import importlib
from dataclasses import dataclass
from typing import Dict, List, Optional, Union

from packaging import version as packaging_version
from packaging.version import Version

from agno.db.base import AsyncBaseDb, BaseDb
from agno.utils.log import log_error, log_info, log_warning

# One place for "how do I apply pending migrations", reused by the AgentOS
# startup warning and anything else that points a user at the migration path.
MIGRATION_HINT = (
    "Apply them with `asyncio.run(MigrationManager(db).up())` (from agno.db.migrations.manager), "
    "or `POST /databases/all/migrate` on AgentOS. "
    "Preview what is pending with `MigrationManager(db).pending()`."
)


@dataclass
class PendingMigration:
    """A table whose stamped schema version is behind the latest available migration."""

    table_type: str
    table_name: str
    current_version: str
    target_version: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "table_type": self.table_type,
            "table_name": self.table_name,
            "current_version": self.current_version,
            "target_version": self.target_version,
        }


class MigrationManager:
    """Manager class to handle database migrations"""

    # Table types migrations know how to handle, mapped to the db attribute
    # holding the configured table name. Tables outside this map are never
    # migrated: they are created fresh at the current schema on first use.
    TABLE_TYPE_TO_ATTR: Dict[str, str] = {
        "memories": "memory_table_name",
        "sessions": "session_table_name",
        "metrics": "metrics_table_name",
        "evals": "eval_table_name",
        "knowledge": "knowledge_table_name",
        "approvals": "approvals_table_name",
        "components": "components_table_name",
        "schedules": "schedules_table_name",
        "schedule_runs": "schedule_runs_table_name",
        "learnings": "learnings_table_name",
    }

    available_versions: list[tuple[str, Version]] = [
        ("v2_0_0", packaging_version.parse("2.0.0")),
        ("v2_3_0", packaging_version.parse("2.3.0")),
        ("v2_5_0", packaging_version.parse("2.5.0")),
        ("v2_5_6", packaging_version.parse("2.5.6")),
        ("v3_0_0", packaging_version.parse("3.0.0")),
    ]

    def __init__(self, db: Union[AsyncBaseDb, BaseDb]):
        self.db = db

    @property
    def latest_schema_version(self) -> Version:
        return self.available_versions[-1][1]

    def _invalidate_table(self, table_name: str) -> None:
        invalidate = getattr(self.db, "_invalidate_table_cache", None)
        if invalidate is not None:
            invalidate(table_name)

    async def _table_exists(self, table_name: str) -> bool:
        """Whether the table is present. Adapters without an existence check are
        treated as having the table, so they are never silently skipped."""
        try:
            if isinstance(self.db, AsyncBaseDb):
                return bool(await self.db.table_exists(table_name))
            return bool(self.db.table_exists(table_name))
        except NotImplementedError:
            return True

    async def pending(self) -> List[PendingMigration]:
        """List the tables whose stamped schema version is behind the latest migration.

        Read-only: nothing is created, altered, or stamped. Tables that do not exist
        yet are not pending; they are created at the current schema on first use.
        Tables the adapter reports no version for are skipped the same way ``up()``
        skips them.
        """
        latest = self.latest_schema_version
        pending: List[PendingMigration] = []
        for table_type, attr in self.TABLE_TYPE_TO_ATTR.items():
            table_name = getattr(self.db, attr, None)
            if not table_name:
                continue
            if not await self._table_exists(table_name):
                continue
            if isinstance(self.db, AsyncBaseDb):
                raw_version = await self.db.get_latest_schema_version(table_name)
            else:
                raw_version = self.db.get_latest_schema_version(table_name)
            if raw_version is None:
                continue
            current_version = packaging_version.parse(raw_version)
            if current_version < latest:
                pending.append(
                    PendingMigration(
                        table_type=table_type,
                        table_name=table_name,
                        current_version=current_version.public,
                        target_version=latest.public,
                    )
                )
        return pending

    def _select_tables(self, table_type: Optional[str]) -> Optional[List[tuple]]:
        """The (table_type, table_name) pairs a migration call applies to, or None for an
        unknown table_type (already logged)."""
        if table_type:
            if table_type not in self.TABLE_TYPE_TO_ATTR:
                log_warning(
                    f"Invalid table type: {table_type}. Use one of: {', '.join(self.TABLE_TYPE_TO_ATTR.keys())}"
                )
                return None
            return [(table_type, getattr(self.db, self.TABLE_TYPE_TO_ATTR[table_type]))]
        return [(tt, getattr(self.db, attr)) for tt, attr in self.TABLE_TYPE_TO_ATTR.items()]

    def _resolve_up_target(self, target_version: Optional[str]) -> Version:
        if not target_version:
            log_info(
                f"No target version provided. Will migrate to the latest available version: {str(self.latest_schema_version)}"
            )
            return self.latest_schema_version
        return packaging_version.parse(target_version)

    def _up_plan(self, table_name: str, raw_version: Optional[str], target: Version, force: bool) -> Optional[tuple]:
        """Decide what an up migration must do for one table.

        Returns None when the table is skipped (no version reported, or already at or
        past the target without force), else ``(current_version, steps)`` where steps
        are the ``(module_suffix, Version)`` pairs to apply, in order.
        """
        if raw_version is None:
            log_warning(
                f"Skipping migration for table {table_name}: the adapter returned no schema version. "
                "Migrations will NOT run for this table. Adapters must return their stamped version, "
                'or "2.0.0" when nothing is stamped yet.'
            )
            return None
        current_version = packaging_version.parse(raw_version)
        if target <= current_version and not force:
            log_info(
                f"Skipping migration: the version of table '{table_name}' ({current_version}) is less or equal to the target version ({target})."
            )
            return None
        log_info(
            f"Starting database migration for table {table_name}. Current version: {current_version}. Target version: {target}."
        )
        steps = [
            (version, normalised)
            for version, normalised in self.available_versions
            if normalised > current_version and normalised <= target
        ]
        return current_version, steps

    def _after_step(self, table_name: str, normalised_version: Version, migration_executed: bool) -> None:
        if migration_executed:
            # The migration changed the table shape; the next access must
            # re-resolve it. No-op steps keep the cache.
            self._invalidate_table(table_name)
            log_info(f"Successfully applied migration {normalised_version} on table {table_name}")
        else:
            log_info(f"Skipping application of migration {normalised_version} on table {table_name}")

    async def up(self, target_version: Optional[str] = None, table_type: Optional[str] = None, force: bool = False):
        """Handle executing an up migration.

        Args:
            target_version: The version to migrate to, e.g. "v3.0.0". If not provided, the latest available version will be used.
            table_type: The type of table to migrate. If not provided, all table types will be considered.
        """
        _target_version = self._resolve_up_target(target_version)
        tables = self._select_tables(table_type)
        if tables is None:
            return

        # Handle migrations for each table separately (extend in future if needed):
        for table_type, table_name in tables:
            if isinstance(self.db, AsyncBaseDb):
                raw_version = await self.db.get_latest_schema_version(table_name)
            else:
                raw_version = self.db.get_latest_schema_version(table_name)
            plan = self._up_plan(table_name, raw_version, _target_version, force)
            if plan is None:
                continue
            _, steps = plan

            latest_version = None
            for version, normalised_version in steps:
                log_info(f"Applying migration {normalised_version} on {table_name}")
                try:
                    migration_executed = await self._up_migration(version, table_type, table_name)
                except BaseException:
                    # A partial migration may have changed the table shape
                    self._invalidate_table(table_name)
                    raise
                self._after_step(table_name, normalised_version, migration_executed)
                # False means "nothing to migrate" — failures raise and abort
                # before stamping, so no-ops still advance the stamp.
                latest_version = normalised_version.public

            if latest_version:
                log_info(f"Storing version {latest_version} in database for table {table_name}")
                if isinstance(self.db, AsyncBaseDb):
                    await self.db.upsert_schema_version(table_name, latest_version)
                else:
                    self.db.upsert_schema_version(table_name, latest_version)
                log_info(f"Successfully stored version {latest_version} in database for table {table_name}")
            log_info("----------------------------------------------------------")

    def up_sync(self, target_version: Optional[str] = None, table_type: Optional[str] = None, force: bool = False):
        """Synchronous twin of ``up()`` for sync adapters (``BaseDb``).

        Sync adapters migrate with blocking calls, so this needs no event loop and is
        safe to call from anywhere, including from inside a running loop or while the
        adapter's table-resolution lock is held (it is reentrant for the same thread).
        Async adapters must ``await up()``.
        """
        if isinstance(self.db, AsyncBaseDb):
            raise TypeError("up_sync() is for sync adapters; await MigrationManager(db).up() for an async adapter")
        _target_version = self._resolve_up_target(target_version)
        tables = self._select_tables(table_type)
        if tables is None:
            return

        for table_type, table_name in tables:
            raw_version = self.db.get_latest_schema_version(table_name)
            plan = self._up_plan(table_name, raw_version, _target_version, force)
            if plan is None:
                continue
            _, steps = plan

            latest_version = None
            for version, normalised_version in steps:
                log_info(f"Applying migration {normalised_version} on {table_name}")
                try:
                    migration_executed = self._up_migration_sync(version, table_type, table_name)
                except BaseException:
                    self._invalidate_table(table_name)
                    raise
                self._after_step(table_name, normalised_version, migration_executed)
                latest_version = normalised_version.public

            if latest_version:
                log_info(f"Storing version {latest_version} in database for table {table_name}")
                self.db.upsert_schema_version(table_name, latest_version)
                log_info(f"Successfully stored version {latest_version} in database for table {table_name}")
            log_info("----------------------------------------------------------")

    async def _up_migration(self, version: str, table_type: str, table_name: str) -> bool:
        """Run the database-specific logic to handle an up migration.

        Args:
            version: The version to migrate to, e.g. "v3.0.0"
        """
        if not isinstance(self.db, AsyncBaseDb):
            return self._up_migration_sync(version, table_type, table_name)
        migration_module = importlib.import_module(f"agno.db.migrations.versions.{version}")
        try:
            return await migration_module.async_up(self.db, table_type, table_name)
        except Exception as e:
            log_error(f"Error running migration to version {version}: {str(e)}")
            raise

    def _up_migration_sync(self, version: str, table_type: str, table_name: str) -> bool:
        """Sync twin of ``_up_migration`` for sync adapters."""
        migration_module = importlib.import_module(f"agno.db.migrations.versions.{version}")
        try:
            return migration_module.up(self.db, table_type, table_name)
        except Exception as e:
            log_error(f"Error running migration to version {version}: {str(e)}")
            raise

    async def down(self, target_version: str, table_type: Optional[str] = None, force: bool = False):
        """Handle executing a down migration.

        Args:
            target_version: The version to migrate to. e.g. "v2.3.0"
            table_type: The type of table to migrate. If not provided, all table types will be considered.
        """
        _target_version = packaging_version.parse(target_version)

        tables = self._select_tables(table_type)
        if tables is None:
            return

        for table_type, table_name in tables:
            if isinstance(self.db, AsyncBaseDb):
                raw_version = await self.db.get_latest_schema_version(table_name)
            else:
                raw_version = self.db.get_latest_schema_version(table_name)

            if raw_version is None:
                log_info(f"Skipping down migration: No version found for table {table_name}.")
                continue
            current_version = packaging_version.parse(raw_version)

            if _target_version >= current_version and not force:
                log_warning(
                    f"Skipping down migration: the version of table '{table_name}' ({current_version}) is less or equal to the target version ({_target_version})."
                )
                continue

            any_migration_executed = False
            # Run down migration for all versions between target and current (include down of current version)
            # Apply down migrations in reverse order to ensure dependencies are met
            for version, normalised_version in reversed(self.available_versions):
                if normalised_version > _target_version:
                    log_info(f"Reverting migration {normalised_version} on table {table_name}")
                    try:
                        migration_executed = await self._down_migration(version, table_type, table_name)
                    except BaseException:
                        # A partial revert may have changed the table shape
                        self._invalidate_table(table_name)
                        raise
                    if migration_executed:
                        self._invalidate_table(table_name)
                    if migration_executed:
                        any_migration_executed = True
                        log_info(f"Successfully reverted migration {normalised_version} on table {table_name}")
                    else:
                        log_info(f"Skipping revert of migration {normalised_version} on table {table_name}")

            if any_migration_executed:
                log_info(f"Storing version {_target_version} in database for table {table_name}")
                if isinstance(self.db, AsyncBaseDb):
                    await self.db.upsert_schema_version(table_name, _target_version.public)
                else:
                    self.db.upsert_schema_version(table_name, _target_version.public)
                log_info(f"Successfully stored version {_target_version} in database for table {table_name}")

    async def _down_migration(self, version: str, table_type: str, table_name: str) -> bool:
        """Run the database-specific logic to handle a down migration.

        Args:
            version: The version to migrate to, e.g. "v3.0.0"
        """
        migration_module = importlib.import_module(f"agno.db.migrations.versions.{version}")
        try:
            if isinstance(self.db, AsyncBaseDb):
                return await migration_module.async_down(self.db, table_type, table_name)
            else:
                return migration_module.down(self.db, table_type, table_name)
        except Exception as e:
            log_error(f"Error running migration to version {version}: {str(e)}")
            raise
