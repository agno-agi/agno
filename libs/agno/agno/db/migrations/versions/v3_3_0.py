"""Migration v3.3.0: Company Products become Goals, and Company files move into one file system

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

Company files
-------------

Before 3.3.0 each folder of the Company file tree was its own namespace of the file table. From
3.3.0 every Company file is a row of the namespace ``company``, stored at its path in the tree:

    company/wiki                     path p  ->  company   wiki/p
    company/products/<id>/wiki       path p  ->  company   goals/<id>/p
    company/tasks/<id>               path p  ->  company   tasks/<id>/p
    company/notes                    path p  ->  company   notes/p

Rows are rewritten in place: content, version and timestamps do not change. The files move after
the Company tables are renamed, on the same session, for any Company table type, in every database
that holds a file table. On PostgreSQL the tables and the files change in one transaction. The move
reads its state from the file table, so a second run finds nothing to move and a run that stopped
halfway is finished by the next one. A different file already stored at a new path stops the
migration with ``CompanyFilesMigrationError``. The summary delivery state of a Goal, in
``company/products/<id>/summary-state``, is not a file of the tree and does not move.

A Company table is stamped with the current version when it is created, so MigrationManager does not
trust that stamp while ``company_files_pending`` finds a file to move. Until the files have moved, an
AgentOS with Company does not start: files left in the namespaces from before would look empty.

Notes were stored in the AgentOS database. A deployment with a separate Company database calls
``move_company_notes`` once to move them into the Company database. Until it has, AgentOS does not
start: notes left in the AgentOS database would look empty.
"""

from dataclasses import dataclass
from inspect import signature
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import unquote

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

        def company(sess: Any) -> bool:
            changed = _rename_company(sess, db_type, tables)
            # After the rename, on the same session: the folders are named with the ids of the Goals and Tasks.
            return _move_company_files(sess, db) or changed

        return company
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


# ---------------------------------------------------------------------------
# Company files: one file system
# ---------------------------------------------------------------------------

COMPANY_NAMESPACE = "company"
_WIKI, _NOTES = "company/wiki", "company/notes"
_GOAL_PREFIX, _GOAL_SUFFIX, _TASK_PREFIX = "company/products/", "/wiki", "company/tasks/"


class CompanyFilesMigrationError(RuntimeError):
    """A Company file cannot move because another file is already stored at its new path."""


def _goal_segment(namespace: str) -> Optional[str]:
    """The id part of a Goal's page namespace, or None for any other namespace."""
    if not namespace.startswith(_GOAL_PREFIX) or not namespace.endswith(_GOAL_SUFFIX):
        return None
    segment = namespace[len(_GOAL_PREFIX) : -len(_GOAL_SUFFIX)]
    return segment if segment and "/" not in segment else None


def _task_segment(namespace: str) -> Optional[str]:
    """The id part of a Task's folder namespace, or None for any other namespace."""
    if not namespace.startswith(_TASK_PREFIX):
        return None
    segment = namespace[len(_TASK_PREFIX) :]
    return segment if segment and "/" not in segment else None


def _file_table(db: Any, conn: Any, create: bool = False, any_schema: bool = False) -> Any:
    """The file table of a database, read and written on the given connection.

    None when the database cannot hold files, or holds no file table and none is to be created.
    With ``any_schema`` a table from before user partitions is returned too, for a statement that
    reads only its namespace and path columns.
    """
    from copy import copy

    from sqlalchemy import inspect

    from agno.fs import FileSystem

    try:
        # A SQLite or PostgreSQL database keeps its files in a database table.
        backend: Any = copy(FileSystem(db, namespace=COMPANY_NAMESPACE, user_scoped=False).backend)
    except (TypeError, ValueError):
        return None
    backend._bound_connection = conn
    if create:
        backend._ensure_table()
    elif not inspect(conn).has_table(backend.table_name, schema=backend.db_schema):
        return None
    elif not any_schema:
        backend._require_current_schema()
    return backend.table


