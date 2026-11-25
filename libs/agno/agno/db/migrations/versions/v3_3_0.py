"""Migration v3.3.0: Company Products become Goals

Every agno 3.2 release stored a Company Goal as a Product. This migration renames that storage in
place. No row is copied and no id changes.

In the database that holds the Company tables (SQLite or PostgreSQL):
- The table ``agno_company_products`` becomes ``agno_company_goals``, and the details table named
  after it becomes ``agno_company_goals_details``. A table named with ``goals_table=`` or
  ``products_table=`` keeps its name.
- The column ``purpose`` becomes ``objective`` on the goals table.
- The column ``product_id`` becomes ``goal_id`` on the projects, tasks and sources tables.
- The indexes on a renamed table or column get the names a new database gives them.
- An archived Project or Task records the parent that archived it. A parent of type ``product``
  becomes type ``goal``, which is what restoring a Goal looks for.
- The schema version rows move to the new table names.

In the database that holds the schedules (SQLite, PostgreSQL or MongoDB):
- ``payload.metadata.product_id`` of a Routine becomes ``goal_id``.
- ``work_scope.product_ids`` in a Routine's auto-accept policy becomes ``goal_ids``.
- The ``disabled_reason`` ``company_product_archived`` becomes ``company_goal_archived``.
- ``automation_failure.product_id`` in the output of a schedule run becomes ``goal_id``.

The Company tables change as one unit. MigrationManager calls ``up`` once for each table type, so
the unit runs for the first Company table type it is called with and finds nothing to do for the
others. It acts on the tables and columns the database holds, not on a table's version stamp.

A deployment started on this version before the migration leaves two tables behind: a goals table
holding the Goals it declares, and a details table holding the configured name. When every id in
that goals table is also in the products table, no Goal there was edited, and that details row was
never edited, both are dropped and the 3.2.0 tables take their names. Otherwise the migration raises
``CompanyGoalsMigrationError`` before it changes anything.

PostgreSQL changes the Company tables in one transaction. SQLite keeps a table or column rename
when the transaction around it fails, so there a run that stops part way is finished by the next
run: every step first checks what is already done.
"""

from dataclasses import dataclass
from inspect import signature
from typing import Any, Callable, Dict, List, Optional, Tuple

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.migrations.utils import quote_db_identifier
from agno.db.schemas.goals import goal_metadata
from agno.db.schemas.scheduler import COMPANY_AUTOMATION_SCHEDULE_ID
from agno.db.utils import LEGACY_GOALS_TABLE_NAME
from agno.utils.log import log_info

try:
    from sqlalchemy import JSON, column, select, table, text, update
    from sqlalchemy.dialects.postgresql import JSONB
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")

# The table types whose tables change together.
COMPANY_TABLE_TYPES = ("goals", "sources", "projects", "tasks")

GOALS_TABLE_NAME = "agno_company_goals"
SQL_DB_TYPES = ("PostgresDb", "SqliteDb", "AsyncPostgresDb", "AsyncSqliteDb")
MONGO_DB_TYPES = ("MongoDb", "AsyncMongoDb")
# How long a statement of the migration waits for a table lock on PostgreSQL before it fails.
LOCK_TIMEOUT_SECONDS = 10


class CompanyGoalsMigrationError(RuntimeError):
    """The Company tables cannot be renamed as they are. Nothing was changed."""


@dataclass(frozen=True)
class _CompanyTables:
    schema: Optional[str]
    goals: str
    details: str
    # The 3.2.0 names of the two tables above, when this database uses the default names.
    legacy_goals: Optional[str]
    legacy_details: Optional[str]
    projects: str
    tasks: str
    sources: str
    versions: str

    @classmethod
    def of(cls, db: Any) -> "_CompanyTables":
        default = db.goals_table_name == GOALS_TABLE_NAME
        return cls(
            schema=getattr(db, "db_schema", None),
            goals=db.goals_table_name,
            details=db.company_table_name,
            legacy_goals=LEGACY_GOALS_TABLE_NAME if default else None,
            legacy_details=LEGACY_GOALS_TABLE_NAME + "_details" if default else None,
            projects=db.projects_table_name,
            tasks=db.tasks_table_name,
            sources=db.sources_table_name,
            versions=db.versions_table_name,
        )

    @property
    def all(self) -> List[str]:
        names = [self.goals, self.details, self.legacy_goals, self.legacy_details]
        return [name for name in (*names, self.projects, self.tasks, self.sources) if name is not None]


