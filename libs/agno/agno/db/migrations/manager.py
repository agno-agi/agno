import importlib
from typing import Optional, Union

from packaging import version as packaging_version
from packaging.version import Version

from agno.db.base import AsyncBaseDb, BaseDb
from agno.utils.log import log_error, log_info, log_warning


class MigrationManager:
    """Manager class to handle database migrations"""

    available_versions: list[tuple[str, Version]] = [
        ("v2_0_0", packaging_version.parse("2.0.0")),
        ("v2_3_0", packaging_version.parse("2.3.0")),
        ("v2_5_0", packaging_version.parse("2.5.0")),
    ]

    def __init__(self, db: Union[AsyncBaseDb, BaseDb]):
        self.db = db

    @property
    def latest_schema_version(self) -> Version:
        return self.available_versions[-1][1]

    async def up(self, target_version: Optional[str] = None, table_type: Optional[str] = None, force: bool = False):
        """Handle executing an up migration.

        Args:
            target_version: The version to migrate to, e.g. "v3.0.0". If not provided, the latest available version will be used.
            table_type: The type of table to migrate. If not provided, all table types will be considered.
        """

        # If not target version is provided, use the latest available version
        if not target_version:
            _target_version = self.latest_schema_version
            log_info(
                f"No target version provided. Will migrate to the latest available version: {str(_target_version)}"
            )
        else:
            _target_version = packaging_version.parse(target_version)

        # Mapping from table_type to db attribute name
        _table_type_to_attr = {
            "memories": "memory_table_name",
            "sessions": "session_table_name",
            "metrics": "metrics_table_name",
            "evals": "eval_table_name",
            "knowledge": "knowledge_table_name",
            "culture": "culture_table_name",
        }

        # Select tables to migrate
        if table_type:
            if table_type not in _table_type_to_attr:
                log_warning(f"Invalid table type: {table_type}. Use one of: {', '.join(_table_type_to_attr.keys())}")
                return
            tables = [(table_type, getattr(self.db, _table_type_to_attr[table_type]))]
        else:
            tables = [(tt, getattr(self.db, attr)) for tt, attr in _table_type_to_attr.items()]

        # Handle migrations for each table separately (extend in future if needed):
        for table_type, table_name in tables:
            if isinstance(self.db, AsyncBaseDb):
                current_version = packaging_version.parse(await self.db.get_latest_schema_version(table_name))
            else:
                current_version = packaging_version.parse(self.db.get_latest_schema_version(table_name))

            if current_version is None:
                log_info(f"Skipping migration: No version found for table {table_name}.")
                continue

            # If the target version is less or equal to the current version, no migrations needed
            if _target_version <= current_version and not force:
                log_info(
                    f"Skipping migration: the version of table '{table_name}' ({current_version}) is less or equal to the target version ({_target_version})."
                )
                continue

            log_info(
                f"Starting database migration for table {table_name}. Current version: {current_version}. Target version: {_target_version}."
            )

            # Find files after the current version
            latest_version = None
            for version, normalised_version in self.available_versions:
                if normalised_version > current_version:
                    if target_version and normalised_version > _target_version:
                        break

                    log_info(f"Applying migration {normalised_version} on {table_name}")
                    migration_executed = await self._up_migration(version, table_type, table_name)
                    latest_version = normalised_version.public
                    if migration_executed:
                        latest_version = normalised_version.public
                        log_info(f"Successfully applied migration {normalised_version} on table {table_name}")
                    else:
                        log_info(f"Skipping application of migration {normalised_version} on table {table_name}")

            if latest_version:
                log_info(f"Storing version {latest_version} in database for table {table_name}")
                if isinstance(self.db, AsyncBaseDb):
                    await self.db.upsert_schema_version(table_name, latest_version)
                else:
                    self.db.upsert_schema_version(table_name, latest_version)
                log_info(f"Successfully stored version {latest_version} in database for table {table_name}")
            log_info("----------------------------------------------------------")

    async def _up_migration(self, version: str, table_type: str, table_name: str) -> bool:
        """Run the database-specific logic to handle an up migration.

        Args:
            version: The version to migrate to, e.g. "v3.0.0"
        """
        migration_module = importlib.import_module(f"agno.db.migrations.versions.{version}")

        try:
            if isinstance(self.db, AsyncBaseDb):
                return await migration_module.async_up(self.db, table_type, table_name)
            else:
                return migration_module.up(self.db, table_type, table_name)
        except Exception as e:
            log_error(f"Error running migration to version {version}: {e}")
            raise

    async def down(self, target_version: str, table_type: Optional[str] = None, force: bool = False):
        """Handle executing a down migration.

        Args:
            target_version: The version to migrate to. e.g. "v2.3.0"
            table_type: The type of table to migrate. If not provided, all table types will be considered.
        """
        _target_version = packaging_version.parse(target_version)

        # Mapping from table_type to db attribute name
        _table_type_to_attr = {
            "memories": "memory_table_name",
            "sessions": "session_table_name",
            "metrics": "metrics_table_name",
            "evals": "eval_table_name",
            "knowledge": "knowledge_table_name",
            "culture": "culture_table_name",
        }

        # Select tables to migrate
        if table_type:
            if table_type not in _table_type_to_attr:
                log_warning(f"Invalid table type: {table_type}. Use one of: {', '.join(_table_type_to_attr.keys())}")
                return
            tables = [(table_type, getattr(self.db, _table_type_to_attr[table_type]))]
        else:
            tables = [(tt, getattr(self.db, attr)) for tt, attr in _table_type_to_attr.items()]

        for table_type, table_name in tables:
            if isinstance(self.db, AsyncBaseDb):
                current_version = packaging_version.parse(await self.db.get_latest_schema_version(table_name))
            else:
                current_version = packaging_version.parse(self.db.get_latest_schema_version(table_name))

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
                    migration_executed = await self._down_migration(version, table_type, table_name)
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
            log_error(f"Error running migration to version {version}: {e}")
            raise