def _old_namespaces(conn: Any, files: Any) -> List[str]:
    """The namespaces of the file table that hold Company files in the layout before 3.3.0."""
    from sqlalchemy import or_

    rows = conn.execute(
        select(files.c.namespace)
        .where(
            or_(
                files.c.namespace.in_([_WIKI, _NOTES]),
                files.c.namespace.startswith(_GOAL_PREFIX, autoescape=True),
                files.c.namespace.startswith(_TASK_PREFIX, autoescape=True),
            )
        )
        .distinct()
    ).all()
    # A prefix match ignores case on SQLite, so each name is checked again here.
    found = {row[0] for row in rows}
    return sorted(
        name
        for name in found
        if name in (_WIKI, _NOTES) or _goal_segment(name) is not None or _task_segment(name) is not None
    )


def _goals_and_tasks(sess: Any, db: Any, namespaces: List[str]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """The Goals and the Task ids the old namespaces may name, read after the rename.

    Read on the session that renamed the tables, and only when a namespace names a Goal or a Task.
    """
    tables = _CompanyTables.of(db)
    sql = _Sql(sess, type(db).__name__, tables.schema)
    goals: List[Dict[str, Any]] = []
    task_ids: List[str] = []
    if any(_goal_segment(name) is not None for name in namespaces) and sql.table_exists(tables.goals):
        rows = sess.execute(text(f"SELECT id, name, objective FROM {sql.ref(tables.goals)}")).fetchall()
        goals = [{"id": row[0], "name": row[1], "objective": row[2]} for row in rows]
    if any(_task_segment(name) is not None for name in namespaces) and sql.table_exists(tables.tasks):
        rows = sess.execute(text(f"SELECT id FROM {sql.ref(tables.tasks)}")).fetchall()
        task_ids = [str(row[0]) for row in rows]
    return goals, task_ids


def _record_id(segment: str, ids: Dict[str, str]) -> str:
    """The id a namespace segment stands for.

    A namespace stored its id in lower case with other characters escaped. The record with that
    form gives the id as it is written. A folder whose record is gone keeps the unescaped segment.
    """
    return ids.get(segment) or unquote(segment)


def _folders(
    namespaces: List[str], goals: List[Dict[str, Any]], task_ids: List[str]
) -> Tuple[Dict[str, str], Dict[str, Dict[str, str]]]:
    """The folder each old namespace moves into, and the default pages of each folder that has them."""
    from agno.company.playbook import _defaults
    from agno.fs._paths import sanitize_namespace_segment

    goal_rows = {sanitize_namespace_segment(str(goal["id"])): goal for goal in goals}
    goal_ids = {segment: str(goal["id"]) for segment, goal in goal_rows.items()}
    tasks = {sanitize_namespace_segment(task_id): task_id for task_id in task_ids}
    folders: Dict[str, str] = {}
    defaults: Dict[str, Dict[str, str]] = {}
    for namespace in namespaces:
        if namespace == _WIKI:
            folders[namespace] = "wiki"
            defaults["wiki"] = _defaults(None)
        elif namespace == _NOTES:
            folders[namespace] = "notes"
        elif (segment := _goal_segment(namespace)) is not None:
            folder = folders[namespace] = f"goals/{_record_id(segment, goal_ids)}"
            if segment in goal_rows:
                defaults[folder] = _defaults(goal_rows[segment])
        elif (segment := _task_segment(namespace)) is not None:
            folders[namespace] = f"tasks/{_record_id(segment, tasks)}"
    return folders, defaults


def _move(conn: Any, files: Any, folders: Dict[str, str], defaults: Dict[str, Dict[str, str]]) -> int:
    """Move every row of each old namespace to its tree path in the Company namespace.

    A file already at the new path is settled first: the same content means the file is there
    already, and a default page that nobody edited gives way to the page that moves in. Any other
    file at the new path stops the move before a row changes.
    """
    from sqlalchemy import and_, delete, literal

    settled: List[Tuple[str, str, str, bool]] = []
    blocked: List[str] = []
    for namespace, folder in folders.items():
        prefix = f"{folder}/"
        old, new = files.alias("old"), files.alias("new")
        clashes = conn.execute(
            select(old.c.user_id, old.c.path, old.c.content, new.c.content, new.c.version)
            .select_from(
                old.join(
                    new,
                    and_(
                        new.c.namespace == COMPANY_NAMESPACE,
                        new.c.user_id == old.c.user_id,
                        new.c.path == literal(prefix).concat(old.c.path),
                    ),
                )
            )
            .where(old.c.namespace == namespace)
        ).all()
        for user_id, path, content, existing, existing_version in clashes:
            if existing == content:
                settled.append((namespace, user_id, path, False))
            elif existing_version == 1 and existing == defaults.get(folder, {}).get(path):
                settled.append((namespace, user_id, path, True))
            else:
                blocked.append(f"{prefix}{path}")
    if blocked:
        raise CompanyFilesMigrationError(
            "Company files were not moved: a different file is already stored at "
            f"{', '.join(sorted(blocked))}. Rename or delete one of the two, then run the migration again."
        )
    for namespace, user_id, path, replace_default in settled:
        if replace_default:
            # The default page gives way; the page from the old namespace moves in below.
            conn.execute(
                delete(files).where(
                    files.c.user_id == user_id,
                    files.c.namespace == COMPANY_NAMESPACE,
                    files.c.path == f"{folders[namespace]}/{path}",
                )
            )
        else:
            conn.execute(
                delete(files).where(files.c.user_id == user_id, files.c.namespace == namespace, files.c.path == path)
            )
    moved = 0
    for namespace, folder in folders.items():
        result = conn.execute(
            update(files)
            .where(files.c.namespace == namespace)
            .values(namespace=COMPANY_NAMESPACE, path=literal(f"{folder}/").concat(files.c.path))
        )
        moved += result.rowcount or 0
    return moved


def _move_company_files(sess: Any, db: Any) -> bool:
    """Move the Company files of the session's database into the Company file system.

    Runs on the session that renamed the Company tables, so on PostgreSQL the tables and the files
    change together or not at all. True when a row moved.
    """
    conn = sess.connection()
    files = _file_table(db, conn)
    if files is None:
        return False
    namespaces = _old_namespaces(conn, files)
    if not namespaces:
        return False
    folders, defaults = _folders(namespaces, *_goals_and_tasks(sess, db, namespaces))
    moved = _move(conn, files, folders, defaults)
    log_info(f"Moved {moved} Company files into the Company file system")
    return True


def _files_pending(sess: Any, db: Any) -> bool:
    """Whether the file table holds a namespace that ``_move_company_files`` moves. One statement on the table."""
    conn = sess.connection()
    files = _file_table(db, conn, any_schema=True)
    return files is not None and bool(_old_namespaces(conn, files))


def company_files_pending(db: BaseDb) -> bool:
    """Whether this database still holds Company files in their namespaces from before 3.3.0."""
    if not _is_db_type(db, SQL_DB_TYPES):
        return False
    with db.Session() as sess:  # type: ignore
        return _files_pending(sess, db)


async def acompany_files_pending(db: Any) -> bool:
    """Async variant of ``company_files_pending``. The database may be synchronous."""
    if not isinstance(db, AsyncBaseDb):
        return company_files_pending(db)
    if not _is_db_type(db, SQL_DB_TYPES):
        return False
    async with db.async_session_factory() as sess:  # type: ignore
        return await sess.run_sync(lambda sync_sess: _files_pending(sync_sess, db))


def move_company_files(db: BaseDb) -> bool:
    """Move the Company files of a SQLite or PostgreSQL database into the Company file system.

    ``MigrationManager`` does this with the Company tables. True when a row moved.
    """
    if not _is_db_type(db, SQL_DB_TYPES):
        return False
    with db.Session() as sess, sess.begin():  # type: ignore
        return _move_company_files(sess, db)


async def amove_company_files(db: AsyncBaseDb) -> bool:
    """Async variant of ``move_company_files``."""
    if not _is_db_type(db, SQL_DB_TYPES):
        return False
    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        return await sess.run_sync(lambda sync_sess: _move_company_files(sync_sess, db))


# Notes kept in another database

_NOTE_COLUMNS = ("user_id", "path", "content", "size_bytes", "version", "created_at", "updated_at")


def _read_notes(sess: Any, db: Any) -> List[Dict[str, Any]]:
    """Every note of a database, with the fields that must not change."""
    conn = sess.connection()
    files = _file_table(db, conn)
    if files is None:
        return []
    rows = conn.execute(
        select(*(files.c[name] for name in _NOTE_COLUMNS)).where(
            files.c.namespace == COMPANY_NAMESPACE, files.c.path.startswith("notes/", autoescape=True)
        )
    ).all()
    # A prefix match ignores case on SQLite, so each path is checked again here.
    return [dict(zip(_NOTE_COLUMNS, row)) for row in rows if row[1].startswith("notes/")]


def _write_notes(sess: Any, db: Any, notes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Store notes as they are, and return them once every one is stored with the same content.

    A different note already at a path stops the copy before a row is written.
    """
    conn = sess.connection()
    files = _file_table(db, conn, create=True)
    present = {
        (row[0], row[1]): row[2]
        for row in conn.execute(
            select(files.c.user_id, files.c.path, files.c.content).where(
                files.c.namespace == COMPANY_NAMESPACE, files.c.path.startswith("notes/", autoescape=True)
            )
        ).all()
    }
    blocked = sorted(
        note["path"]
        for note in notes
        if (note["user_id"], note["path"]) in present and present[(note["user_id"], note["path"])] != note["content"]
    )
    if blocked:
        raise CompanyFilesMigrationError(
            "Notes were not moved: a different note is already stored in the Company database at "
            f"{', '.join(blocked)}. Rename or delete one of the two, then run the move again."
        )
    missing = [note for note in notes if (note["user_id"], note["path"]) not in present]
    if missing:
        conn.execute(files.insert(), [{"namespace": COMPANY_NAMESPACE, **note} for note in missing])
    return notes


def _delete_notes(sess: Any, db: Any, notes: List[Dict[str, Any]]) -> int:
    """Remove notes that are stored in the Company database now."""
    from sqlalchemy import delete

    conn = sess.connection()
    files = _file_table(db, conn)
    for note in notes:
        conn.execute(
            delete(files).where(
                files.c.namespace == COMPANY_NAMESPACE,
                files.c.user_id == note["user_id"],
                files.c.path == note["path"],
                files.c.version == note["version"],
            )
        )
    return len(notes)


def _same_file_table(source_db: Any, company_db: Any) -> bool:
    """Whether two databases keep their files in one table: the same database, schema and table."""
    from agno.fs import FileSystem

    def place(db: Any) -> tuple:
        backend: Any = FileSystem(db, namespace=COMPANY_NAMESPACE, user_scoped=False).backend
        url = backend.db_engine.url
        return (url.get_backend_name(), url.host, url.port, url.database, backend.db_schema, backend.table_name)

    return place(source_db) == place(company_db)


def _notes_can_move(source_db: Any, company_db: Any) -> bool:
    if not _is_db_type(source_db, SQL_DB_TYPES) or not _is_db_type(company_db, SQL_DB_TYPES):
        return False
    # Notes in the Company database are where they belong: copying them onto themselves would remove them.
    return not _same_file_table(source_db, company_db)


def _take_notes(sess: Any, db: Any) -> List[Dict[str, Any]]:
    """The notes of a database, after any still in the namespace from before 3.3.0 are put in notes/."""
    conn = sess.connection()
    files = _file_table(db, conn)
    if files is None:
        return []
    _move(conn, files, {_NOTES: "notes"}, {})
    return _read_notes(sess, db)


def _notes_wait(sess: Any, db: Any) -> bool:
    """Whether a database holds a note, in the namespace from before 3.3.0 or in notes/. One statement on the table."""
    from sqlalchemy import and_, func, or_

    conn = sess.connection()
    files = _file_table(db, conn, any_schema=True)
    if files is None:
        return False
    # substr compares case on SQLite and PostgreSQL alike; a prefix match ignores it on SQLite.
    in_notes = and_(files.c.namespace == COMPANY_NAMESPACE, func.substr(files.c.path, 1, len("notes/")) == "notes/")
    found = conn.execute(select(files.c.path).where(or_(files.c.namespace == _NOTES, in_notes)).limit(1))
    return found.first() is not None


def _in_session(db: Any, step: Callable[[Any], Any]) -> Any:
    with db.Session() as sess, sess.begin():
        return step(sess)


async def _ain_session(db: Any, step: Callable[[Any], Any]) -> Any:
    """Run a step on a session of a database, asynchronous or not."""
    if not isinstance(db, AsyncBaseDb):
        return _in_session(db, step)
    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        return await sess.run_sync(step)


def company_notes_to_move(source_db: BaseDb, company_db: BaseDb) -> bool:
    """Whether the AgentOS database holds notes that ``move_company_notes`` moves to the Company database.

    False when the two keep their files in one table: the notes are where they belong.
    """
    if not _notes_can_move(source_db, company_db):
        return False
    return _in_session(source_db, lambda sess: _notes_wait(sess, source_db))


async def acompany_notes_to_move(source_db: Any, company_db: Any) -> bool:
    """Async variant of ``company_notes_to_move``. Either database may be synchronous."""
    if not _notes_can_move(source_db, company_db):
        return False
    return await _ain_session(source_db, lambda sess: _notes_wait(sess, source_db))


def move_company_notes(source_db: BaseDb, company_db: BaseDb) -> int:
    """Move notes/ from the AgentOS database to the Company database, for a deployment that keeps two.

    Before 3.3.0 notes were stored in the AgentOS database. From 3.3.0 they are a folder of the
    Company file system, in the Company database. Each note is copied with its content, version and
    timestamps, and removed from the AgentOS database after the copy is stored. Returns the number
    of notes moved.

    Notes are moved from the namespace 3.2.0 kept them in and from notes/, so the call does not
    depend on ``MigrationManager`` having run on the AgentOS database. Calling it again moves
    nothing, and a call that stopped after the copy is finished by the next one. Use
    ``amove_company_notes`` when either database is asynchronous.
    """
    if not _notes_can_move(source_db, company_db):
        return 0
    notes = _in_session(source_db, lambda sess: _take_notes(sess, source_db))
    if not notes:
        return 0
    stored = _in_session(company_db, lambda sess: _write_notes(sess, company_db, notes))
    return _in_session(source_db, lambda sess: _delete_notes(sess, source_db, stored))


async def amove_company_notes(source_db: Any, company_db: Any) -> int:
    """Async variant of ``move_company_notes``. Either database may be synchronous."""
    if not _notes_can_move(source_db, company_db):
        return 0
    notes = await _ain_session(source_db, lambda sess: _take_notes(sess, source_db))
    if not notes:
        return 0
    stored = await _ain_session(company_db, lambda sess: _write_notes(sess, company_db, notes))
    return await _ain_session(source_db, lambda sess: _delete_notes(sess, source_db, stored))


def up(db: BaseDb, table_type: str, table_name: str) -> bool:
    """
    Rename the storage of Company Products to Goals, then move the Company files into one file
    system. See the module docstring for the changes.

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
    Rename the storage of Company Products to Goals, then move the Company files into one file
    system. See the module docstring for the changes.

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
    The rename of Company Products to Goals is not reverted, and the Company files are not moved back.

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