class _Sql:
    """The statements that differ between SQLite and PostgreSQL."""

    def __init__(self, sess: Any, db_type: str, schema: Optional[str]):
        self.sess = sess
        self.db_type = db_type
        self.postgres = sess.bind.dialect.name == "postgresql"
        self.schema = schema if self.postgres else None
        self.json = JSONB if self.postgres else JSON

    def quote(self, name: str) -> str:
        return quote_db_identifier(self.db_type, name)

    def ref(self, name: str) -> str:
        """A table or index name, with its schema on PostgreSQL."""
        return f"{self.quote(self.schema)}.{self.quote(name)}" if self.schema is not None else self.quote(name)

    def _first(self, statement: str, **params: Any) -> Any:
        return self.sess.execute(text(statement), params).first()

    def table_exists(self, name: str) -> bool:
        if self.postgres:
            found = self._first(
                "SELECT 1 FROM information_schema.tables WHERE table_schema = :schema AND table_name = :name",
                schema=self.schema,
                name=name,
            )
        else:
            found = self._first("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :name", name=name)
        return found is not None

    def columns(self, name: str) -> List[str]:
        if self.postgres:
            rows = self.sess.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :name"
                ),
                {"schema": self.schema, "name": name},
            ).fetchall()
            return [row[0] for row in rows]
        return [row[1] for row in self.sess.execute(text(f"PRAGMA table_info({self.quote(name)})")).fetchall()]

    def indexes(self, table_name: str) -> List[str]:
        if self.postgres:
            statement = "SELECT indexname FROM pg_indexes WHERE schemaname = :schema AND tablename = :name"
            params: Dict[str, Any] = {"schema": self.schema, "name": table_name}
        else:
            statement = "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = :name"
            params = {"name": table_name}
        return [row[0] for row in self.sess.execute(text(statement), params).fetchall()]

    def rename_table(self, old: str, new: str) -> None:
        self.sess.execute(text(f"ALTER TABLE {self.ref(old)} RENAME TO {self.quote(new)}"))

    def drop_table(self, name: str) -> None:
        self.sess.execute(text(f"DROP TABLE {self.ref(name)}"))

    def rename_column(self, table_name: str, old: str, new: str) -> None:
        self.sess.execute(
            text(f"ALTER TABLE {self.ref(table_name)} RENAME COLUMN {self.quote(old)} TO {self.quote(new)}")
        )

    def rename_index(self, old: str, new: str) -> bool:
        """Give an index the name a new database uses. Returns whether it has that name now.

        SQLite cannot rename an index, so it is created again from the statement SQLite stored for
        it, with only the name changed. That keeps UNIQUE, the WHERE clause, the column order and
        the collation of an index the user added. An index whose stored statement cannot be read
        that way keeps its name and its definition.

        SQLite creates the new index before dropping the old one, so a run that stops between the
        two leaves the old name for the next run to find.

        SQLite names an index within the whole database. When the new name already belongs to an
        index of another table, or to one with another definition, the old index is the only one
        with this definition. It keeps its name and is not dropped.
        """
        if self.postgres:
            self.sess.execute(text(f"ALTER INDEX {self.ref(old)} RENAME TO {self.quote(new)}"))
            return True
        find = "SELECT sql, tbl_name FROM sqlite_master WHERE type = 'index' AND name = :name"
        source = self._first(find, name=old)
        renamed = _sqlite_index_under_name(source[0] if source else None, old, self.quote(new))
        if renamed is None:
            return False
        create, stored_as = renamed
        taken = self._first(find, name=new)
        if taken is not None and (taken[1] != source[1] or taken[0] != stored_as):
            return False
        self.sess.execute(text(create))
        self.sess.execute(text(f"DROP INDEX {self.quote(old)}"))
        return True

    def drop_index(self, name: str) -> None:
        self.sess.execute(text(f"DROP INDEX {self.ref(name)}"))


