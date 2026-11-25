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

No table is dropped. The versions table records, for each of the two tables, that its rename is done
or that it was created under its current name. An agno 3.2 process that starts after that creates its products
and details tables again: those are left as they are and not used. Where a table stands beside its
3.2.0 table and nothing is recorded, the migration raises ``CompanyGoalsMigrationError`` before it
changes anything.

PostgreSQL changes the Company tables in one transaction. SQLite keeps a table or column rename
when the transaction around it fails, so there a run that stops part way is finished by the next
run: every step first checks what is already done.

Company files
-------------

Before 3.3.0 each folder of the Company file tree was its own namespace of the file table. From
3.3.0 every Company file is a row of the namespace ``company``, stored at its path in the tree:

    company/wiki                     path p  ->  company   wiki/p
    company/products/<id>/wiki       path p  ->  company   goals/<folder>/p
    company/tasks/<id>               path p  ->  company   tasks/<folder>/p
    company/notes                    path p  ->  company   notes/p

``<folder>`` is ``agno.company.filesystem.folder_name`` of the Goal or Task id: the id as one path
segment. 3.2.0 wrote an id into a namespace lower-cased, with a slash kept, so the owner of a
namespace is found among the records of this database: the one Goal or Task whose id 3.2.0 would
have written that way.

Rows are rewritten in place: content, version and timestamps do not change. Only rows of the shared
partition are Company files; a user's rows are left alone. The files move after the Company tables
are renamed, on the same session, for any Company table type, in every database that holds a file
table. On PostgreSQL the tables and the files change in one transaction. The move reads its state
from the file table, so a second run finds nothing to move and a run that stopped halfway is
finished by the next one. A different file already stored at a new path stops the migration with
``CompanyFilesMigrationError``. The summary delivery state of a Goal, in
``company/products/<id>/summary-state``, is not a file of the tree and does not move.

The migration never guesses where a file belongs. A namespace stays where it is, and is reported
in the log and by ``company_files_left``, when no Goal or Task of this database has its id, or when
several have: 3.2.0 kept the pages of ``Docs`` and ``docs`` in one namespace. Such a namespace does
not keep the migration pending. ``move_company_files(db, owners={namespace: id})`` moves it to the
owner it is given.

A Company table is stamped with the current version when it is created, so MigrationManager does not
trust that stamp while ``company_files_pending`` finds a file to move. Until the files have moved, the
Company file system refuses every use with ``MigrationRequiredError``: files left in the namespaces
from before would look like an empty store. AgentOS starts, so the migration can be run through it.