def _sqlite_index_under_name(stored: Optional[str], old: str, quoted_new: str) -> Optional[Tuple[str, str]]:
    """The statement that creates a stored SQLite index again under another name, if it is not there yet.

    Returned with the statement SQLite then stores for the new index, which tells whether an index
    that already has the new name is the same one.

    SQLite stores an index as ``CREATE INDEX`` or ``CREATE UNIQUE INDEX``, then the name as it was
    written, then the rest of the statement. None when the name is not found in that place.
    """
    for head in ("CREATE UNIQUE INDEX ", "CREATE INDEX "):
        if stored is None or not stored.startswith(head):
            continue
        rest = stored[len(head) :]
        for written in (f'"{old}"', f"`{old}`", f"[{old}]", f"'{old}'", old):
            if not rest.startswith(written):
                continue
            after = rest[len(written) :]
            if written == old and after[:1] not in ("", " ", "\t", "\n", "\r", "("):
                # The bare name is only the start of a longer name.
                continue
            return f"{head}IF NOT EXISTS {quoted_new}{after}", f"{head}{quoted_new}{after}"
    return None


def _goal_rows(sql: _Sql, table_name: str, objective: str) -> Dict[str, Any]:
    """The rows of a goals table by id, with the objective read from the given column."""
    rows = table(
        table_name,
        column("id"),
        column("name"),
        column(objective),
        column("user_id"),
        column("metadata", sql.json),
        column("updated_at"),
        column("deleted_at"),
        schema=sql.schema,
    )
    found = sql.sess.execute(select(rows)).mappings().all()
    return {row["id"]: {**row, "objective": row[objective]} for row in found}


def _goal_edited(current: Dict[str, Any], stored: Dict[str, Any]) -> bool:
    """Whether a Goal in the new table holds a change that its 3.2.0 row does not.

    Start-up links Routines, which moves updated_at, so an updated row is compared by content.
    """
    if current["updated_at"] is None and current["deleted_at"] is None:
        return False
    current_metadata, stored_metadata = goal_metadata(current["metadata"]), goal_metadata(stored["metadata"])
    linked = set(current_metadata.pop("routine_ids", None) or [])
    if linked - set(stored_metadata.pop("routine_ids", None) or []):
        return True
    return (
        any(current[field] != stored[field] for field in ("name", "objective", "user_id"))
        or (current["deleted_at"] is None) != (stored["deleted_at"] is None)
        or current_metadata != stored_metadata
    )


def _left_by_an_early_start(sql: _Sql, tables: _CompanyTables) -> Tuple[bool, bool]:
    """Whether the goals table and the details table hold only what a start before this migration wrote.

    Each is True when the table exists beside its 3.2.0 table and can be dropped. Raises when it
    holds anything else, before the migration changes a table.
    """
    drop_goals = drop_details = False
    if tables.legacy_goals and sql.table_exists(tables.legacy_goals) and sql.table_exists(tables.goals):
        declared = _goal_rows(sql, tables.goals, "objective")
        stored = _goal_rows(sql, tables.legacy_goals, "purpose")
        only_new = sorted(set(declared) - set(stored))
        if only_new:
            raise CompanyGoalsMigrationError(
                f"Tables {tables.legacy_goals} and {tables.goals} both hold Goals, and {tables.goals} holds ids "
                f"that {tables.legacy_goals} does not: {only_new}. Nothing was changed. Copy those rows into "
                f"{tables.legacy_goals} with their old column names, or delete them, then run the migration again."
            )
        changed = sorted(id for id, row in declared.items() if _goal_edited(row, stored[id]))
        if changed:
            raise CompanyGoalsMigrationError(
                f"Tables {tables.legacy_goals} and {tables.goals} both hold Goals, and {tables.goals} holds rows "
                f"that were changed: {changed}. Nothing was changed by the migration. Copy the changes you want "
                f"to keep into {tables.legacy_goals} with its column names, delete those rows from "
                f"{tables.goals}, then run the migration again."
            )
        drop_goals = True
    if tables.legacy_details and sql.table_exists(tables.legacy_details) and sql.table_exists(tables.details):
        edited = sql._first(f"SELECT 1 FROM {sql.ref(tables.details)} WHERE created_at <> updated_at")
        if edited is not None:
            raise CompanyGoalsMigrationError(
                f"Tables {tables.legacy_details} and {tables.details} both hold company details, and the row in "
                f"{tables.details} was edited. Nothing was changed. Drop the table whose details you do not "
                "want to keep, then run the migration again."
            )
        drop_details = True
    return drop_goals, drop_details


def _rename_table(sql: _Sql, legacy: Optional[str], current: str, drop_current: bool) -> bool:
    """Give a 3.2.0 table its current name, and its indexes the names that go with it."""
    changed = False
    if legacy is not None and sql.table_exists(legacy):
        if drop_current:
            sql.drop_table(current)
        sql.rename_table(legacy, current)
        changed = True
    if legacy is None or not sql.table_exists(current):
        return changed
    # A renamed table keeps the index names of its old name.
    for index in sql.indexes(current):
        if index.startswith(f"idx_{legacy}_"):
            changed = sql.rename_index(index, f"idx_{current}_" + index[len(f"idx_{legacy}_") :]) or changed
        elif sql.postgres and index == f"{legacy}_pkey":
            changed = sql.rename_index(index, f"{current}_pkey") or changed
    return changed


def _rename_column(sql: _Sql, table_name: str, old: str, new: str) -> bool:
    """Rename one column and its single-column index."""
    if not sql.table_exists(table_name):
        return False
    changed = False
    columns = sql.columns(table_name)
    if old in columns and new not in columns:
        sql.rename_column(table_name, old, new)
        columns = sql.columns(table_name)
        changed = True
    old_index, new_index = f"idx_{table_name}_{old}", f"idx_{table_name}_{new}"
    indexes = sql.indexes(table_name)
    if new in columns and old_index in indexes:
        if new_index in indexes and sql.postgres:
            sql.drop_index(old_index)
            changed = True
        else:
            # On SQLite this also checks an index that already has the new name.
            changed = sql.rename_index(old_index, new_index) or changed
    return changed


def _rename_pending(sess: Any, db_type: str, tables: _CompanyTables) -> bool:
    """Whether a Company table still has its 3.2.0 name or columns."""
    sql = _Sql(sess, db_type, tables.schema)
    legacy = (tables.legacy_goals, tables.legacy_details)
    if any(name is not None and sql.table_exists(name) for name in legacy):
        return True
    old_columns = (
        (tables.goals, "purpose"),
        *((n, "product_id") for n in (tables.projects, tables.tasks, tables.sources)),
    )
    return any(sql.table_exists(name) and old in sql.columns(name) for name, old in old_columns)


def company_rename_pending(db: BaseDb) -> bool:
    """Whether this database still holds a Company table in its 3.2.0 shape."""
    if not _is_db_type(db, SQL_DB_TYPES):
        return False
    with db.Session() as sess:  # type: ignore
        return _rename_pending(sess, type(db).__name__, _CompanyTables.of(db))


async def acompany_rename_pending(db: AsyncBaseDb) -> bool:
    """Async version of company_rename_pending."""
    if not _is_db_type(db, SQL_DB_TYPES):
        return False
    tables = _CompanyTables.of(db)
    async with db.async_session_factory() as sess:  # type: ignore
        return await sess.run_sync(lambda sync_sess: _rename_pending(sync_sess, type(db).__name__, tables))


def _goal_parent(event: Any) -> Any:
    """A transition as it is when a Goal archived the record."""
    parent = event.get("archived_by") if isinstance(event, dict) else None
    if isinstance(parent, dict) and parent.get("type") == "product":
        return {**event, "archived_by": {**parent, "type": "goal"}}
    return event