Notes were stored in the AgentOS database. For a deployment with a separate Company database,
AgentOS moves them into the Company database as it starts, after it has migrated both, with
``move_company_notes``. Where it could not, notes/ is refused with ``MigrationRequiredError`` until
that call has run: notes left in the AgentOS database would look empty.
"""

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from inspect import signature
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from uuid import uuid4

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.migrations.utils import quote_db_identifier
from agno.db.schemas.scheduler import COMPANY_AUTOMATION_SCHEDULE_ID
from agno.db.utils import LEGACY_GOALS_TABLE_NAME
from agno.utils.log import log_info, log_warning

try:
    from sqlalchemy import JSON, column, select, table, text, update
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
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


def _has_rows(sql: _Sql, name: str) -> bool:
    return sql._first(f"SELECT 1 FROM {sql.ref(name)}") is not None


# The value of a rename record. A table's stamp is always a version, so no stamp is read as a record.
RENAMED = "renamed"


def _rename_record(legacy: str, current: str) -> str:
    """The row of the versions table that records the rename of one table.

    No table has this name: SQLite reserves the prefix, and it is longer than PostgreSQL allows.
    """
    return f"sqlite_agno_migration_record:{current}:renamed_from:{legacy}"


def _rename_recorded(sql: _Sql, tables: _CompanyTables, legacy: str, current: str) -> bool:
    """Whether the database records that a Company table carries its current name."""
    if not sql.table_exists(tables.versions):
        return False
    statement = f"SELECT 1 FROM {sql.ref(tables.versions)} WHERE table_name = :name AND version = :renamed"
    return sql._first(statement, name=_rename_record(legacy, current), renamed=RENAMED) is not None


def _record_rename(sql: _Sql, tables: _CompanyTables, legacy: Optional[str], current: str) -> bool:
    """Record that one rename is done, so a 3.2.0 table found later is known to be created after it.

    Each table has its own record: one of them can be settled while the other is not.
    """
    if legacy is None or not sql.table_exists(tables.versions) or not sql.table_exists(current):
        return False
    if _rename_recorded(sql, tables, legacy, current):
        return False
    sql.sess.execute(
        text(
            f"INSERT INTO {sql.ref(tables.versions)} (table_name, version, created_at) "
            "VALUES (:name, :renamed, :now) ON CONFLICT (table_name) DO NOTHING"
        ),
        {"name": _rename_record(legacy, current), "renamed": RENAMED, "now": datetime.now().isoformat()},
    )
    return True


def _is_pending(sql: _Sql, tables: _CompanyTables, legacy: Optional[str], current: str) -> bool:
    """Whether a 3.2.0 table still has to take its current name.

    An agno 3.2 process that starts after the rename creates its tables again. The record of the
    rename says that those are not the stored data.
    """
    if legacy is None or not sql.table_exists(legacy):
        return False
    if not sql.table_exists(current):
        return True
    return _has_rows(sql, legacy) and not _rename_recorded(sql, tables, legacy, current)


def _refuse_two_tables(sql: _Sql, tables: _CompanyTables) -> None:
    """Raise when a table stands beside its 3.2.0 table and no rename is recorded.

    Either could be the one to keep. The current table is not dropped even when it is empty: another
    session could add a row before the drop.
    """
    for legacy, current in ((tables.legacy_goals, tables.goals), (tables.legacy_details, tables.details)):
        if _is_pending(sql, tables, legacy, current) and sql.table_exists(current):
            raise CompanyGoalsMigrationError(
                f"Tables {legacy} and {current} both exist. Nothing was changed. Stop the processes that use them, "
                f"keep the rows you want in {legacy}, under its column names, drop {current}, then run the "
                "migration again."
            )


def _rename_table(sql: _Sql, tables: _CompanyTables, legacy: Optional[str], current: str) -> bool:
    """Give a 3.2.0 table its current name, and its indexes the names that go with it."""
    changed = False
    if legacy is not None and _is_pending(sql, tables, legacy, current):
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
    pairs = ((tables.legacy_goals, tables.goals), (tables.legacy_details, tables.details))
    if any(_is_pending(sql, tables, legacy, current) for legacy, current in pairs):
        return True
    old_columns = (
        (tables.goals, "purpose"),
        *((n, "product_id") for n in (tables.projects, tables.tasks, tables.sources)),
    )
    return any(sql.table_exists(name) and old in sql.columns(name) for name, old in old_columns)


def _table_pending(sess: Any, db_type: str, tables: _CompanyTables, table_type: str) -> bool:
    sql = _Sql(sess, db_type, tables.schema)
    if table_type == "goals":
        return _is_pending(sql, tables, tables.legacy_goals, tables.goals)
    return _is_pending(sql, tables, tables.legacy_details, tables.details)


def company_table_pending(db: Any, table_type: str) -> bool:
    """Whether the goals or the company details table is still stored under its 3.2.0 name."""
    with db.Session() as sess:
        return _table_pending(sess, type(db).__name__, _CompanyTables.of(db), table_type)


async def acompany_table_pending(db: Any, table_type: str) -> bool:
    """Async version of company_table_pending."""
    tables = _CompanyTables.of(db)
    async with db.async_session_factory() as sess:
        return await sess.run_sync(lambda sync_sess: _table_pending(sync_sess, type(db).__name__, tables, table_type))


def _record_created(sess: Any, db_type: str, tables: _CompanyTables, table_type: str) -> None:
    sql = _Sql(sess, db_type, tables.schema)
    if table_type == "goals":
        _record_rename(sql, tables, tables.legacy_goals, tables.goals)
    else:
        _record_rename(sql, tables, tables.legacy_details, tables.details)


def record_company_table(db: Any, table_type: str) -> None:
    """Record that the goals or the company details table was created under its current name."""
    with db.Session() as sess, sess.begin():
        _record_created(sess, type(db).__name__, _CompanyTables.of(db), table_type)


async def arecord_company_table(db: Any, table_type: str) -> None:
    """Async version of record_company_table."""
    tables = _CompanyTables.of(db)
    async with db.async_session_factory() as sess, sess.begin():
        await sess.run_sync(lambda sync_sess: _record_created(sync_sess, type(db).__name__, tables, table_type))


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
    _refuse_two_tables(sql, tables)
    changed = _rename_table(sql, tables, tables.legacy_goals, tables.goals)
    changed = _rename_table(sql, tables, tables.legacy_details, tables.details) or changed
    changed = _rename_column(sql, tables.goals, "purpose", "objective") or changed
    for name in (tables.projects, tables.tasks, tables.sources):
        changed = _rename_column(sql, name, "product_id", "goal_id") or changed
    for name in (tables.projects, tables.tasks):
        changed = _rename_archive_parents(sql, name) or changed
    changed = _move_version_stamps(sql, tables) or changed
    changed = _record_rename(sql, tables, tables.legacy_goals, tables.goals) or changed
    return _record_rename(sql, tables, tables.legacy_details, tables.details) or changed


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
# Company wrote the shared partition only, so a row of a user's partition is never a Company file.
_SHARED = ""
_WIKI, _NOTES = "company/wiki", "company/notes"
_GOAL_PREFIX, _GOAL_SUFFIX, _TASK_PREFIX = "company/products/", "/wiki", "company/tasks/"
# The paths of one namespace a log line names before it counts the rest.
_REPORTED_PATHS = 20
# The namespaces already reported as left in place, by database: one run of the migration calls the
# file move once for each Company table type, and says it once.
_reported_left: Set[Tuple[str, Tuple[str, ...]]] = set()


class CompanyFilesMigrationError(RuntimeError):
    """Company files cannot be moved as they are. No file was changed."""


def _is_goal_namespace(namespace: str) -> bool:
    named = len(namespace) > len(_GOAL_PREFIX) + len(_GOAL_SUFFIX)
    return named and namespace.startswith(_GOAL_PREFIX) and namespace.endswith(_GOAL_SUFFIX)


def _is_task_namespace(namespace: str) -> bool:
    return len(namespace) > len(_TASK_PREFIX) and namespace.startswith(_TASK_PREFIX)


def _namespace_before(name: str) -> Optional[str]:
    """A namespace as agno 3.2.0 stored it: composed, lower-cased and escaped, with a slash kept.

    None when that version could store nothing under the name.
    """
    from agno.fs._paths import normalize_namespace
    from agno.fs.errors import InvalidPathError

    try:
        return normalize_namespace(name)
    except InvalidPathError:
        return None


class _OnConnection:
    """A connection, read the way the statements of this module read a session."""

    def __init__(self, conn: Any):
        self.bind = conn.engine
        self._conn = conn

    def execute(self, statement: Any, parameters: Any = None) -> Any:
        return self._conn.execute(statement, parameters or {})

    def connection(self) -> Any:
        return self._conn


def _file_backend(db: Any, conn: Any, create: bool = False) -> Any:
    """The file table of a database, read and written on the given connection.

    None when the database cannot hold files, or holds no file table and none is to be created.
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
    return backend