def _rename_archive_parents(sql: _Sql, table_name: str) -> bool:
    """Archived records name the Goal that archived them, so restoring the Goal restores them."""
    if not sql.table_exists(table_name) or "transitions" not in sql.columns(table_name):
        return False
    rows = table(table_name, column("id"), column("transitions", sql.json), column("deleted_at"), schema=sql.schema)
    changed = False
    archived = sql.sess.execute(select(rows.c.id, rows.c.transitions).where(rows.c.deleted_at.is_not(None))).all()
    for row in archived:
        if not isinstance(row.transitions, list):
            continue
        renamed = [_goal_parent(event) for event in row.transitions]
        if renamed != row.transitions:
            sql.sess.execute(update(rows).where(rows.c.id == row.id).values(transitions=renamed))
            changed = True
    return changed


def _move_version_stamps(sql: _Sql, tables: _CompanyTables) -> bool:
    """A renamed table's schema version is recorded under its current name."""
    if not sql.table_exists(tables.versions):
        return False
    versions = sql.ref(tables.versions)
    changed = False
    for legacy, current in ((tables.legacy_goals, tables.goals), (tables.legacy_details, tables.details)):
        if legacy is None or sql._first(f"SELECT 1 FROM {versions} WHERE table_name = :name", name=legacy) is None:
            continue
        if sql._first(f"SELECT 1 FROM {versions} WHERE table_name = :name", name=current) is None:
            statement = f"UPDATE {versions} SET table_name = :current WHERE table_name = :legacy"
            sql.sess.execute(text(statement), {"current": current, "legacy": legacy})
        else:
            sql.sess.execute(text(f"DELETE FROM {versions} WHERE table_name = :legacy"), {"legacy": legacy})
        changed = True
    return changed


def _rename_company(sess: Any, db_type: str, tables: _CompanyTables) -> bool:
    """Rename every Company table, column and stored value that names a Product."""
    sql = _Sql(sess, db_type, tables.schema)
    drop_goals, drop_details = _left_by_an_early_start(sql, tables)
    changed = _rename_table(sql, tables.legacy_goals, tables.goals, drop_goals)
    changed = _rename_table(sql, tables.legacy_details, tables.details, drop_details) or changed
    changed = _rename_column(sql, tables.goals, "purpose", "objective") or changed
    for name in (tables.projects, tables.tasks, tables.sources):
        changed = _rename_column(sql, name, "product_id", "goal_id") or changed
    for name in (tables.projects, tables.tasks):
        changed = _rename_archive_parents(sql, name) or changed
    return _move_version_stamps(sql, tables) or changed


def _goal_routine(schedule: Dict[str, Any]) -> Dict[str, Any]:
    """The fields of a Routine that name a Product, as they are for a Goal. Empty when none does."""
    changes: Dict[str, Any] = {}
    if schedule.get("managed_by") != "company":
        return changes
    payload = schedule.get("payload")
    if isinstance(payload, dict) and isinstance(payload.get("metadata"), dict):
        renamed = dict(payload["metadata"])
        if "product_id" in renamed and "goal_id" not in renamed:
            renamed["goal_id"] = renamed.pop("product_id")
        policy = renamed.get("auto_accept")
        if isinstance(policy, dict) and isinstance(policy.get("work_scope"), dict):
            scope = policy["work_scope"]
            if "product_ids" in scope and "goal_ids" not in scope:
                scope = {"goal_ids" if key == "product_ids" else key: value for key, value in scope.items()}
                renamed["auto_accept"] = {**policy, "work_scope": scope}
        if renamed != payload["metadata"]:
            changes["payload"] = {**payload, "metadata": renamed}
    if schedule.get("disabled_reason") == "company_product_archived":
        changes["disabled_reason"] = "company_goal_archived"
    return changes