def _has_user_partitions(backend: Any) -> bool:
    """Whether the file table has the user partition.

    A table from before it is refused by every file operation, so no version that had Company wrote
    a file to one: it holds nothing to move.
    """
    return backend._is_current(*backend._schema_state())


def _old_namespace_names(conn: Any, files: Any) -> List[str]:
    """The namespaces of the file table that are named as Company named its own before 3.3.0.

    One statement, on the namespace column alone, so it runs on a file table of any age.
    """
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
        name for name in found if name in (_WIKI, _NOTES) or _is_goal_namespace(name) or _is_task_namespace(name)
    )


def _waiting_namespaces(conn: Any, backend: Any) -> List[str]:
    """The namespaces from before 3.3.0 that hold a Company file: a file of the shared partition."""
    files = backend.table
    names = _old_namespace_names(conn, files)
    if not names or not _has_user_partitions(backend):
        return []
    rows = conn.execute(
        select(files.c.namespace).where(files.c.user_id == _SHARED, files.c.namespace.in_(names)).distinct()
    )
    return sorted(row[0] for row in rows)


def _records(sess: Any, db: Any, goals: bool, tasks: bool) -> Tuple[List[Dict[str, Any]], List[str]]:
    """The Goals and the Task ids in the Company tables of this database, before or after the rename."""
    tables = _CompanyTables.of(db)
    sql = _Sql(sess, type(db).__name__, tables.schema)
    goal_rows: List[Dict[str, Any]] = []
    task_ids: List[str] = []
    if goals:
        name = next((n for n in (tables.goals, tables.legacy_goals) if n is not None and sql.table_exists(n)), None)
        if name is not None:
            objective = "objective" if "objective" in sql.columns(name) else "purpose"
            rows = sess.execute(text(f"SELECT id, name, {sql.quote(objective)} FROM {sql.ref(name)}")).fetchall()
            goal_rows = [{"id": str(row[0]), "name": row[1], "objective": row[2]} for row in rows]
    if tasks and sql.table_exists(tables.tasks):
        rows = sess.execute(text(f"SELECT id FROM {sql.ref(tables.tasks)}")).fetchall()
        task_ids = [str(row[0]) for row in rows]
    return goal_rows, task_ids


@dataclass
class _Plan:
    """Where the files of each waiting namespace go, and the namespaces that stay.

    A namespace stays when the Goal or Task it belongs to is not certain: no record of this database
    has its id, or more than one has. ``left`` names the ids that could own it.
    """

    folders: Dict[str, str]
    defaults: Dict[str, Dict[str, str]]
    left: Dict[str, List[str]]


def _plan(sess: Any, db: Any, namespaces: List[str], owners: Optional[Dict[str, str]] = None) -> _Plan:
    """Decide where each waiting namespace goes. ``owners`` names the owner of a namespace by hand."""
    from agno.company.filesystem import folder_name
    from agno.company.playbook import _defaults

    owners = owners or {}
    goal_spaces = [name for name in namespaces if _is_goal_namespace(name)]
    task_spaces = [name for name in namespaces if _is_task_namespace(name)]
    goals, task_ids = _records(sess, db, bool(goal_spaces), bool(task_spaces))
    by_id = {goal["id"]: goal for goal in goals}
    # 3.2.0 lower-cased an id in a namespace and kept its slashes, so two ids can name one namespace.
    goal_owners: Dict[str, List[str]] = {}
    for goal in goals:
        goal_owners.setdefault(_namespace_before(_GOAL_PREFIX + goal["id"] + _GOAL_SUFFIX) or "", []).append(goal["id"])
    task_owners: Dict[str, List[str]] = {}
    for task_id in task_ids:
        task_owners.setdefault(_namespace_before(_TASK_PREFIX + task_id) or "", []).append(task_id)

    for namespace, owner in owners.items():
        known = by_id if namespace in goal_spaces else task_ids if namespace in task_spaces else None
        if known is None:
            raise CompanyFilesMigrationError(
                f"{namespace} holds no files of a Goal or a Task that wait to be moved, so it takes no owner."
            )
        if owner not in known:
            kind = "Goal" if namespace in goal_spaces else "Task"
            raise CompanyFilesMigrationError(f"{owner!r} is not the id of a {kind} in this database.")

    plan = _Plan({}, {}, {})
    for namespace in namespaces:
        if namespace == _WIKI:
            plan.folders[namespace] = "wiki"
            plan.defaults["wiki"] = _defaults(None)
        elif namespace == _NOTES:
            plan.folders[namespace] = "notes"
        else:
            is_goal = namespace in goal_spaces
            could_own = sorted((goal_owners if is_goal else task_owners).get(namespace, []))
            if namespace in owners:
                could_own = [owners[namespace]]
            if len(could_own) != 1:
                plan.left[namespace] = could_own
            elif is_goal:
                folder = plan.folders[namespace] = f"goals/{folder_name(could_own[0])}"
                plan.defaults[folder] = _defaults(by_id[could_own[0]])
            else:
                plan.folders[namespace] = f"tasks/{folder_name(could_own[0])}"
    # An owner named by hand can send a second namespace to a folder. One run moves one namespace into
    # a folder, so a page both hold is found in the way by the next run and nothing is overwritten.
    into: Dict[str, List[str]] = {}
    for namespace, folder in plan.folders.items():
        into.setdefault(folder, []).append(namespace)
    shared = {folder: names for folder, names in into.items() if len(names) > 1}
    if shared:
        folder, names = sorted(shared.items())[0]
        raise CompanyFilesMigrationError(
            f"Company files were not moved: {' and '.join(sorted(names))} would both move into {folder}/. "
            "Move one of them first, then name the owner of the other."
        )
    return plan


def _move(conn: Any, files: Any, folders: Dict[str, str], defaults: Dict[str, Dict[str, str]]) -> int:
    """Move every shared row of each old namespace to its tree path in the Company namespace.

    A file already at the new path is settled first. The same content means the file is there
    already: of the two rows the one with the higher version stays, so no version a client read
    is given out again. A default page that nobody edited gives way to the page that moves in.
    Any other file at the new path stops the move before a row changes.
    """
    from sqlalchemy import and_, delete, literal

    give_way: List[Tuple[str, str]] = []
    already_there: List[Tuple[str, str]] = []
    blocked: List[str] = []
    for namespace, folder in folders.items():
        prefix = f"{folder}/"
        old, new = files.alias("old"), files.alias("new")
        clashes = conn.execute(
            select(old.c.path, old.c.content, old.c.version, new.c.content, new.c.version)
            .select_from(
                old.join(
                    new,
                    and_(
                        new.c.namespace == COMPANY_NAMESPACE,
                        new.c.user_id == _SHARED,
                        new.c.path == literal(prefix).concat(old.c.path),
                    ),
                )
            )
            .where(old.c.namespace == namespace, old.c.user_id == _SHARED)
        ).all()
        for path, content, version, existing, existing_version in clashes:
            unedited_default = existing_version == 1 and existing == defaults.get(folder, {}).get(path)
            if existing == content and existing_version > version:
                already_there.append((namespace, path))
            elif existing == content or unedited_default:
                give_way.append((COMPANY_NAMESPACE, f"{prefix}{path}"))
            else:
                blocked.append(f"{prefix}{path}")
    if blocked:
        raise CompanyFilesMigrationError(
            "Company files were not moved: a different file is already stored at "
            f"{', '.join(sorted(blocked))}. Rename or delete one of the two, then run the migration again."
        )
    # Each row removed here has its content in the row that stays.
    for namespace, path in (*give_way, *already_there):
        conn.execute(
            delete(files).where(files.c.user_id == _SHARED, files.c.namespace == namespace, files.c.path == path)
        )
    moved = 0
    for namespace, folder in folders.items():
        result = conn.execute(
            update(files)
            .where(files.c.namespace == namespace, files.c.user_id == _SHARED)
            .values(namespace=COMPANY_NAMESPACE, path=literal(f"{folder}/").concat(files.c.path))
        )
        moved += result.rowcount or 0
    return moved