def _goal_failure(output: Any) -> Optional[Dict[str, Any]]:
    """A schedule run's output with its failure record naming the Goal. None when it already does."""
    failure = output.get("automation_failure") if isinstance(output, dict) else None
    if not isinstance(failure, dict) or "product_id" not in failure or "goal_id" in failure:
        return None
    renamed = {"goal_id" if key == "product_id" else key: value for key, value in failure.items()}
    return {**output, "automation_failure": renamed}


def _rename_routines(sess: Any, db_type: str, schema: Optional[str], table_name: str) -> bool:
    sql = _Sql(sess, db_type, schema)
    if not sql.table_exists(table_name) or "managed_by" not in sql.columns(table_name):
        return False
    rows = table(
        table_name,
        column("id"),
        column("managed_by"),
        column("payload", sql.json),
        column("disabled_reason"),
        schema=sql.schema,
    )
    changed = False
    routines = sess.execute(select(rows).where(rows.c.managed_by == "company")).mappings().all()
    for routine in routines:
        changes = _goal_routine(dict(routine))
        if changes:
            sess.execute(update(rows).where(rows.c.id == routine["id"]).values(**changes))
            changed = True
    return changed


def _rename_failures(sess: Any, db_type: str, schema: Optional[str], table_name: str) -> bool:
    sql = _Sql(sess, db_type, schema)
    if not sql.table_exists(table_name):
        return False
    rows = table(table_name, column("id"), column("schedule_id"), column("output", sql.json), schema=sql.schema)
    changed = False
    runs = sess.execute(select(rows.c.id, rows.c.output).where(rows.c.schedule_id == COMPANY_AUTOMATION_SCHEDULE_ID))
    for run in runs.all():
        output = _goal_failure(run.output)
        if output is not None:
            sess.execute(update(rows).where(rows.c.id == run.id).values(output=output))
            changed = True
    return changed


def _sql_step(db: Any, table_type: str) -> Optional[Callable[[Any], bool]]:
    """What this migration does for one table type on SQLite or PostgreSQL, given a session."""
    db_type = type(db).__name__
    schema = getattr(db, "db_schema", None)
    if table_type in COMPANY_TABLE_TYPES:
        tables = _CompanyTables.of(db)
        return lambda sess: _rename_company(sess, db_type, tables)
    if table_type == "schedules":
        return lambda sess: _rename_routines(sess, db_type, schema, db.schedules_table_name)
    if table_type == "schedule_runs":
        return lambda sess: _rename_failures(sess, db_type, schema, db.schedule_runs_table_name)
    return None


def _is_db_type(db: Any, names: Tuple[str, ...]) -> bool:
    """Whether db is one of the named adapters or a subclass, without importing their drivers."""
    return any(cls.__name__ in names for cls in type(db).__mro__)


def _invalidate_company_tables(db: Any, table_type: str) -> None:
    """The Company tables changed shape together, so each is resolved again on its next use."""
    if table_type in COMPANY_TABLE_TYPES:
        for name in _CompanyTables.of(db).all:
            db._invalidate_table_cache(name)


def _keeping_updated_at(update_schedule: Any) -> Dict[str, Any]:
    return {"preserve_updated_at": True} if "preserve_updated_at" in signature(update_schedule).parameters else {}


def _written(result: Any, what: str) -> None:
    if result is None:
        raise RuntimeError(f"Migration v3.3.0 could not update {what}")


def _rename_mongo(db: BaseDb, table_type: str) -> bool:
    """Rename the stored values of Routines and of their failure history through the adapter."""
    changed = False
    page = 1
    if table_type == "schedules":
        while True:
            schedules, total = db.get_schedules(limit=100, page=page, raise_on_error=True)
            for schedule in schedules:
                changes = _goal_routine(schedule)
                if changes:
                    kept = _keeping_updated_at(db.update_schedule)
                    _written(db.update_schedule(schedule["id"], **kept, **changes), f"schedule {schedule['id']}")
                    changed = True
            if page * 100 >= total:
                return changed
            page += 1
    if table_type == "schedule_runs":
        while True:
            runs, total = db.get_schedule_runs(  # type: ignore[call-arg]
                COMPANY_AUTOMATION_SCHEDULE_ID, limit=100, page=page, raise_on_error=True
            )
            for run in runs:
                output = _goal_failure(run.get("output"))
                if output is not None:
                    _written(db.update_schedule_run(run["id"], output=output), f"schedule run {run['id']}")
                    changed = True
            if page * 100 >= total:
                return changed
            page += 1
    return False


async def _arename_mongo(db: AsyncBaseDb, table_type: str) -> bool:
    """Async version of _rename_mongo."""
    changed = False
    page = 1
    if table_type == "schedules":
        while True:
            schedules, total = await db.get_schedules(limit=100, page=page, raise_on_error=True)
            for schedule in schedules:
                changes = _goal_routine(schedule)
                if changes:
                    kept = _keeping_updated_at(db.update_schedule)
                    updated = await db.update_schedule(schedule["id"], **kept, **changes)
                    _written(updated, f"schedule {schedule['id']}")
                    changed = True
            if page * 100 >= total:
                return changed
            page += 1
    if table_type == "schedule_runs":
        while True:
            runs, total = await db.get_schedule_runs(  # type: ignore[call-arg]
                COMPANY_AUTOMATION_SCHEDULE_ID, limit=100, page=page, raise_on_error=True
            )
            for run in runs:
                output = _goal_failure(run.get("output"))
                if output is not None:
                    _written(await db.update_schedule_run(run["id"], output=output), f"schedule run {run['id']}")
                    changed = True
            if page * 100 >= total:
                return changed
            page += 1
    return False


def _limit_lock_wait(sess: Any) -> None:
    """On PostgreSQL, stop waiting for a table lock after LOCK_TIMEOUT_SECONDS, for this transaction.

    A rename waits for every session that has read the table in an open transaction, and every
    later query on the table waits behind the rename. Without a limit, one session left open keeps
    the migration, and an AgentOS that migrates as it starts, waiting for as long as it stays open.
    """
    if sess.bind.dialect.name == "postgresql":
        sess.execute(text(f"SET LOCAL lock_timeout = '{int(LOCK_TIMEOUT_SECONDS)}s'"))


def up(db: BaseDb, table_type: str, table_name: str) -> bool:
    """
    Rename the storage of Company Products to Goals. See the module docstring for the changes.

    The changes for the Company table types are applied together, for whichever of them is given.

    Returns:
        bool: True if any migration was applied, False otherwise.
    """
    if _is_db_type(db, MONGO_DB_TYPES):
        return _rename_mongo(db, table_type)
    step = _sql_step(db, table_type) if _is_db_type(db, SQL_DB_TYPES) else None
    if step is None:
        return False
    try:
        with db.Session() as sess, sess.begin():  # type: ignore
            _limit_lock_wait(sess)
            return step(sess)
    finally:
        _invalidate_company_tables(db, table_type)


async def async_up(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """
    Rename the storage of Company Products to Goals. See the module docstring for the changes.

    The changes for the Company table types are applied together, for whichever of them is given.

    Returns:
        bool: True if any migration was applied, False otherwise.
    """
    if _is_db_type(db, MONGO_DB_TYPES):
        return await _arename_mongo(db, table_type)
    step = _sql_step(db, table_type) if _is_db_type(db, SQL_DB_TYPES) else None
    if step is None:
        return False
    try:
        async with db.async_session_factory() as sess, sess.begin():  # type: ignore
            await sess.run_sync(_limit_lock_wait)
            return await sess.run_sync(step)
    finally:
        _invalidate_company_tables(db, table_type)


def down(db: BaseDb, table_type: str, table_name: str) -> bool:
    """
    The rename of Company Products to Goals is not reverted.

    Returns:
        bool: Always False. Nothing is changed.
    """
    if table_type == "goals":
        log_info("The rename of Company Products to Goals is not reverted: the tables keep their Goal names")
    return False


async def async_down(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """
    The rename of Company Products to Goals is not reverted.

    Returns:
        bool: Always False. Nothing is changed.
    """
    return down(db, table_type, table_name)  # type: ignore[arg-type]