def _paths_left(conn: Any, files: Any, left: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    """Each namespace that stays, with the paths of its files and the ids that could own it."""
    rows = conn.execute(
        select(files.c.namespace, files.c.path).where(files.c.user_id == _SHARED, files.c.namespace.in_(list(left)))
    ).all()
    paths: Dict[str, List[str]] = {namespace: [] for namespace in left}
    for namespace, path in rows:
        paths[namespace].append(path)
    return [
        {"namespace": namespace, "paths": sorted(paths[namespace]), "owners": left[namespace]}
        for namespace in sorted(left)
    ]


def _report_left(entries: List[Dict[str, Any]]) -> None:
    lines = []
    for entry in entries:
        kind = "Goal" if _is_goal_namespace(entry["namespace"]) else "Task"
        named = entry["paths"][:_REPORTED_PATHS]
        more = len(entry["paths"]) - len(named)
        paths = ", ".join(named) + (f" and {more} more" if more else "")
        if entry["owners"]:
            why = f"3.2.0 kept the files of these {kind}s in this one namespace: {', '.join(entry['owners'])}"
        else:
            why = f"no {kind} of this database has its id"
        lines.append(f"{entry['namespace']} ({paths}): {why}")
    log_warning(
        "Company files were left where a version before 3.3.0 kept them, because the migration cannot be sure "
        "which Goal or Task they belong to. " + ". ".join(lines) + ". They keep their content and versions. To "
        "move a namespace, name its owner: `move_company_files(db, owners={'<namespace>': '<goal or task id>'})` "
        "from `agno.db.migrations.versions.v3_3_0`, or `await amove_company_files(...)` in async code."
    )


def _report_foreign(conn: Any, files: Any) -> None:
    """Name the files already in the Company namespace that are not in the tree: another filesystem wrote them."""
    rows = conn.execute(
        select(files.c.path).where(files.c.namespace == COMPANY_NAMESPACE, files.c.user_id == _SHARED)
    ).all()
    areas = ("wiki", "goals", "tasks", "notes")
    foreign = sorted(row[0] for row in rows if "/" not in row[0] or row[0].split("/", 1)[0] not in areas)
    if not foreign:
        return
    named = ", ".join(foreign[:_REPORTED_PATHS])
    more = f" and {len(foreign) - _REPORTED_PATHS} more" if len(foreign) > _REPORTED_PATHS else ""
    log_warning(
        f"The namespace {COMPANY_NAMESPACE!r} now belongs to the Company file system, and another filesystem stored "
        f"files there: {named}{more}. They are left in place. Agents can no longer open that namespace: move the "
        "files to a namespace of their own."
    )


def _report_size(conn: Any, files: Any, db: Any) -> None:
    """Say so when the store holds more than it may. Before 3.3.0 each folder had a limit of its own."""
    from sqlalchemy import func

    from agno.company.filesystem import company_filesystem_bytes

    held = conn.execute(
        select(func.coalesce(func.sum(files.c.size_bytes), 0)).where(
            files.c.namespace == COMPANY_NAMESPACE, files.c.user_id == _SHARED
        )
    ).scalar()
    limit = company_filesystem_bytes(db)
    if int(held or 0) > limit:
        log_warning(
            f"The Company file system holds {int(held)} bytes after the move and its limit is {limit} bytes, so "
            "every write that grows it is refused. Reads are not affected. Remove files, or raise the limit with "
            "`CompanyConfig(max_filesystem_bytes=...)`."
        )


def _move_company_files(sess: Any, db: Any, owners: Optional[Dict[str, str]] = None) -> bool:
    """Move the Company files of the session's database into the Company file system.

    Runs on the session that renamed the Company tables, so on PostgreSQL the tables and the files
    change together or not at all. True when a namespace moved.
    """
    conn = sess.connection()
    backend = _file_backend(db, conn)
    namespaces = _waiting_namespaces(conn, backend) if backend is not None else []
    if not namespaces:
        if owners:
            raise CompanyFilesMigrationError(f"No file waits in {', '.join(sorted(owners))}.")
        return False
    plan = _plan(sess, db, namespaces, owners)
    if plan.folders:
        _report_foreign(conn, backend.table)
        moved = _move(conn, backend.table, plan.folders, plan.defaults)
        log_info(f"Moved {moved} Company files into the Company file system")
        _report_size(conn, backend.table, db)
    reported = (conn.engine.url.render_as_string(hide_password=True), tuple(sorted(plan.left)))
    if plan.left and reported not in _reported_left:
        _reported_left.add(reported)
        _report_left(_paths_left(conn, backend.table, plan.left))
    return bool(plan.folders)


def _files_state(conn: Any, db: Any) -> Tuple[bool, Dict[str, str]]:
    """Whether a namespace waits to be moved, and the folders whose files stay because several records could own them.

    Each such folder comes with the namespace that holds its files. One statement on the file table
    when nothing is named as Company named its namespaces.
    """
    from agno.company.filesystem import folder_name

    backend = _file_backend(db, conn)
    namespaces = _waiting_namespaces(conn, backend) if backend is not None else []
    if not namespaces:
        return False, {}
    plan = _plan(_OnConnection(conn), db, namespaces)
    unsettled = {
        f"{'goals' if _is_goal_namespace(namespace) else 'tasks'}/{folder_name(owner)}": namespace
        for namespace, owners in plan.left.items()
        for owner in owners
    }
    return bool(plan.folders), unsettled


def _files_wait(conn: Any, db: Any) -> bool:
    """Whether the file table holds a namespace that ``_move_company_files`` moves."""
    return _files_state(conn, db)[0]


def _files_left(sess: Any, db: Any) -> List[Dict[str, Any]]:
    conn = sess.connection()
    backend = _file_backend(db, conn)
    namespaces = _waiting_namespaces(conn, backend) if backend is not None else []
    left = _plan(sess, db, namespaces).left if namespaces else {}
    return _paths_left(conn, backend.table, left) if left else []


# SQLite refuses a writer while another connection writes, where PostgreSQL makes it wait. A step is one
# transaction that is safe to run again, so it is tried again for this long.
_BUSY_TRIES = 100
_BUSY_WAIT_SECONDS = 0.1


def _busy(exc: BaseException, attempt: int) -> bool:
    return attempt < _BUSY_TRIES - 1 and "database is locked" in str(exc)


def _in_session(db: Any, step: Callable[[Any], Any]) -> Any:
    """Run a step in one transaction of a database."""
    for attempt in range(_BUSY_TRIES):
        try:
            with db.Session() as sess, sess.begin():
                return step(sess)
        except OperationalError as exc:
            if not _busy(exc, attempt):
                raise
            time.sleep(_BUSY_WAIT_SECONDS)


async def _ain_session(db: Any, step: Callable[[Any], Any]) -> Any:
    """Run a step in one transaction of a database, asynchronous or not."""
    if not isinstance(db, AsyncBaseDb):
        return _in_session(db, step)
    for attempt in range(_BUSY_TRIES):
        try:
            async with db.async_session_factory() as sess, sess.begin():  # type: ignore
                return await sess.run_sync(step)
        except OperationalError as exc:
            if not _busy(exc, attempt):
                raise
            await asyncio.sleep(_BUSY_WAIT_SECONDS)


def company_files_pending(db: BaseDb) -> bool:
    """Whether this database still holds Company files that the migration moves."""
    if not _is_db_type(db, SQL_DB_TYPES):
        return False
    return _in_session(db, lambda sess: _files_wait(sess.connection(), db))


async def acompany_files_pending(db: Any) -> bool:
    """Async variant of ``company_files_pending``. The database may be synchronous."""
    if not _is_db_type(db, SQL_DB_TYPES):
        return False
    return await _ain_session(db, lambda sess: _files_wait(sess.connection(), db))


def company_files_left(db: BaseDb) -> List[Dict[str, Any]]:
    """The Company files the migration leaves where a version before 3.3.0 kept them.

    One entry for each namespace whose Goal or Task is not certain: its ``namespace``, the ``paths``
    of its files, and ``owners``, the ids that could own it. ``owners`` is empty when no record of
    this database has the id, and holds several ids when 3.2.0 kept their files in one namespace.
    ``move_company_files(db, owners={namespace: id})`` moves a namespace to the owner it is given.
    """
    if not _is_db_type(db, SQL_DB_TYPES):
        return []
    return _in_session(db, lambda sess: _files_left(sess, db))


async def acompany_files_left(db: Any) -> List[Dict[str, Any]]:
    """Async variant of ``company_files_left``. The database may be synchronous."""
    if not _is_db_type(db, SQL_DB_TYPES):
        return []
    return await _ain_session(db, lambda sess: _files_left(sess, db))


def _move_after_rename(sess: Any, db: Any, owners: Optional[Dict[str, str]]) -> bool:
    if _rename_pending(sess, type(db).__name__, _CompanyTables.of(db)):
        raise CompanyFilesMigrationError(
            "Company files were not moved: the Company tables are not renamed yet, and a folder is named after "
            "the Goal or Task in them. Run the migration, which renames the tables and then moves the files: "
            "`asyncio.run(MigrationManager(db).up())` (import it from `agno.db.migrations.manager`)."
        )
    return _move_company_files(sess, db, owners)


def move_company_files(db: BaseDb, owners: Optional[Dict[str, str]] = None) -> bool:
    """Move the Company files of a SQLite or PostgreSQL database into the Company file system.

    ``MigrationManager`` does this after it renames the Company tables, and this refuses to run
    before that. ``owners`` names, by namespace, the Goal or Task id that takes the files of a
    namespace ``company_files_left`` reports. True when a namespace moved.
    """
    if not _is_db_type(db, SQL_DB_TYPES):
        return False
    return _in_session(db, lambda sess: _move_after_rename(sess, db, owners))


async def amove_company_files(db: Any, owners: Optional[Dict[str, str]] = None) -> bool:
    """Async variant of ``move_company_files``. The database may be synchronous."""
    if not _is_db_type(db, SQL_DB_TYPES):
        return False
    return await _ain_session(db, lambda sess: _move_after_rename(sess, db, owners))


# Notes kept in another database

_NOTE_COLUMNS = ("path", "content", "size_bytes", "version", "created_at", "updated_at")
# Holds one row while a move makes sure its two databases are two: never a note.
_PROBE_NAMESPACE = "company/notes-move"
# What tells one PostgreSQL cluster from another, and what does when a role may not ask for it.
_CLUSTER_ID = "SELECT system_identifier FROM pg_control_system()"
_CLUSTER_START = "SELECT pg_postmaster_start_time()"


def _file_place(sess: Any, db: Any) -> tuple:
    """Where a database keeps its files, as the database itself answers.

    The same for every way of reaching one database: a path written two ways, a link, a host under
    two names. An in-memory database is the place of its own engine, so two of them are two places.
    """
    import os

    from agno.fs import FileSystem

    conn = sess.connection()
    backend: Any = FileSystem(db, namespace=COMPANY_NAMESPACE, user_scoped=False).backend
    table = (backend.db_schema, backend.table_name)
    if conn.dialect.name == "postgresql":
        try:
            with conn.begin_nested():
                cluster = conn.execute(text(_CLUSTER_ID)).scalar()
        except DBAPIError:
            # Every connection to one server reads the same start time, and two servers do not share one.
            cluster = conn.execute(text(_CLUSTER_START)).scalar()
        database = conn.execute(text("SELECT current_database()")).scalar()
        return ("postgresql", str(cluster), database, *table)
    file = next((row[2] for row in conn.execute(text("PRAGMA database_list")).fetchall() if row[1] == "main"), "")
    if not file:
        return ("sqlite", "memory", id(conn.engine), *table)
    try:
        stat = os.stat(file)
    except OSError:
        return ("sqlite", os.path.realpath(file), *table)
    return ("sqlite", stat.st_dev, stat.st_ino, *table)


def _notes_can_move(source_db: Any, company_db: Any) -> bool:
    return _is_db_type(source_db, SQL_DB_TYPES) and _is_db_type(company_db, SQL_DB_TYPES)


def _is_note(files: Any) -> Any:
    """Rows that are notes: in the namespace from before 3.3.0, or under notes/ in the Company namespace."""
    from sqlalchemy import and_, func, or_

    # substr compares case on SQLite and PostgreSQL alike; a prefix match ignores it on SQLite.
    in_folder = and_(files.c.namespace == COMPANY_NAMESPACE, func.substr(files.c.path, 1, len("notes/")) == "notes/")
    return or_(files.c.namespace == _NOTES, in_folder)


def _notes_wait(sess: Any, db: Any) -> bool:
    """Whether a database holds a shared note. One statement on the file table when it holds none."""
    conn = sess.connection()
    backend = _file_backend(db, conn)
    if backend is None:
        return False
    files = backend.table
    if conn.execute(select(files.c.path).where(_is_note(files)).limit(1)).first() is None:
        return False
    if not _has_user_partitions(backend):
        return False
    return (
        conn.execute(select(files.c.path).where(_is_note(files), files.c.user_id == _SHARED).limit(1)).first()
        is not None
    )


def _take_notes(sess: Any, db: Any) -> List[Dict[str, Any]]:
    """The shared notes of a database, after any still in the namespace from before 3.3.0 are put in notes/."""
    if not _notes_wait(sess, db):
        return []
    conn = sess.connection()
    files = _file_backend(db, conn).table
    _move(conn, files, {_NOTES: "notes"}, {})
    rows = conn.execute(
        select(*(files.c[name] for name in _NOTE_COLUMNS)).where(
            files.c.namespace == COMPANY_NAMESPACE, files.c.user_id == _SHARED, _is_note(files)
        )
    ).all()
    return [dict(zip(_NOTE_COLUMNS, row)) for row in rows]


def _notes_in_place(files: Any) -> tuple:
    return (files.c.namespace == COMPANY_NAMESPACE, files.c.user_id == _SHARED, _is_note(files))


def _write_notes(sess: Any, db: Any, notes: List[Dict[str, Any]]) -> None:
    """Store notes in the Company database.

    A different note already at a path stops the copy before a row is written. A note already there
    with the same content takes the higher of the two versions, with the timestamps that go with it.
    """
    conn = sess.connection()
    files = _file_backend(db, conn, create=True).table
    in_place = _notes_in_place(files)
    rows = conn.execute(select(files.c.path, files.c.content, files.c.version).where(*in_place)).all()
    before = {row[0]: (row[1], row[2]) for row in rows}
    blocked = sorted(n["path"] for n in notes if n["path"] in before and before[n["path"]][0] != n["content"])
    if blocked:
        raise CompanyFilesMigrationError(
            "Notes were not moved: a different note is already stored in the Company database at "
            f"{', '.join(blocked)}. Rename or delete one of the two, then run the move again."
        )
    missing = [note for note in notes if note["path"] not in before]
    if missing:
        conn.execute(files.insert(), [{"namespace": COMPANY_NAMESPACE, "user_id": _SHARED, **n} for n in missing])
    for note in notes:
        if note["path"] in before and before[note["path"]][1] < note["version"]:
            kept = {name: note[name] for name in ("version", "created_at", "updated_at")}
            conn.execute(update(files).where(*in_place, files.c.path == note["path"]).values(**kept))


def _notes_held(sess: Any, db: Any, notes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The notes a database is seen to hold with the same content, read after the write is committed."""
    conn = sess.connection()
    backend = _file_backend(db, conn)
    if backend is None:
        return []
    files = backend.table
    rows = conn.execute(select(files.c.path, files.c.content).where(*_notes_in_place(files))).all()
    held = {row[0]: row[1] for row in rows}
    return [note for note in notes if note["path"] in held and held[note["path"]] == note["content"]]


def _delete_notes(sess: Any, db: Any, notes: List[Dict[str, Any]]) -> int:
    """Remove from the AgentOS database the notes the Company database holds now."""
    from sqlalchemy import delete

    conn = sess.connection()
    files = _file_backend(db, conn).table
    removed = 0
    for note in notes:
        result = conn.execute(
            delete(files).where(
                files.c.namespace == COMPANY_NAMESPACE,
                files.c.user_id == _SHARED,
                files.c.path == note["path"],
                files.c.version == note["version"],
                files.c.content == note["content"],
            )
        )
        removed += result.rowcount or 0
    return removed


def _probe(sess: Any, db: Any, token: str, step: str) -> bool:
    """Write, look for, or remove the row that tells two file tables apart."""
    from sqlalchemy import delete

    conn = sess.connection()
    backend = _file_backend(db, conn, create=step == "write")
    if backend is None:
        return False
    files = backend.table
    mine = (files.c.namespace == _PROBE_NAMESPACE, files.c.user_id == _SHARED, files.c.path == token)
    if step == "write":
        row = {"namespace": _PROBE_NAMESPACE, "user_id": _SHARED, "path": token, "content": "", "size_bytes": 0}
        conn.execute(files.insert(), [{**row, "version": 1, "created_at": 0, "updated_at": None}])
        return True
    if step == "look":
        return conn.execute(select(files.c.path).where(*mine)).first() is not None
    conn.execute(delete(files).where(*mine))
    return True


def _place_of_notes(sess: Any, db: Any) -> Optional[tuple]:
    """Where a database keeps its files, when it holds a shared note."""
    return _file_place(sess, db) if _notes_wait(sess, db) else None


def company_notes_to_move(source_db: BaseDb, company_db: BaseDb) -> bool:
    """Whether the AgentOS database holds notes that ``move_company_notes`` moves to the Company database.

    False when the two keep their files in one table, however each is reached: the notes are where
    they belong.
    """
    if not _notes_can_move(source_db, company_db):
        return False
    source = _in_session(source_db, lambda sess: _place_of_notes(sess, source_db))
    return source is not None and source != _in_session(company_db, lambda sess: _file_place(sess, company_db))


async def acompany_notes_to_move(source_db: Any, company_db: Any) -> bool:
    """Async variant of ``company_notes_to_move``. Either database may be synchronous."""
    if not _notes_can_move(source_db, company_db):
        return False
    source = await _ain_session(source_db, lambda sess: _place_of_notes(sess, source_db))
    if source is None:
        return False
    return source != await _ain_session(company_db, lambda sess: _file_place(sess, company_db))


def move_company_notes(source_db: BaseDb, company_db: BaseDb) -> int:
    """Move notes/ from the AgentOS database to the Company database, for a deployment that keeps two.

    Before 3.3.0 notes were stored in the AgentOS database. From 3.3.0 they are a folder of the
    Company file system, in the Company database. Each shared note is copied with its content,
    version and timestamps, and removed from the AgentOS database after the Company database is
    seen to hold it. Returns the number of notes moved.

    Nothing is removed unless the two databases are two: a row written through one must not be
    seen through the other. Two handles on one database, however each names it, move nothing.

    Notes are moved from the namespace 3.2.0 kept them in and from notes/, so the call does not
    depend on ``MigrationManager`` having run on the AgentOS database. Calling it again moves
    nothing, and a call that stopped after the copy is finished by the next one. Use
    ``amove_company_notes`` when either database is asynchronous.
    """
    if not company_notes_to_move(source_db, company_db):
        return 0
    notes = _in_session(source_db, lambda sess: _take_notes(sess, source_db))
    if not notes:
        return 0
    try:
        _in_session(company_db, lambda sess: _write_notes(sess, company_db, notes))
    except IntegrityError:
        # Another move stored a note at the same moment. What the Company database holds now decides.
        _in_session(company_db, lambda sess: _write_notes(sess, company_db, notes))
    stored = _in_session(company_db, lambda sess: _notes_held(sess, company_db, notes))
    if not stored:
        return 0
    token = uuid4().hex
    _in_session(source_db, lambda sess: _probe(sess, source_db, token, "write"))
    try:
        if _in_session(company_db, lambda sess: _probe(sess, company_db, token, "look")):
            return 0
    finally:
        _in_session(source_db, lambda sess: _probe(sess, source_db, token, "remove"))
    return _in_session(source_db, lambda sess: _delete_notes(sess, source_db, stored))


async def amove_company_notes(source_db: Any, company_db: Any) -> int:
    """Async variant of ``move_company_notes``. Either database may be synchronous."""
    if not await acompany_notes_to_move(source_db, company_db):
        return 0
    notes = await _ain_session(source_db, lambda sess: _take_notes(sess, source_db))
    if not notes:
        return 0
    try:
        await _ain_session(company_db, lambda sess: _write_notes(sess, company_db, notes))
    except IntegrityError:
        await _ain_session(company_db, lambda sess: _write_notes(sess, company_db, notes))
    stored = await _ain_session(company_db, lambda sess: _notes_held(sess, company_db, notes))
    if not stored:
        return 0
    token = uuid4().hex
    await _ain_session(source_db, lambda sess: _probe(sess, source_db, token, "write"))
    try:
        if await _ain_session(company_db, lambda sess: _probe(sess, company_db, token, "look")):
            return 0
    finally:
        await _ain_session(source_db, lambda sess: _probe(sess, source_db, token, "remove"))
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
