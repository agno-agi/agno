"""Oracle Database adapter.

Full public surface parity with PostgresDb is built up across several
tickets; this file starts with the domains needed to keep an Agent's
conversation working end to end (sessions, runs, schema versioning and table
creation) plus the differential harness proving it. Every other abstract
method is present as an explicit stub -- the class must instantiate now, and
each stub names the ticket that replaces it, mirroring the pattern the MySQL
adapter already uses for its own coverage gaps.

Sections below are ordered to match ``agno.db.postgres.postgres`` so the two
files read side by side.
"""

import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from sqlalchemy import (
    Column,
    Engine,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    UniqueConstraint,
    create_engine,
    func,
    select,
    text,
)
from sqlalchemy.orm import Session as SQLASession
from sqlalchemy.orm import scoped_session, sessionmaker

from agno.db.base import BaseDb, SessionType
from agno.db.migrations.manager import MigrationManager
from agno.db.oracle._version import OracleCapabilities, detect_capabilities
from agno.db.oracle.engine import _engine_options
from agno.db.oracle.schemas import get_table_schema_definition
from agno.db.oracle.utils import (
    apply_sorting,
    calculate_date_metrics,
    fetch_all_sessions_data,
    from_db_user_id,
    get_dates_to_calculate_metrics_for,
    is_table_available,
    is_valid_table,
    merge_upsert,
    partial_unique_index_elements,
    to_db_user_id,
    truncate_identifier,
)
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.db.utils import (
    SessionRunObjectCache,
    build_single_run_row,
    deserialize_run,
    deserialize_session,
    deserialize_sessions,
    learning_search_patterns,
    metrics_starting_date_from_days,
    table_schema_mismatch_error,
    validate_pagination,
)
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.string import generate_id


class OracleDb(BaseDb):
    """Interface for interacting with an Oracle Database (19c and later).

    The following order is used to determine the database connection:
        1. Use db_engine if provided.
        2. Use db_url.
        3. Raise if neither is provided.
    """

    def __init__(
        self,
        db_url: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        db_schema: Optional[str] = None,
        session_table: Optional[str] = None,
        runs_table: Optional[str] = None,
        memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
        traces_table: Optional[str] = None,
        spans_table: Optional[str] = None,
        versions_table: Optional[str] = None,
        components_table: Optional[str] = None,
        component_configs_table: Optional[str] = None,
        component_links_table: Optional[str] = None,
        learnings_table: Optional[str] = None,
        schedules_table: Optional[str] = None,
        schedule_runs_table: Optional[str] = None,
        job_table: Optional[str] = None,
        approvals_table: Optional[str] = None,
        auth_tokens_table: Optional[str] = None,
        service_accounts_table: Optional[str] = None,
        mcp_oauth_clients_table: Optional[str] = None,
        mcp_oauth_transactions_table: Optional[str] = None,
        mcp_oauth_codes_table: Optional[str] = None,
        mcp_oauth_refresh_tokens_table: Optional[str] = None,
        mcp_oauth_keys_table: Optional[str] = None,
        id: Optional[str] = None,
        create_schema: bool = True,
        json_storage: Optional[str] = None,
    ):
        """
        Args:
            db_url: The database URL to connect to.
            db_engine: The SQLAlchemy database engine to use.
            db_schema: The Oracle schema (user) tables live under. On Oracle a
                schema IS a user: the default, None, means the connecting
                user's own schema, and tables are created unqualified. An
                explicit value is validated for existence at first use, since
                creating a user requires DBA privilege an application user
                should not hold.
            ... (table name overrides -- see BaseDb.__init__)
            id: ID of the database.
            create_schema: On every other SQL adapter this creates a schema.
                Here it cannot: creating an Oracle user needs a privilege
                application code should never carry. Kept for interface
                parity; True (the default) logs, once, that this is a no-op.
                Set False to suppress even that log line.
            json_storage: Override capability detection ("native" or "clob").
                For locked-down environments where the connecting user cannot
                read PRODUCT_COMPONENT_VERSION. Boolean and vector support are
                conservatively assumed absent when this is set -- construct
                OracleCapabilities directly for finer control.

        Raises:
            ValueError: If neither db_url nor db_engine is provided.
        """
        _engine: Optional[Engine] = db_engine
        if _engine is None and db_url is not None:
            _engine = create_engine(db_url, **_engine_options())
        if _engine is None:
            raise ValueError("One of db_url or db_engine must be provided")

        self.db_url: Optional[str] = db_url
        self.db_engine: Engine = _engine

        if id is None:
            base_seed = db_url or str(_engine.url)
            seed = f"{base_seed}#{db_schema or ''}"
            id = generate_id(seed)

        super().__init__(
            id=id,
            session_table=session_table,
            runs_table=runs_table,
            memory_table=memory_table,
            metrics_table=metrics_table,
            eval_table=eval_table,
            knowledge_table=knowledge_table,
            traces_table=traces_table,
            spans_table=spans_table,
            versions_table=versions_table,
            components_table=components_table,
            component_configs_table=component_configs_table,
            component_links_table=component_links_table,
            learnings_table=learnings_table,
            schedules_table=schedules_table,
            schedule_runs_table=schedule_runs_table,
            job_table=job_table,
            approvals_table=approvals_table,
            auth_tokens_table=auth_tokens_table,
            service_accounts_table=service_accounts_table,
            mcp_oauth_clients_table=mcp_oauth_clients_table,
            mcp_oauth_transactions_table=mcp_oauth_transactions_table,
            mcp_oauth_codes_table=mcp_oauth_codes_table,
            mcp_oauth_refresh_tokens_table=mcp_oauth_refresh_tokens_table,
            mcp_oauth_keys_table=mcp_oauth_keys_table,
        )

        # None, not "ai": a schema is a user on Oracle, and the default is
        # "whichever user this connection authenticated as".
        self.db_schema: Optional[str] = db_schema
        self.metadata: MetaData = MetaData(schema=self.db_schema)
        # Reinterpreted per ADR: Oracle has no privilege-safe way to create a
        # schema (user) from application code. True is the default purely for
        # interface parity with every other SQL adapter; it changes nothing
        # except whether the reinterpretation is logged.
        self.create_schema: bool = create_schema
        if create_schema:
            log_debug(
                "OracleDb: create_schema has no effect on Oracle -- a schema is a user, and creating one "
                "requires DBA privilege application code should not hold. Tables are created in the "
                "connecting user's own schema (or in db_schema, if given, which must already exist)."
            )
        if db_schema is not None:
            self._require_schema_exists(db_schema)

        if json_storage is not None:
            self.capabilities: OracleCapabilities = OracleCapabilities.override(json_storage=json_storage)
        else:
            self.capabilities = detect_capabilities(self.db_engine)

        self.Session: scoped_session = scoped_session(sessionmaker(bind=self.db_engine, expire_on_commit=False))

        self._run_object_cache = SessionRunObjectCache()
        self._metrics_refreshed_at: float = 0.0

    def _require_schema_exists(self, db_schema: str) -> None:
        """Validate an explicitly-given schema (user) exists.

        Raises with the DBA action required, rather than letting every
        subsequent query fail with an opaque ORA-00942 (table or view does
        not exist) that gives no hint the schema itself is the problem.
        """
        with self.db_engine.connect() as conn:
            exists = (
                conn.execute(
                    text("SELECT 1 FROM all_users WHERE username = UPPER(:schema)"), {"schema": db_schema}
                ).first()
                is not None
            )
        if not exists:
            raise ValueError(
                f"Oracle schema (user) '{db_schema}' does not exist. On Oracle a schema is a user; "
                f"OracleDb cannot create one (that requires DBA privilege). Ask a DBA to run: "
                f"CREATE USER {db_schema} IDENTIFIED BY <password>; GRANT CREATE SESSION, CREATE TABLE, "
                f"CREATE SEQUENCE TO {db_schema}; ALTER USER {db_schema} QUOTA UNLIMITED ON <tablespace>;"
            )

    # -- Serialization methods --
    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update({"db_url": self.db_url, "db_schema": self.db_schema, "type": "oracle"})
        return base

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OracleDb":
        return cls(
            db_url=data.get("db_url"),
            db_schema=data.get("db_schema"),
            session_table=data.get("session_table"),
            runs_table=data.get("runs_table"),
            memory_table=data.get("memory_table"),
            metrics_table=data.get("metrics_table"),
            eval_table=data.get("eval_table"),
            knowledge_table=data.get("knowledge_table"),
            traces_table=data.get("traces_table"),
            spans_table=data.get("spans_table"),
            versions_table=data.get("versions_table"),
            components_table=data.get("components_table"),
            component_configs_table=data.get("component_configs_table"),
            component_links_table=data.get("component_links_table"),
            learnings_table=data.get("learnings_table"),
            schedules_table=data.get("schedules_table"),
            schedule_runs_table=data.get("schedule_runs_table"),
            approvals_table=data.get("approvals_table"),
            service_accounts_table=data.get("service_accounts_table"),
            id=data.get("id"),
        )

    def close(self) -> None:
        """Close database connections and dispose of the connection pool."""
        if self.db_engine is not None:
            self.db_engine.dispose()

    # -- Table creation and resolution --
    def table_exists(self, table_name: str) -> bool:
        with self.Session() as sess:
            return is_table_available(session=sess, table_name=table_name, db_schema=self.db_schema)

    def _resolve_table_name(self, logical_name: str) -> str:
        table_map = {
            "traces": self.trace_table_name,
            "spans": self.span_table_name,
            "sessions": self.session_table_name,
            "runs": self.runs_table_name,
            "memories": self.memory_table_name,
            "metrics": self.metrics_table_name,
            "evals": self.eval_table_name,
            "knowledge": self.knowledge_table_name,
            "versions": self.versions_table_name,
            "components": self.components_table_name,
            "component_configs": self.component_configs_table_name,
            "component_links": self.component_links_table_name,
            "learnings": self.learnings_table_name,
            "schedules": self.schedules_table_name,
            "schedule_runs": self.schedule_runs_table_name,
            "jobs": self.job_table_name,
            "tool_results": self.tool_results_table_name,
            "approvals": self.approvals_table_name,
            "auth_tokens": self.auth_tokens_table_name,
            "service_accounts": self.service_accounts_table_name,
            "mcp_oauth_clients": self.mcp_oauth_clients_table_name,
            "mcp_oauth_transactions": self.mcp_oauth_transactions_table_name,
            "mcp_oauth_codes": self.mcp_oauth_codes_table_name,
            "mcp_oauth_refresh_tokens": self.mcp_oauth_refresh_tokens_table_name,
            "mcp_oauth_keys": self.mcp_oauth_keys_table_name,
        }
        return table_map.get(logical_name, logical_name)

    def _resolve_fk_reference(self, fk_ref: str) -> str:
        """Resolve "logical_table.column" to a schema-qualified reference.

        Unlike Postgres, the schema qualifier is omitted entirely when
        db_schema is None (the connecting user's own schema) -- Oracle tables
        are created unqualified in that case, and qualifying the FK target
        would reference a schema the parent table was never created in.
        """
        parts = fk_ref.rsplit(".", 1)
        if len(parts) == 2:
            table, column = parts
            resolved_table = self._resolve_table_name(table)
            if self.db_schema:
                return f"{self.db_schema}.{resolved_table}.{column}"
            return f"{resolved_table}.{column}"
        return fk_ref

    def _create_table(self, table_name: str, table_type: str) -> Table:
        """Create a table for ``table_type``, translating the five special
        schema keys the way Oracle needs (see module and utils.py docstrings
        for why each translation exists):

        - ``_unique_constraints`` / ``__primary_key__`` / ``__foreign_keys__``
          / ``__composite_indexes__``: structurally identical to Postgres.
        - ``_partial_unique_indexes``: becomes a unique function-based index
          (``partial_unique_index_elements``), since Oracle has no partial index.

        A column typed ``OracleClobJSON`` gets no structural database-level
        check: see that class's own docstring for why an ``IS JSON`` check,
        inline or out-of-line, cannot be used here.
        """
        try:
            table_schema = get_table_schema_definition(
                table_type,
                self.capabilities,
                traces_table_name=self.trace_table_name,
                db_schema=self.db_schema,
                schedules_table_name=self.schedules_table_name,
                session_table_name=self.session_table_name,
                components_table_name=self.components_table_name,
                component_configs_table_name=self.component_configs_table_name,
            ).copy()

            declares_fk = bool(table_schema.get("__foreign_keys__")) or any(
                isinstance(cfg, dict) and "foreign_key" in cfg for cfg in table_schema.values()
            )
            if declares_fk:
                registered = {t.name for t in self.metadata.tables.values()}
                for ref_type, ref_name in self._fk_dependencies(table_type):
                    if ref_name not in registered:
                        self._resolve_table(table_name=ref_name, table_type=ref_type, create_table_if_not_found=True)

            schema_unique_constraints = table_schema.pop("_unique_constraints", [])
            schema_primary_key = table_schema.pop("__primary_key__", None)
            schema_foreign_keys = table_schema.pop("__foreign_keys__", [])
            schema_composite_indexes = table_schema.pop("__composite_indexes__", [])
            schema_partial_unique_indexes = table_schema.pop("_partial_unique_indexes", [])

            columns: List[Column] = []
            single_indexes: List[str] = []

            for col_name, col_config in table_schema.items():
                column_args: List[Any] = [col_name, col_config["type"]()]
                column_kwargs: Dict[str, Any] = {}

                if col_config.get("primary_key", False) and schema_primary_key is None:
                    column_kwargs["primary_key"] = True
                if "nullable" in col_config:
                    column_kwargs["nullable"] = col_config["nullable"]
                if "default" in col_config:
                    column_kwargs["default"] = col_config["default"]
                if col_config.get("unique", False):
                    column_kwargs["unique"] = True
                if col_config.get("index", False):
                    single_indexes.append(col_name)
                if "foreign_key" in col_config:
                    fk_ref = self._resolve_fk_reference(col_config["foreign_key"])
                    fk_kwargs: Dict[str, Any] = {}
                    if "ondelete" in col_config:
                        fk_kwargs["ondelete"] = col_config["ondelete"]
                    column_args.append(ForeignKey(fk_ref, **fk_kwargs))

                columns.append(Column(*column_args, **column_kwargs))

            table = Table(table_name, self.metadata, *columns, schema=self.db_schema)

            if schema_primary_key is not None:
                missing = [c for c in schema_primary_key if c not in table.c]
                if missing:
                    raise ValueError(f"Composite PK references missing columns in {table_name}: {missing}")
                table.append_constraint(
                    PrimaryKeyConstraint(*schema_primary_key, name=truncate_identifier(f"{table_name}_pkey"))
                )

            for fk_config in schema_foreign_keys:
                fk_columns = fk_config["columns"]
                ref_columns = fk_config["ref_columns"]
                if len(fk_columns) != len(ref_columns):
                    raise ValueError(f"Composite FK in {table_name} has mismatched columns/ref_columns")
                missing = [c for c in fk_columns if c not in table.c]
                if missing:
                    raise ValueError(f"Composite FK references missing columns in {table_name}: {missing}")

                resolved_ref_table = self._resolve_table_name(fk_config["ref_table"])
                ref_column_strings = [f"{resolved_ref_table}.{col}" for col in ref_columns]
                table.append_constraint(
                    ForeignKeyConstraint(
                        fk_columns,
                        ref_column_strings,
                        name=truncate_identifier(f"{table_name}_{'_'.join(fk_columns)}_fkey"),
                    )
                )

            for constraint in schema_unique_constraints:
                constraint_columns = constraint["columns"]
                missing = [c for c in constraint_columns if c not in table.c]
                if missing:
                    raise ValueError(f"Unique constraint references missing columns in {table_name}: {missing}")
                table.append_constraint(
                    UniqueConstraint(
                        *constraint_columns, name=truncate_identifier(f"{table_name}_{constraint['name']}")
                    )
                )

            for idx_col in single_indexes:
                if idx_col not in table.c:
                    raise ValueError(f"Index references missing column in {table_name}: {idx_col}")
                # A unique= column already carries an implicit index backing
                # that constraint. On Postgres a second explicit index over
                # the identical column is merely redundant; on Oracle it is
                # ORA-01408 ("such column list already indexed"). Skip it.
                if table_schema[idx_col].get("unique"):
                    continue
                Index(truncate_identifier(f"idx_{table_name}_{idx_col}"), table.c[idx_col])

            for idx_config in schema_composite_indexes:
                idx_cols = [table.c[c] for c in idx_config["columns"]]
                Index(truncate_identifier(f"idx_{table_name}_{'_'.join(idx_config['columns'])}"), *idx_cols)

            for idx_config in schema_partial_unique_indexes:
                idx_columns = idx_config["columns"]
                missing = [c for c in idx_columns if c not in table.c]
                if missing:
                    raise ValueError(f"Partial unique index references missing columns in {table_name}: {missing}")
                elements = partial_unique_index_elements(table, idx_columns, idx_config["where"])
                Index(truncate_identifier(f"{table_name}_{idx_config['name']}"), *elements, unique=True)

            table_created = False
            if not self.table_exists(table_name):
                table.create(self.db_engine, checkfirst=True)
                log_debug(f"Created table {table_name}")
                table_created = True
            else:
                log_debug(f"Table {table_name} already exists", log_level=2)

            for idx in table.indexes:
                try:
                    with self.Session() as sess:
                        params: Dict[str, Any]
                        if self.db_schema is None:
                            exists_query = text("SELECT 1 FROM user_indexes WHERE index_name = UPPER(:index_name)")
                            params = {"index_name": idx.name}
                        else:
                            exists_query = text(
                                "SELECT 1 FROM all_indexes WHERE owner = UPPER(:db_schema) "
                                "AND index_name = UPPER(:index_name)"
                            )
                            params = {"db_schema": self.db_schema, "index_name": idx.name}
                        if sess.execute(exists_query, params).scalar() is not None:
                            continue
                    idx.create(self.db_engine)
                    log_debug(f"Created index: {idx.name} for table {table_name}")
                except Exception as e:
                    log_error(f"Error creating index {idx.name}: {str(e)}")

            if table_name != self.versions_table_name and table_created:
                latest_schema_version = MigrationManager(self).latest_schema_version
                self.upsert_schema_version(table_name=table_name, version=latest_schema_version.public)

            return table

        except Exception as e:
            # ORA-00955 (name already used) / ORA-00001 (unique violation): a
            # concurrent CREATE TABLE lost the catalog's own uniqueness race.
            # An existing winner is not a database outage.
            orig = getattr(e, "orig", e)
            code = getattr(orig, "code", None) or next(
                (getattr(a, "code", None) for a in getattr(orig, "args", ())), None
            )
            if code in (955, 1) and self.table_exists(table_name):
                log_debug(f"Concurrent table creation: {table_name}", log_level=2)
            else:
                log_error(f"Could not create table {table_name}: {str(e)}")
                raise
            return self._reflect_table(table_name)

    def _reflect_table(self, table_name: str) -> Table:
        return Table(table_name, self.metadata, schema=self.db_schema, autoload_with=self.db_engine)

    def _resolve_table(
        self, table_name: str, table_type: str, create_table_if_not_found: Optional[bool] = False
    ) -> Optional[Table]:
        with self.Session() as sess:
            table_is_available = is_table_available(session=sess, table_name=table_name, db_schema=self.db_schema)

        if not table_is_available:
            if not create_table_if_not_found:
                return None
            table = self._create_table(table_name=table_name, table_type=table_type)
            self._store_resolved_table(table_type, table_name, table)
            return table

        expected_columns = get_table_schema_definition(
            table_type,
            self.capabilities,
            traces_table_name=self.trace_table_name,
            db_schema=self.db_schema,
            schedules_table_name=self.schedules_table_name,
            session_table_name=self.session_table_name,
            components_table_name=self.components_table_name,
            component_configs_table_name=self.component_configs_table_name,
        ).keys()
        if not is_valid_table(
            db_engine=self.db_engine, table_name=table_name, expected_columns=expected_columns, db_schema=self.db_schema
        ):
            raise table_schema_mismatch_error(
                f"{self.db_schema}.{table_name}" if self.db_schema else table_name, table_type=table_type
            )

        try:
            table = self._reflect_table(table_name)
            self._store_resolved_table(table_type, table_name, table)
            return table
        except Exception as e:
            log_error(f"Error loading existing table {table_name}: {str(e)}")
            raise

    def _get_table(self, table_type: str, create_table_if_not_found: Optional[bool] = False) -> Optional[Table]:
        table_name = self._resolve_table_name(table_type)
        return self._get_or_create_table(
            table_name=table_name, table_type=table_type, create_table_if_not_found=create_table_if_not_found
        )

    # -- Schema version --
    def get_latest_schema_version(self, table_name: str) -> str:
        """Latest stamped version for ``table_name``, or the base version.

        Never returns None: the migration manager skips migration entirely
        (with only a warning) on a None return, leaving the table behind in
        silence -- exactly the failure mode this whole ticket exists to close.
        """
        table = self._get_table(table_type="versions", create_table_if_not_found=True)
        if table is None:
            return self.default_schema_version
        with self.Session() as sess:
            stmt = (
                select(table.c.version)
                .where(table.c.table_name == table_name)
                .order_by(table.c.version.desc())
                .limit(1)
            )
            row = sess.execute(stmt).first()
        return row[0] if row and row[0] else self.default_schema_version

    def upsert_schema_version(self, table_name: str, version: str) -> None:
        versions_table = self._get_table(table_type="versions", create_table_if_not_found=True)
        if versions_table is None:
            return
        current_datetime = datetime.now().isoformat()
        with self.Session() as sess, sess.begin():
            merge_upsert(
                sess,
                versions_table,
                key_columns=["table_name"],
                values={
                    "table_name": table_name,
                    "version": version,
                    "created_at": current_datetime,
                    "updated_at": current_datetime,
                },
            )

    def _create_all_tables(self) -> None:
        tables_to_create = [
            (self.session_table_name, "sessions"),
            (self.runs_table_name, "runs"),
        ]
        for table_name, table_type in tables_to_create:
            if not self.table_exists(table_name):
                self._invalidate_table_cache(table_name)
            self._get_or_create_table(table_name=table_name, table_type=table_type, create_table_if_not_found=True)

    # -- Runs --
    def get_run(
        self, run_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[RunOutput, TeamRunOutput, WorkflowRunOutput, Dict[str, Any]]]:
        try:
            table = self._get_table(table_type="runs")
            if table is None:
                return None
            with self.Session() as sess:
                result = sess.execute(select(table).where(table.c.run_id == run_id)).fetchone()
                if result is None:
                    return None
                run_row = dict(result._mapping)
            run_row["user_id"] = from_db_user_id(run_row.get("user_id"))
            if not deserialize:
                return run_row
            return deserialize_run(run_row.get("run_type"), run_row["run_data"])
        except Exception as e:
            log_error(f"Exception reading from runs table: {str(e)}")
            raise

    def upsert_run(
        self,
        run: Union[RunOutput, TeamRunOutput, WorkflowRunOutput, Dict[str, Any]],
        session_id: str,
        user_id: Optional[str] = None,
        run_index: Optional[int] = None,
    ) -> None:
        try:
            runs_table = self._get_table(table_type="runs", create_table_if_not_found=True)
            if runs_table is None:
                return

            row = build_single_run_row(run=run, session_id=session_id, user_id=user_id, run_index=run_index)
            row["user_id"] = to_db_user_id(row.get("user_id"))

            with self.Session() as sess, sess.begin():
                if row.get("run_index") is None:
                    # Serialize same-session backfills so two concurrent
                    # max-reads cannot both land the same index. Oracle has no
                    # advisory-lock primitive keyed on an arbitrary string the
                    # way Postgres does; a row lock on the session's own row
                    # gives the same same-session serialization instead.
                    sessions_table = self._get_table(table_type="sessions")
                    if sessions_table is not None:
                        sess.execute(
                            select(sessions_table.c.session_id)
                            .where(sessions_table.c.session_id == session_id)
                            .with_for_update()
                        ).first()
                    current_max = sess.execute(
                        select(func.max(runs_table.c.run_index)).where(runs_table.c.session_id == session_id)
                    ).scalar()
                    row["run_index"] = (current_max + 1) if current_max is not None else 0

                merge_upsert(
                    sess,
                    runs_table,
                    key_columns=["run_id"],
                    values=row,
                )
        except Exception as e:
            log_error(f"Exception upserting run to runs table: {str(e)}")
            raise

    def get_runs(
        self,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        status: Optional[RunStatus] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[Union[RunOutput, TeamRunOutput, WorkflowRunOutput]], Tuple[List[Dict[str, Any]], int]]:
        validate_pagination(limit, page)
        try:
            table = self._get_table(table_type="runs")
            if table is None:
                return [] if deserialize else ([], 0)

            with self.Session() as sess:
                stmt = select(table)
                if session_id is not None:
                    stmt = stmt.where(table.c.session_id == session_id)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == to_db_user_id(user_id))
                if agent_id is not None:
                    stmt = stmt.where(table.c.agent_id == agent_id)
                if team_id is not None:
                    stmt = stmt.where(table.c.team_id == team_id)
                if workflow_id is not None:
                    stmt = stmt.where(table.c.workflow_id == workflow_id)
                if status is not None:
                    status_value = status.value if isinstance(status, RunStatus) else status
                    stmt = stmt.where(table.c.status == status_value)

                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = sess.execute(count_stmt).scalar() or 0

                if sort_by is not None:
                    stmt = apply_sorting(stmt, table, sort_by, sort_order)
                else:
                    stmt = stmt.order_by(table.c.run_index.asc(), table.c.created_at.asc())

                if limit is not None:
                    offset = (page - 1) * limit if page and page > 1 else 0
                    stmt = stmt.offset(offset).limit(limit)

                records = sess.execute(stmt).fetchall()
                run_rows = [dict(record._mapping) for record in records]

            for r in run_rows:
                r["user_id"] = from_db_user_id(r.get("user_id"))

            if not deserialize:
                return run_rows, total_count
            return [deserialize_run(row.get("run_type"), row["run_data"]) for row in run_rows]
        except Exception as e:
            log_error(f"Exception reading from runs table: {str(e)}")
            raise

    def delete_run(self, run_id: str) -> bool:
        try:
            table = self._get_table(table_type="runs")
            if table is None:
                return False
            with self.Session() as sess, sess.begin():
                result = sess.execute(table.delete().where(table.c.run_id == run_id))
                return result.rowcount > 0
        except Exception as e:
            log_error(f"Error deleting run: {str(e)}")
            raise

    def delete_runs(self, run_ids: List[str]) -> None:
        try:
            table = self._get_table(table_type="runs")
            if table is None:
                return
            with self.Session() as sess, sess.begin():
                result = sess.execute(table.delete().where(table.c.run_id.in_(run_ids)))
            log_debug(f"Successfully deleted {result.rowcount} runs")
        except Exception as e:
            log_error(f"Error deleting runs: {str(e)}")
            raise

    # -- Sessions --
    def _cascade_tool_results(self, session_ids: List[str]) -> None:
        """Best-effort cleanup of offloaded tool results on session delete.

        Real tool-result offloading is a later ticket; until then this table
        is always empty, so this is a safe, cheap no-op. Kept here (rather
        than added later) so delete_session's behavior does not silently
        change shape once offloading is turned on.
        """
        if not session_ids:
            return
        try:
            table = self._get_table(table_type="tool_results")
            if table is None:
                return
            with self.Session() as sess, sess.begin():
                sess.execute(table.delete().where(table.c.session_id.in_(session_ids)))
        except Exception:
            log_debug("tool-result cascade failed; the primary session delete still succeeded", exc_info=True)

    def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        try:
            table = self._get_table(table_type="sessions")
            if table is None:
                return False
            runs_table = self._get_table(table_type="runs")

            with self.Session() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.session_id == session_id)
                if user_id is not None:
                    delete_stmt = delete_stmt.where(table.c.user_id == to_db_user_id(user_id))
                result = sess.execute(delete_stmt)
                if result.rowcount == 0:
                    return False
                if runs_table is not None:
                    sess.execute(runs_table.delete().where(runs_table.c.session_id == session_id))

            self._cascade_tool_results([session_id])
            self._run_object_cache.drop_session(session_id)
            return True
        except Exception as e:
            log_error(f"Error deleting session: {str(e)}")
            raise

    def delete_sessions(self, session_ids: List[str], user_id: Optional[str] = None) -> None:
        try:
            table = self._get_table(table_type="sessions")
            if table is None:
                return
            runs_table = self._get_table(table_type="runs")

            with self.Session() as sess, sess.begin():
                select_stmt = select(table.c.session_id).where(table.c.session_id.in_(session_ids))
                if user_id is not None:
                    select_stmt = select_stmt.where(table.c.user_id == to_db_user_id(user_id))
                deletable_ids = [row[0] for row in sess.execute(select_stmt)]
                cascade_ids = session_ids if user_id is None else deletable_ids

                result = sess.execute(table.delete().where(table.c.session_id.in_(deletable_ids)))

                if runs_table is not None:
                    runs_delete_stmt = runs_table.delete().where(runs_table.c.session_id.in_(session_ids))
                    if user_id is not None:
                        runs_delete_stmt = runs_delete_stmt.where(runs_table.c.user_id == to_db_user_id(user_id))
                    sess.execute(runs_delete_stmt)

            log_debug(f"Successfully deleted {result.rowcount} sessions")
            self._cascade_tool_results(cascade_ids)
            for deleted_id in cascade_ids:
                self._run_object_cache.drop_session(deleted_id)
        except Exception as e:
            log_error(f"Error deleting sessions: {str(e)}")
            raise

    def get_session(
        self,
        session_id: str,
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
        runs_limit: Optional[int] = None,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        try:
            table = self._get_table(table_type="sessions")
            if table is None:
                return None
            runs_table = self._get_table(table_type="runs")

            with self.Session() as sess:
                stmt = select(table).where(table.c.session_id == session_id)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == to_db_user_id(user_id))
                result = sess.execute(stmt).fetchone()
                if result is None:
                    return None

                session = dict(result._mapping)
                session["user_id"] = from_db_user_id(session.get("user_id"))
                run_rows: Optional[List[Tuple[str, str]]] = None

                if runs_table is None:
                    session["runs"] = []
                elif runs_limit is not None:
                    session["runs"] = self._get_session_runs_data(
                        sess=sess, runs_table=runs_table, session_id=session_id, limit=runs_limit
                    )
                elif (
                    deserialize
                    and session.get("session_type") == SessionType.AGENT.value
                    and (session_type is None or session_type == SessionType.AGENT)
                ):
                    run_rows = self._get_session_run_rows(sess=sess, runs_table=runs_table, session_id=session_id)
                    session["runs"] = None
                else:
                    session["runs"] = self._get_session_runs_data(
                        sess=sess, runs_table=runs_table, session_id=session_id
                    )

            if not deserialize:
                return session

            if run_rows is not None:
                session_obj = deserialize_session(session_type, session)
                session_obj.runs = self._run_object_cache.runs_from_rows(session_id, run_rows)  # type: ignore[union-attr]
                return session_obj
            return deserialize_session(session_type, session)
        except Exception as e:
            log_error(f"Exception reading from session table: {str(e)}")
            raise

    def _get_session_run_rows(self, sess: SQLASession, runs_table: Table, session_id: str) -> List[Tuple[str, str]]:
        """(run_id, raw run_data text) for the whole session, insertion order.

        Feeds the run-object cache, which reparses a run only when its text
        changed since the last read.

        Unlike the Postgres adapter, this does not push the text conversion
        down to SQL via CAST: Oracle's CAST does not accept a native JSON
        column as a source (ORA-22849 -- JSON_SERIALIZE is needed instead,
        and that would only cover the native-JSON variant, not the CLOB one).
        Both OracleNativeJSON and OracleClobJSON already decode to a Python
        dict on read, so the row is fetched decoded and re-encoded here in
        Python instead -- functionally identical, and dialect-variant-agnostic.
        """
        import json as _json

        stmt = (
            select(runs_table.c.run_id, runs_table.c.run_data)
            .where(runs_table.c.session_id == session_id)
            .order_by(runs_table.c.run_index.asc(), runs_table.c.created_at.asc(), runs_table.c.run_id.asc())
        )
        rows = sess.execute(stmt).fetchall()
        return [(run_id, run_data if isinstance(run_data, str) else _json.dumps(run_data)) for run_id, run_data in rows]

    def _get_session_runs_data(
        self, sess: SQLASession, runs_table: Table, session_id: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        if limit is not None:
            stmt = (
                select(runs_table.c.run_data)
                .where(runs_table.c.session_id == session_id)
                .order_by(runs_table.c.run_index.desc(), runs_table.c.created_at.desc(), runs_table.c.run_id.desc())
                .limit(limit)
            )
            rows = [row[0] for row in sess.execute(stmt).fetchall()]
            rows.reverse()
            return rows
        stmt = (
            select(runs_table.c.run_data)
            .where(runs_table.c.session_id == session_id)
            .order_by(runs_table.c.run_index.asc(), runs_table.c.created_at.asc(), runs_table.c.run_id.asc())
        )
        return [row[0] for row in sess.execute(stmt).fetchall()]

    def _get_sessions_runs_data(
        self, sess: SQLASession, runs_table: Table, session_ids: List[str]
    ) -> Dict[str, List[Dict[str, Any]]]:
        if not session_ids:
            return {}
        stmt = (
            select(runs_table.c.session_id, runs_table.c.run_data)
            .where(runs_table.c.session_id.in_(session_ids))
            .order_by(runs_table.c.run_index.asc(), runs_table.c.created_at.asc())
        )
        runs_by_session: Dict[str, List[Dict[str, Any]]] = {}
        for session_id, run_data in sess.execute(stmt).fetchall():
            runs_by_session.setdefault(session_id, []).append(run_data)
        return runs_by_session

    def get_sessions(
        self,
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        component_id: Optional[str] = None,
        session_name: Optional[str] = None,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        deserialize: Optional[bool] = True,
        include_runs: bool = True,
    ) -> Union[List[Session], Tuple[List[Dict[str, Any]], int]]:
        validate_pagination(limit, page)
        try:
            table = self._get_table(table_type="sessions")
            if table is None:
                return [] if deserialize else ([], 0)
            runs_table = self._get_table(table_type="runs")

            with self.Session() as sess, sess.begin():
                stmt = select(table)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == to_db_user_id(user_id))
                if component_id is not None:
                    if session_type == SessionType.AGENT:
                        stmt = stmt.where(table.c.agent_id == component_id)
                    elif session_type == SessionType.TEAM:
                        stmt = stmt.where(table.c.team_id == component_id)
                    elif session_type == SessionType.WORKFLOW:
                        stmt = stmt.where(table.c.workflow_id == component_id)
                    elif session_type is None:
                        stmt = stmt.where(
                            (table.c.agent_id == component_id)
                            | (table.c.team_id == component_id)
                            | (table.c.workflow_id == component_id)
                        )
                if start_timestamp is not None:
                    stmt = stmt.where(table.c.created_at >= start_timestamp)
                if end_timestamp is not None:
                    stmt = stmt.where(table.c.created_at <= end_timestamp)
                if session_name is not None:
                    # session_data's session_name is inside a JSON column;
                    # matched in Python below rather than pushed to SQL, so
                    # this works identically across both JSON storage
                    # variants (native JSON, or CLOB) without dialect-specific
                    # JSON path syntax.
                    pass
                if session_type is not None:
                    session_type_value = session_type.value if isinstance(session_type, SessionType) else session_type
                    stmt = stmt.where(table.c.session_type == session_type_value)

                if sort_by is not None:
                    stmt = apply_sorting(stmt, table, sort_by, sort_order)
                else:
                    stmt = apply_sorting(stmt, table, "created_at", "desc")

                records = sess.execute(stmt).fetchall()
                sessions = [dict(record._mapping) for record in records]
                for s in sessions:
                    s["user_id"] = from_db_user_id(s.get("user_id"))

                if session_name is not None:
                    needle = session_name.lower()
                    sessions = [
                        s
                        for s in sessions
                        if needle in str((s.get("session_data") or {}).get("session_name") or "").lower()
                    ]

                total_count = len(sessions)
                if limit is not None:
                    offset = (page - 1) * limit if page and page > 1 else 0
                    sessions = sessions[offset : offset + limit]

                if include_runs and runs_table is not None:
                    runs_by_session = self._get_sessions_runs_data(
                        sess=sess, runs_table=runs_table, session_ids=[s["session_id"] for s in sessions]
                    )
                    for s in sessions:
                        s["runs"] = runs_by_session.get(s["session_id"], [])
                else:
                    for s in sessions:
                        s["runs"] = None

                if not deserialize:
                    return sessions, total_count

            return deserialize_sessions(session_type, sessions)
        except Exception as e:
            log_error(f"Exception reading from session table: {str(e)}")
            raise

    def rename_session(
        self,
        session_id: str,
        session_type: Optional[SessionType],
        session_name: str,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """Rename a session by reading, mutating in Python, and writing back.

        Oracle has no single cross-variant JSON-patch expression covering
        both the native JSON type (21c+) and the CLOB fallback (below 21c);
        SQLite takes the same read-modify-write approach for the equivalent
        reason. The round trip happens inside one transaction so a concurrent
        writer's changes are not silently lost -- see the row lock below.
        """
        try:
            table = self._get_table(table_type="sessions")
            if table is None:
                return None

            with self.Session() as sess, sess.begin():
                stmt = select(table).where(table.c.session_id == session_id).with_for_update()
                if session_type is not None:
                    stmt = stmt.where(table.c.session_type == session_type.value)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == to_db_user_id(user_id))
                row = sess.execute(stmt).fetchone()
                if row is None:
                    return None

                session_data = dict(row._mapping.get("session_data") or {})
                session_data["session_name"] = session_name

                update_stmt = (
                    table.update()
                    .where(table.c.session_id == session_id)
                    .values(session_data=session_data, updated_at=int(time.time()))
                )
                sess.execute(update_stmt)

                refreshed = sess.execute(select(table).where(table.c.session_id == session_id)).fetchone()
                session = dict(refreshed._mapping)
                session["user_id"] = from_db_user_id(session.get("user_id"))

            runs_table = self._get_table(table_type="runs")
            if runs_table is not None:
                with self.Session() as sess:
                    session["runs"] = self._get_session_runs_data(
                        sess=sess, runs_table=runs_table, session_id=session_id
                    )
            else:
                session["runs"] = []

            log_debug(f"Renamed session with id '{session_id}' to '{session_name}'")
            if not deserialize:
                return session
            return deserialize_session(session_type, session)
        except Exception as e:
            log_error(f"Exception renaming session: {str(e)}")
            raise

    def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """Insert or update the session row.

        Runs are persisted independently via upsert_run() -- this method does
        not touch the runs table.
        """
        try:
            table = self._get_table(table_type="sessions", create_table_if_not_found=True)
            if table is None:
                return None

            session_dict = session.to_dict(include_runs=False)

            if isinstance(session, AgentSession):
                type_values: Dict[str, Any] = dict(
                    session_type=SessionType.AGENT.value,
                    agent_id=session_dict.get("agent_id"),
                    agent_data=session_dict.get("agent_data"),
                )
            elif isinstance(session, TeamSession):
                type_values = dict(
                    session_type=SessionType.TEAM.value,
                    team_id=session_dict.get("team_id"),
                    team_data=session_dict.get("team_data"),
                )
            elif isinstance(session, WorkflowSession):
                type_values = dict(
                    session_type=SessionType.WORKFLOW.value,
                    workflow_id=session_dict.get("workflow_id"),
                    workflow_data=session_dict.get("workflow_data"),
                )
            else:
                raise ValueError(f"Invalid session type: {session.session_type}")

            now = int(time.time())
            values = {
                "session_id": session_dict.get("session_id"),
                "user_id": to_db_user_id(session_dict.get("user_id")),
                "session_data": session_dict.get("session_data"),
                "summary": session_dict.get("summary"),
                "metadata": session_dict.get("metadata"),
                "created_at": session_dict.get("created_at") or now,
                "updated_at": now,
                **type_values,
            }

            with self.Session() as sess, sess.begin():
                # Owner-scoped match, mirroring Postgres's ON CONFLICT ...
                # WHERE clause: a session_id collision only updates the
                # existing row when it is unowned or already owned by this
                # same user, so one user's upsert cannot silently overwrite
                # another user's row of the same id.
                existing = sess.execute(
                    select(table.c.session_id, table.c.user_id).where(table.c.session_id == values["session_id"])
                ).first()
                if existing is not None and existing[1] is not None and existing[1] != values["user_id"]:
                    log_warning(
                        f"upsert_session: session_id '{values['session_id']}' is owned by a different user; "
                        "not overwriting."
                    )
                    return None

                merge_upsert(sess, table, key_columns=["session_id"], values=values)
                row = sess.execute(select(table).where(table.c.session_id == values["session_id"])).fetchone()
                if row is None:
                    return None
                session_dict = dict(row._mapping)
                session_dict["user_id"] = from_db_user_id(session_dict.get("user_id"))

            if not deserialize:
                session_dict["runs"] = [run if isinstance(run, dict) else run.to_dict() for run in session.runs or []]
                return session_dict

            session_dict.pop("runs", None)
            upserted_session = deserialize_session(None, session_dict)
            upserted_session.runs = session.runs  # type: ignore[union-attr]
            return upserted_session
        except Exception as e:
            log_error(f"Exception upserting into sessions table: {str(e)}")
            raise

    def upsert_sessions(
        self,
        sessions: List[Session],
        deserialize: Optional[bool] = True,
        preserve_updated_at: bool = False,
    ) -> List[Union[Session, Dict[str, Any]]]:
        """Bulk upsert, implemented as a loop over upsert_session.

        Deliberately simpler than Postgres's per-type batched MERGE: correct
        and easy to verify, at the cost of one round trip per session rather
        than one per type. Revisit if this shows up as a real bottleneck.
        """
        if not sessions:
            return []
        results: List[Union[Session, Dict[str, Any]]] = []
        for session in sessions:
            if preserve_updated_at:
                # upsert_session always stamps "now"; simulate preservation by
                # writing the caller's updated_at back afterward when given.
                result = self.upsert_session(session, deserialize=deserialize)
                if result is not None and getattr(session, "updated_at", None) is not None:
                    table = self._get_table(table_type="sessions")
                    if table is not None:
                        with self.Session() as sess, sess.begin():
                            sess.execute(
                                table.update()
                                .where(table.c.session_id == session.session_id)
                                .values(updated_at=session.updated_at)
                            )
                        if isinstance(result, dict):
                            result["updated_at"] = session.updated_at
                        else:
                            result.updated_at = session.updated_at  # type: ignore[union-attr]
                results.append(result) if result is not None else None
            else:
                result = self.upsert_session(session, deserialize=deserialize)
                if result is not None:
                    results.append(result)
        return results

    # -- Not yet implemented: owned by later tickets --
    #
    # Every method below is a required override of an @abstractmethod on
    # BaseDb. Each raises NotImplementedError explicitly, naming the ticket
    # that replaces it with a real implementation -- the same pattern the
    # MySQL adapter already uses for its own learnings stubs
    # (mysql.py, "Learning methods (stubs)"), rather than a silent pass.

    # -- Memory --
    def clear_memories(self) -> None:
        try:
            table = self._get_table(table_type="memories")
            if table is None:
                return
            with self.Session() as sess, sess.begin():
                sess.execute(table.delete())
        except Exception as e:
            log_error(f"Exception deleting all memories: {str(e)}")
            raise

    def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None) -> None:
        try:
            table = self._get_table(table_type="memories")
            if table is None:
                return
            with self.Session() as sess, sess.begin():
                stmt = table.delete().where(table.c.memory_id == memory_id)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == to_db_user_id(user_id))
                sess.execute(stmt)
        except Exception as e:
            log_error(f"Error deleting user memory: {str(e)}")
            raise

    def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        try:
            table = self._get_table(table_type="memories")
            if table is None:
                return
            with self.Session() as sess, sess.begin():
                stmt = table.delete().where(table.c.memory_id.in_(memory_ids))
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == to_db_user_id(user_id))
                sess.execute(stmt)
        except Exception as e:
            log_error(f"Error deleting user memories: {str(e)}")
            raise

    def get_all_memory_topics(self, user_id: Optional[str] = None) -> List[str]:
        """Distinct topics across memories, filtered by owner.

        Postgres pushes this down with jsonb_array_elements_text, a
        set-returning function with no cross-variant Oracle equivalent
        (native JSON needs JSON_TABLE, the CLOB variant has no native JSON
        function at all). ``topics`` already decodes to a Python list on
        read, so this flattens and dedupes in Python instead -- one query,
        no dialect-specific JSON array expansion.
        """
        try:
            table = self._get_table(table_type="memories")
            if table is None:
                return []
            with self.Session() as sess:
                stmt = select(table.c.topics).where(table.c.topics.is_not(None))
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == to_db_user_id(user_id))
                rows = sess.execute(stmt).fetchall()
            topics: set = set()
            for (row_topics,) in rows:
                if isinstance(row_topics, list):
                    topics.update(t for t in row_topics if t is not None)
            return list(topics)
        except Exception as e:
            log_error(f"Exception reading from memory table: {str(e)}")
            return []

    def get_user_memory(
        self, memory_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        try:
            table = self._get_table(table_type="memories")
            if table is None:
                return None
            with self.Session() as sess, sess.begin():
                stmt = select(table).where(table.c.memory_id == memory_id)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == to_db_user_id(user_id))
                result = sess.execute(stmt).fetchone()
                if not result:
                    return None
                memory_raw = dict(result._mapping)
                memory_raw["user_id"] = from_db_user_id(memory_raw.get("user_id"))
                if not deserialize:
                    return memory_raw
            return UserMemory.from_dict(memory_raw)
        except Exception as e:
            log_error(f"Exception reading from memory table: {str(e)}")
            raise

    def get_user_memories(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        topics: Optional[List[str]] = None,
        search_content: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[UserMemory], Tuple[List[Dict[str, Any]], int]]:
        """Get memories matching the given filters.

        ``topics`` and ``search_content`` are matched in Python, not pushed
        to SQL: Postgres matches both by casting the JSONB column to text and
        substring-searching the raw serialized JSON, which has no single
        cross-variant Oracle equivalent (CAST rejects a native JSON source --
        ORA-22849 -- and JSON_SERIALIZE covers only that one variant). The
        columns Oracle CAN filter in SQL (user_id, agent_id, team_id) still
        are; only these two go through Python, after the SQL-filtered fetch.
        """
        validate_pagination(limit, page)
        try:
            table = self._get_table(table_type="memories")
            if table is None:
                return [] if deserialize else ([], 0)

            with self.Session() as sess, sess.begin():
                stmt = select(table)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == to_db_user_id(user_id))
                if agent_id is not None:
                    stmt = stmt.where(table.c.agent_id == agent_id)
                if team_id is not None:
                    stmt = stmt.where(table.c.team_id == team_id)
                stmt = apply_sorting(stmt, table, sort_by, sort_order)
                rows = sess.execute(stmt).fetchall()

            memories_raw = [dict(record._mapping) for record in rows]
            for m in memories_raw:
                m["user_id"] = from_db_user_id(m.get("user_id"))

            if topics:
                memories_raw = [m for m in memories_raw if m.get("topics") and any(t in m["topics"] for t in topics)]
            if search_content:
                needle = search_content.lower()
                memories_raw = [m for m in memories_raw if needle in json.dumps(m.get("memory") or {}).lower()]

            total_count = len(memories_raw)
            if limit is not None:
                offset = (page - 1) * limit if page and page > 1 else 0
                memories_raw = memories_raw[offset : offset + limit]

            if not deserialize:
                return memories_raw, total_count
            return [UserMemory.from_dict(record) for record in memories_raw]
        except Exception as e:
            log_error(f"Exception reading from memory table: {str(e)}")
            raise

    def get_user_memory_stats(
        self, limit: Optional[int] = None, page: Optional[int] = None, user_id: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], int]:
        validate_pagination(limit, page)
        try:
            table = self._get_table(table_type="memories")
            if table is None:
                return [], 0

            with self.Session() as sess, sess.begin():
                stmt = select(
                    table.c.user_id,
                    func.count(table.c.memory_id).label("total_memories"),
                    func.max(table.c.updated_at).label("last_memory_updated_at"),
                )
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == to_db_user_id(user_id))
                else:
                    stmt = stmt.where(table.c.user_id.is_not(None))
                stmt = stmt.group_by(table.c.user_id).order_by(func.max(table.c.updated_at).desc())

                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = sess.execute(count_stmt).scalar()

                if limit is not None:
                    offset = (page - 1) * limit if page and page > 1 else 0
                    stmt = stmt.offset(offset).limit(limit)

                result = sess.execute(stmt).fetchall()
            if not result:
                return [], 0
            return [
                {
                    "user_id": from_db_user_id(record.user_id),
                    "total_memories": record.total_memories,
                    "last_memory_updated_at": record.last_memory_updated_at,
                }
                for record in result
            ], total_count
        except Exception as e:
            log_error(f"Exception getting user memory stats: {str(e)}")
            raise

    def upsert_user_memory(
        self, memory: UserMemory, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        try:
            table = self._get_table(table_type="memories", create_table_if_not_found=True)
            if table is None:
                return None

            if memory.memory_id is None:
                memory.memory_id = str(uuid4())
            current_time = int(time.time())

            values = {
                "memory_id": memory.memory_id,
                "memory": memory.memory,
                "input": memory.input,
                "user_id": to_db_user_id(memory.user_id),
                "agent_id": memory.agent_id,
                "team_id": memory.team_id,
                "topics": memory.topics,
                "feedback": memory.feedback,
                "created_at": memory.created_at if memory.created_at is not None else current_time,
                "updated_at": memory.updated_at if memory.updated_at is not None else current_time,
            }

            with self.Session() as sess, sess.begin():
                merge_upsert(sess, table, key_columns=["memory_id"], values=values, preserve_on_conflict=["created_at"])
                row = sess.execute(select(table).where(table.c.memory_id == memory.memory_id)).fetchone()
                if row is None:
                    return None
                memory_raw = dict(row._mapping)
                memory_raw["user_id"] = from_db_user_id(memory_raw.get("user_id"))

            if not deserialize:
                return memory_raw
            return UserMemory.from_dict(memory_raw)
        except Exception as e:
            log_error(f"Exception upserting user memory: {str(e)}")
            raise

    def upsert_memories(
        self, memories: List[UserMemory], deserialize: Optional[bool] = True, preserve_updated_at: bool = False
    ) -> List[Union[UserMemory, Dict[str, Any]]]:
        """Bulk upsert, implemented as a loop over upsert_user_memory -- see
        the equivalent note on upsert_sessions for why."""
        if not memories:
            return []
        results: List[Union[UserMemory, Dict[str, Any]]] = []
        for memory in memories:
            saved_updated_at = memory.updated_at if preserve_updated_at else None
            result = self.upsert_user_memory(memory, deserialize=deserialize)
            if result is None:
                continue
            if preserve_updated_at and saved_updated_at is not None:
                table = self._get_table(table_type="memories")
                if table is not None:
                    with self.Session() as sess, sess.begin():
                        sess.execute(
                            table.update()
                            .where(table.c.memory_id == memory.memory_id)
                            .values(updated_at=saved_updated_at)
                        )
                    if isinstance(result, dict):
                        result["updated_at"] = saved_updated_at
                    else:
                        result.updated_at = saved_updated_at  # type: ignore[union-attr]
            results.append(result)
        return results

    # -- Metrics --
    def _get_all_sessions_for_metrics_calculation(
        self, start_timestamp: Optional[int] = None, end_timestamp: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        table = self._get_table(table_type="sessions")
        if table is None:
            return []
        runs_table = self._get_table(table_type="runs")

        stmt = select(
            table.c.session_id, table.c.user_id, table.c.session_data, table.c.created_at, table.c.session_type
        )
        if start_timestamp is not None:
            stmt = stmt.where(table.c.created_at >= start_timestamp)
        if end_timestamp is not None:
            stmt = stmt.where(table.c.created_at <= end_timestamp)

        with self.Session() as sess:
            result = sess.execute(stmt).fetchall()
            sessions = [dict(record._mapping) for record in result]

            if runs_table is not None and sessions:
                session_ids = [s["session_id"] for s in sessions]
                # run_data->model/model_provider read in Python: it already
                # decodes to a dict, so there is no need for a JSON-path SQL
                # operator (Postgres's ->> has no portable Oracle equivalent
                # across both storage variants).
                runs_stmt = select(runs_table.c.session_id, runs_table.c.run_data).where(
                    runs_table.c.session_id.in_(session_ids)
                )
                runs_by_session: Dict[str, List[Dict[str, Any]]] = {}
                for session_id, run_data in sess.execute(runs_stmt).fetchall():
                    run_data = run_data or {}
                    runs_by_session.setdefault(session_id, []).append(
                        {"model": run_data.get("model"), "model_provider": run_data.get("model_provider")}
                    )
                for s in sessions:
                    s["runs"] = runs_by_session.get(s["session_id"], [])
            return sessions

    def _get_metrics_calculation_starting_date(self, table: Table) -> Optional[date]:
        # == True/False, not .is_(True/False): the latter compiles to Oracle's
        # "IS <literal>" operator, which only accepts the keywords NULL, TRUE
        # or FALSE, not a bind parameter -- and OracleNativeBoolean, wrapping
        # Boolean in a TypeDecorator, does not get SQLAlchemy's usual
        # dialect-aware IS TRUE/FALSE rewriting for that comparison. Plain
        # equality binds normally on both the native and emulated variants.
        with self.Session() as sess:
            latest_completed = sess.execute(select(func.max(table.c.date)).where(table.c.completed == True)).scalar()  # noqa: E712

            incomplete_stmt = select(func.min(table.c.date)).where(table.c.completed == False)  # noqa: E712
            if latest_completed is not None:
                incomplete_stmt = incomplete_stmt.where(table.c.date > latest_completed)
            earliest_incomplete = sess.execute(incomplete_stmt).scalar()

            starting_date = metrics_starting_date_from_days(latest_completed, earliest_incomplete)
            if starting_date is not None:
                return starting_date

        first_session, _ = self.get_sessions(sort_by="created_at", sort_order="asc", limit=1, deserialize=False)
        first_session_date = first_session[0]["created_at"] if first_session else None  # type: ignore[index]
        if first_session_date is None:
            return None
        return datetime.fromtimestamp(first_session_date, tz=timezone.utc).date()

    def calculate_metrics(self) -> Optional[List[dict]]:
        try:
            self._metrics_refreshed_at = time.time()

            table = self._get_table(table_type="metrics", create_table_if_not_found=True)
            if table is None:
                return None

            starting_date = self._get_metrics_calculation_starting_date(table)
            if starting_date is None:
                log_debug("No session data found. Won't calculate metrics.")
                return None

            dates_to_process = get_dates_to_calculate_metrics_for(starting_date)
            if not dates_to_process:
                log_debug("Metrics already calculated for all relevant dates.")
                return None

            start_timestamp = int(
                datetime.combine(dates_to_process[0], datetime.min.time()).replace(tzinfo=timezone.utc).timestamp()
            )
            end_timestamp = int(
                datetime.combine(dates_to_process[-1] + timedelta(days=1), datetime.min.time())
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )

            sessions = self._get_all_sessions_for_metrics_calculation(
                start_timestamp=start_timestamp, end_timestamp=end_timestamp
            )
            all_sessions_data = fetch_all_sessions_data(
                sessions=sessions, dates_to_process=dates_to_process, start_timestamp=start_timestamp
            )
            if not all_sessions_data:
                log_debug("No new session data found. Won't calculate metrics.")
                return None

            metrics_records = []
            for date_to_process in dates_to_process:
                sessions_for_date = all_sessions_data.get(date_to_process.isoformat(), {})
                if not any(len(v) > 0 for v in sessions_for_date.values()):
                    continue
                metrics_records.extend(calculate_date_metrics(date_to_process, sessions_for_date))

            if not metrics_records:
                return None

            results: List[dict] = []
            with self.Session() as sess, sess.begin():
                for record in metrics_records:
                    # Translate the empty-owner bucket to the sentinel before
                    # it reaches Oracle -- "" folds to NULL there, colliding
                    # with the unique constraint's NULL-is-distinct behavior
                    # for every other unowned row (see ADR 0005 / utils.py).
                    db_record = dict(record)
                    db_record["user_id"] = to_db_user_id(db_record.get("user_id"))
                    merge_upsert(
                        sess,
                        table,
                        key_columns=["user_id", "date", "aggregation_period"],
                        values=db_record,
                        preserve_on_conflict=["id", "created_at"],
                    )
                for record in metrics_records:
                    row = sess.execute(
                        select(table).where(
                            table.c.user_id == to_db_user_id(record["user_id"]),
                            table.c.date == record["date"],
                            table.c.aggregation_period == record["aggregation_period"],
                        )
                    ).fetchone()
                    if row is not None:
                        results.append(dict(row._mapping))

            log_debug("Updated metrics calculations")
            return results
        except Exception as e:
            log_error(f"Exception refreshing metrics: {str(e)}")
            raise

    def get_metrics(
        self, starting_date: Optional[date] = None, ending_date: Optional[date] = None, user_id: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        try:
            if time.time() - self._metrics_refreshed_at >= 60:
                try:
                    self.calculate_metrics()
                except Exception as e:
                    log_warning(f"Could not refresh metrics before reading them: {str(e)}")

            table = self._get_table(table_type="metrics", create_table_if_not_found=True)
            if table is None:
                return [], None

            with self.Session() as sess, sess.begin():
                stmt = select(table)
                if starting_date:
                    stmt = stmt.where(table.c.date >= starting_date)
                if ending_date:
                    stmt = stmt.where(table.c.date <= ending_date)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == to_db_user_id(user_id))
                result = sess.execute(stmt).fetchall()
                if not result:
                    return [], None

                latest_stmt = select(func.max(table.c.updated_at))
                if user_id is not None:
                    latest_stmt = latest_stmt.where(table.c.user_id == to_db_user_id(user_id))
                latest_updated_at = sess.execute(latest_stmt).scalar()

            rows: List[dict] = []
            for row in result:
                row_dict = dict(row._mapping)
                # Mirrors Postgres's own display convention for this method:
                # the unowned bucket is shown to API consumers as None, not
                # as the empty string it round-trips to via from_db_user_id.
                translated = from_db_user_id(row_dict.get("user_id"))
                row_dict["user_id"] = None if translated == "" else translated
                rows.append(row_dict)
            return rows, latest_updated_at
        except Exception as e:
            log_error(f"Exception getting metrics: {str(e)}")
            raise

    # -- Knowledge --
    def delete_knowledge_content(self, id: str, user_id: Optional[str] = None):
        try:
            table = self._get_table(table_type="knowledge")
            if table is None:
                return
            with self.Session() as sess, sess.begin():
                stmt = table.delete().where(table.c.id == id)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                sess.execute(stmt)
        except Exception as e:
            log_error(f"Exception deleting knowledge content: {str(e)}")
            raise

    def get_knowledge_content(self, id: str, user_id: Optional[str] = None) -> Optional[KnowledgeRow]:
        try:
            table = self._get_table(table_type="knowledge")
            if table is None:
                return None
            with self.Session() as sess, sess.begin():
                stmt = select(table).where(table.c.id == id)
                if user_id is not None:
                    stmt = stmt.where((table.c.user_id == user_id) | (table.c.user_id.is_(None)))
                result = sess.execute(stmt).fetchone()
                if result is None:
                    return None
                return KnowledgeRow.model_validate(result._mapping)
        except Exception as e:
            log_error(f"Exception getting knowledge content: {str(e)}")
            raise

    def get_knowledge_contents(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        linked_to: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[KnowledgeRow], int]:
        validate_pagination(limit, page)
        try:
            table = self._get_table(table_type="knowledge")
            if table is None:
                return [], 0

            with self.Session() as sess, sess.begin():
                stmt = select(table)
                if linked_to is not None:
                    stmt = stmt.where(table.c.linked_to == linked_to)
                if user_id is not None:
                    stmt = stmt.where((table.c.user_id == user_id) | (table.c.user_id.is_(None)))
                stmt = apply_sorting(stmt, table, sort_by, sort_order)

                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = sess.execute(count_stmt).scalar()

                if limit is not None:
                    offset = (page - 1) * limit if page and page > 1 else 0
                    stmt = stmt.offset(offset).limit(limit)

                result = sess.execute(stmt).fetchall()
                return [KnowledgeRow.model_validate(record._mapping) for record in result], total_count
        except Exception as e:
            log_error(f"Exception getting knowledge contents: {str(e)}")
            raise

    def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        try:
            table = self._get_table(table_type="knowledge", create_table_if_not_found=True)
            if table is None:
                return None

            values = {key: value for key, value in knowledge_row.model_dump().items() if key in table.c}
            with self.Session() as sess, sess.begin():
                merge_upsert(sess, table, key_columns=["id"], values=values, preserve_on_conflict=["created_at"])
                row = sess.execute(select(table).where(table.c.id == knowledge_row.id)).fetchone()
            if row is None:
                return None
            return KnowledgeRow.model_validate(row._mapping)
        except Exception as e:
            log_error(f"Exception upserting knowledge content: {str(e)}")
            raise

    # -- Evals --
    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        try:
            table = self._get_table(table_type="evals", create_table_if_not_found=True)
            if table is None:
                return None
            with self.Session() as sess, sess.begin():
                current_time = int(time.time())
                eval_data = eval_run.model_dump()
                eval_data["user_id"] = to_db_user_id(eval_data.get("user_id"))
                sess.execute(
                    table.insert().values({"created_at": current_time, "updated_at": current_time, **eval_data})
                )
            return eval_run
        except Exception as e:
            log_error(f"Error creating eval run: {str(e)}")
            raise

    def delete_eval_run(self, eval_run_id: str) -> None:
        try:
            table = self._get_table(table_type="evals")
            if table is None:
                return
            with self.Session() as sess, sess.begin():
                result = sess.execute(table.delete().where(table.c.run_id == eval_run_id))
                if result.rowcount == 0:
                    log_warning(f"No eval run found with ID: {eval_run_id}")
        except Exception as e:
            log_error(f"Error deleting eval run {eval_run_id}: {str(e)}")
            raise

    def delete_eval_runs(self, eval_run_ids: List[str], user_id: Optional[str] = None) -> None:
        try:
            table = self._get_table(table_type="evals")
            if table is None:
                return
            with self.Session() as sess, sess.begin():
                stmt = table.delete().where(table.c.run_id.in_(eval_run_ids))
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == to_db_user_id(user_id))
                sess.execute(stmt)
        except Exception as e:
            log_error(f"Error deleting eval runs {eval_run_ids}: {str(e)}")
            raise

    def get_eval_run(
        self, eval_run_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        try:
            table = self._get_table(table_type="evals")
            if table is None:
                return None
            with self.Session() as sess, sess.begin():
                stmt = select(table).where(table.c.run_id == eval_run_id)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == to_db_user_id(user_id))
                result = sess.execute(stmt).fetchone()
                if result is None:
                    return None
                eval_run_raw = dict(result._mapping)
                eval_run_raw["user_id"] = from_db_user_id(eval_run_raw.get("user_id"))
                if not deserialize:
                    return eval_run_raw
                return EvalRunRecord.model_validate(eval_run_raw)
        except Exception as e:
            log_error(f"Exception getting eval run {eval_run_id}: {str(e)}")
            raise

    def get_eval_runs(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        model_id: Optional[str] = None,
        filter_type: Optional[EvalFilterType] = None,
        eval_type: Optional[List[EvalType]] = None,
        deserialize: Optional[bool] = True,
        user_id: Optional[str] = None,
    ) -> Union[List[EvalRunRecord], Tuple[List[Dict[str, Any]], int]]:
        validate_pagination(limit, page)
        try:
            table = self._get_table(table_type="evals")
            if table is None:
                return [] if deserialize else ([], 0)

            with self.Session() as sess, sess.begin():
                stmt = select(table)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == to_db_user_id(user_id))
                if agent_id is not None:
                    stmt = stmt.where(table.c.agent_id == agent_id)
                if team_id is not None:
                    stmt = stmt.where(table.c.team_id == team_id)
                if workflow_id is not None:
                    stmt = stmt.where(table.c.workflow_id == workflow_id)
                if model_id is not None:
                    stmt = stmt.where(table.c.model_id == model_id)
                if eval_type:
                    eval_type_values = [e.value if hasattr(e, "value") else e for e in eval_type]
                    stmt = stmt.where(table.c.eval_type.in_(eval_type_values))
                if filter_type is not None:
                    if filter_type == EvalFilterType.AGENT:
                        stmt = stmt.where(table.c.agent_id.is_not(None))
                    elif filter_type == EvalFilterType.TEAM:
                        stmt = stmt.where(table.c.team_id.is_not(None))
                    elif filter_type == EvalFilterType.WORKFLOW:
                        stmt = stmt.where(table.c.workflow_id.is_not(None))

                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = sess.execute(count_stmt).scalar()

                if sort_by is None:
                    stmt = stmt.order_by(table.c.created_at.desc())
                else:
                    stmt = apply_sorting(stmt, table, sort_by, sort_order)

                if limit is not None:
                    offset = (page - 1) * limit if page and page > 1 else 0
                    stmt = stmt.offset(offset).limit(limit)

                result = sess.execute(stmt).fetchall()
                if not result:
                    return [] if deserialize else ([], 0)

                eval_runs_raw = [dict(row._mapping) for row in result]
                for r in eval_runs_raw:
                    r["user_id"] = from_db_user_id(r.get("user_id"))

                if not deserialize:
                    return eval_runs_raw, total_count
                return [EvalRunRecord.model_validate(row) for row in eval_runs_raw]
        except Exception as e:
            log_error(f"Exception getting eval runs: {str(e)}")
            raise

    def rename_eval_run(
        self, eval_run_id: str, name: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        try:
            table = self._get_table(table_type="evals")
            if table is None:
                return None
            with self.Session() as sess, sess.begin():
                stmt = (
                    table.update().where(table.c.run_id == eval_run_id).values(name=name, updated_at=int(time.time()))
                )
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == to_db_user_id(user_id))
                sess.execute(stmt)

            eval_run_raw = self.get_eval_run(eval_run_id=eval_run_id, deserialize=deserialize, user_id=user_id)
            if not eval_run_raw or not deserialize:
                return eval_run_raw
            return EvalRunRecord.model_validate(eval_run_raw)
        except Exception as e:
            log_error(f"Error upserting eval run name {eval_run_id}: {str(e)}")
            raise

    def update_eval_run_user_id(self, eval_run_id: str, user_id: str) -> None:
        try:
            table = self._get_table(table_type="evals")
            if table is None:
                return
            with self.Session() as sess, sess.begin():
                sess.execute(table.update().where(table.c.run_id == eval_run_id).values(user_id=to_db_user_id(user_id)))
        except Exception as e:
            log_error(f"Error setting owner on eval run {eval_run_id}: {str(e)}")
            raise

    # -- Traces --
    @staticmethod
    def _trace_component_level(
        workflow_id: Optional[str], team_id: Optional[str], agent_id: Optional[str], name: Optional[str]
    ) -> int:
        """Component priority for upsert_trace's name-preference rule.

        Mirrors Postgres's SQL CASE expression of the same name, computed in
        Python instead: this whole method exists only because upsert_trace
        merges in Python rather than in SQL (see that method's docstring).
        """
        is_root_name = name is not None and (".run" in name or ".arun" in name)
        if workflow_id is not None and is_root_name:
            return 3
        if team_id is not None and is_root_name:
            return 2
        if agent_id is not None and is_root_name:
            return 1
        return 0

    def upsert_trace(self, trace: Any) -> None:
        """Create or update a single trace record.

        Postgres does this merge in one SQL statement (ON CONFLICT DO UPDATE,
        with GREATEST/LEAST for start/end time and EXTRACT(EPOCH FROM ...) for
        duration). EXTRACT(EPOCH ...) has no Oracle equivalent over the string
        columns start_time/end_time are stored as; read-modify-write in Python
        under a row lock reproduces the same merge semantics -- earliest
        start, latest end, recomputed duration, non-null context preserved,
        name replaced only by a higher-priority component -- without needing
        one.
        """
        try:
            table = self._get_table(table_type="traces", create_table_if_not_found=True)
            if table is None:
                return

            trace_dict = trace.to_dict()
            trace_dict.pop("total_spans", None)
            trace_dict.pop("error_count", None)
            trace_dict["user_id"] = to_db_user_id(trace_dict.get("user_id"))

            with self.Session() as sess, sess.begin():
                existing = sess.execute(
                    select(table).where(table.c.trace_id == trace_dict["trace_id"]).with_for_update()
                ).fetchone()

                if existing is None:
                    merge_upsert(sess, table, key_columns=["trace_id"], values=trace_dict)
                    return

                existing_row = dict(existing._mapping)
                new_start, new_end = trace_dict.get("start_time"), trace_dict.get("end_time")
                # ISO 8601 strings compare correctly lexicographically.
                merged_start = min(existing_row["start_time"], new_start) if new_start else existing_row["start_time"]
                merged_end = max(existing_row["end_time"], new_end) if new_end else existing_row["end_time"]
                try:
                    start_dt = datetime.fromisoformat(merged_start.replace("Z", "+00:00"))
                    end_dt = datetime.fromisoformat(merged_end.replace("Z", "+00:00"))
                    duration_ms = int((end_dt - start_dt).total_seconds() * 1000)
                except Exception:
                    duration_ms = trace_dict.get("duration_ms", existing_row.get("duration_ms"))

                new_level = self._trace_component_level(
                    trace_dict.get("workflow_id"),
                    trace_dict.get("team_id"),
                    trace_dict.get("agent_id"),
                    trace_dict.get("name"),
                )
                existing_level = self._trace_component_level(
                    existing_row.get("workflow_id"),
                    existing_row.get("team_id"),
                    existing_row.get("agent_id"),
                    existing_row.get("name"),
                )
                name = trace_dict.get("name") if new_level > existing_level else existing_row.get("name")

                merged = {
                    "trace_id": trace_dict["trace_id"],
                    "name": name,
                    "status": trace_dict.get("status"),
                    "start_time": merged_start,
                    "end_time": merged_end,
                    "duration_ms": duration_ms,
                    # COALESCE-equivalent: keep the existing non-null context
                    # value, so a later upsert from an unrelated child span
                    # cannot clobber the trace's already-correct context.
                    "run_id": existing_row.get("run_id") or trace_dict.get("run_id"),
                    "session_id": existing_row.get("session_id") or trace_dict.get("session_id"),
                    "user_id": existing_row.get("user_id") or trace_dict.get("user_id"),
                    "agent_id": existing_row.get("agent_id") or trace_dict.get("agent_id"),
                    "team_id": existing_row.get("team_id") or trace_dict.get("team_id"),
                    "workflow_id": existing_row.get("workflow_id") or trace_dict.get("workflow_id"),
                    "created_at": existing_row.get("created_at"),
                }
                merge_upsert(sess, table, key_columns=["trace_id"], values=merged, preserve_on_conflict=["created_at"])
        except Exception as e:
            log_error(f"Error creating trace: {str(e)}")
            # Don't raise -- tracing should not break the main application flow

    def _traces_base_query(self, table: Table, spans_table: Optional[Table]):
        from sqlalchemy import case as _case
        from sqlalchemy import literal as _literal

        if spans_table is not None:
            return (
                select(
                    table,
                    func.coalesce(func.count(spans_table.c.span_id), 0).label("total_spans"),
                    func.coalesce(func.sum(_case((spans_table.c.status_code == "ERROR", 1), else_=0)), 0).label(
                        "error_count"
                    ),
                )
                .select_from(table.outerjoin(spans_table, table.c.trace_id == spans_table.c.trace_id))
                # Group by every column of `table`, not just trace_id (the
                # PK): Postgres allows grouping by a primary key alone and
                # selecting the table's other columns unaggregated, inferring
                # the functional dependency; Oracle has no such relaxation
                # and raises ORA-00979 ("must appear in the GROUP BY clause")
                # on any selected column that is not listed, confirmed
                # against a live server. Grouping by every column is
                # semantically identical here since trace_id is unique.
                .group_by(*table.c)
            )
        return select(table, _literal(0).label("total_spans"), _literal(0).label("error_count"))

    def get_trace(self, trace_id: Optional[str] = None, run_id: Optional[str] = None):
        try:
            from agno.tracing.schemas import Trace

            table = self._get_table(table_type="traces")
            if table is None:
                return None
            spans_table = self._get_table(table_type="spans")

            with self.Session() as sess:
                stmt = self._traces_base_query(table, spans_table)
                if trace_id:
                    stmt = stmt.where(table.c.trace_id == trace_id)
                elif run_id:
                    stmt = stmt.where(table.c.run_id == run_id)
                else:
                    return None
                stmt = stmt.order_by(table.c.start_time.desc()).limit(1)
                result = sess.execute(stmt).fetchone()
                if result is None:
                    return None
                row = dict(result._mapping)
                row["user_id"] = from_db_user_id(row.get("user_id"))
                return Trace.from_dict(row)
        except Exception as e:
            log_error(f"Error getting trace: {str(e)}")
            return None

    def get_traces(
        self,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: Optional[int] = 20,
        page: Optional[int] = 1,
        filter_expr: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List, int]:
        try:
            from agno.db.filter_converter import TRACE_COLUMNS, filter_expr_to_sqlalchemy
            from agno.tracing.schemas import Trace

            table = self._get_table(table_type="traces")
            if table is None:
                return [], 0
            spans_table = self._get_table(table_type="spans")

            with self.Session() as sess:
                base_stmt = self._traces_base_query(table, spans_table)
                if run_id:
                    base_stmt = base_stmt.where(table.c.run_id == run_id)
                if session_id:
                    base_stmt = base_stmt.where(table.c.session_id == session_id)
                if user_id is not None:
                    base_stmt = base_stmt.where(table.c.user_id == to_db_user_id(user_id))
                if agent_id:
                    base_stmt = base_stmt.where(table.c.agent_id == agent_id)
                if team_id:
                    base_stmt = base_stmt.where(table.c.team_id == team_id)
                if workflow_id:
                    base_stmt = base_stmt.where(table.c.workflow_id == workflow_id)
                if status:
                    base_stmt = base_stmt.where(table.c.status == status)
                if start_time:
                    base_stmt = base_stmt.where(table.c.start_time >= start_time.isoformat())
                if end_time:
                    base_stmt = base_stmt.where(table.c.end_time <= end_time.isoformat())
                if filter_expr:
                    try:
                        base_stmt = base_stmt.where(
                            filter_expr_to_sqlalchemy(filter_expr, table, allowed_columns=TRACE_COLUMNS)
                        )
                    except ValueError:
                        raise
                    except (KeyError, TypeError) as e:
                        raise ValueError(f"Invalid filter expression: {e}") from e

                count_stmt = select(func.count()).select_from(base_stmt.alias())
                total_count = sess.execute(count_stmt).scalar() or 0

                offset = (page - 1) * limit if page and limit else 0
                paginated_stmt = base_stmt.order_by(table.c.start_time.desc()).limit(limit).offset(offset)
                results = sess.execute(paginated_stmt).fetchall()

                traces = []
                for row in results:
                    row_dict = dict(row._mapping)
                    row_dict["user_id"] = from_db_user_id(row_dict.get("user_id"))
                    traces.append(Trace.from_dict(row_dict))
                return traces, total_count
        except Exception as e:
            log_error(f"Error getting traces: {str(e)}")
            return [], 0

    def get_trace_stats(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: Optional[int] = 20,
        page: Optional[int] = 1,
        filter_expr: Optional[Dict[str, Any]] = None,
        group_by: str = "session",
    ) -> Tuple[List[Dict[str, Any]], int]:
        if group_by not in ("session", "agent", "team", "workflow", "endpoint"):
            raise ValueError(f"Invalid group_by value: {group_by!r}. Allowed: session, agent, team, workflow, endpoint")
        try:
            from sqlalchemy import and_ as _and
            from sqlalchemy import case as _case
            from sqlalchemy import distinct as _distinct

            from agno.db.filter_converter import TRACE_COLUMNS, filter_expr_to_sqlalchemy

            table = self._get_table(table_type="traces")
            if table is None:
                return [], 0

            with self.Session() as sess:
                group_column = None
                group_label = ""
                if group_by == "session":
                    base_stmt = (
                        select(
                            table.c.session_id,
                            func.max(table.c.user_id).label("user_id"),
                            func.max(table.c.agent_id).label("agent_id"),
                            func.max(table.c.team_id).label("team_id"),
                            func.max(table.c.workflow_id).label("workflow_id"),
                            func.count(table.c.trace_id).label("total_traces"),
                            func.min(table.c.created_at).label("first_trace_at"),
                            func.max(table.c.created_at).label("last_trace_at"),
                        )
                        .where(table.c.session_id.is_not(None))
                        .group_by(table.c.session_id)
                    )
                else:
                    if group_by == "endpoint":
                        group_column = table.c.name
                        group_label = "name"
                        group_filter = _and(
                            table.c.agent_id.is_(None), table.c.team_id.is_(None), table.c.workflow_id.is_(None)
                        )
                    else:
                        group_column = {
                            "agent": table.c.agent_id,
                            "team": table.c.team_id,
                            "workflow": table.c.workflow_id,
                        }[group_by]
                        group_label = f"{group_by}_id"
                        group_filter = group_column.is_not(None)
                    base_stmt = (
                        select(
                            group_column.label(group_label),
                            func.count(table.c.trace_id).label("total_traces"),
                            func.count(_distinct(table.c.session_id)).label("total_sessions"),
                            func.avg(table.c.duration_ms).label("avg_duration_ms"),
                            func.percentile_cont(0.95).within_group(table.c.duration_ms).label("p95_duration_ms"),
                            func.max(table.c.duration_ms).label("max_duration_ms"),
                            func.sum(_case((table.c.status == "ERROR", 1), else_=0)).label("error_traces"),
                            func.min(table.c.created_at).label("first_trace_at"),
                            func.max(table.c.created_at).label("last_trace_at"),
                        )
                        .where(group_filter)
                        .group_by(group_column)
                    )

                if user_id is not None:
                    base_stmt = base_stmt.where(table.c.user_id == to_db_user_id(user_id))
                if workflow_id:
                    base_stmt = base_stmt.where(table.c.workflow_id == workflow_id)
                if team_id:
                    base_stmt = base_stmt.where(table.c.team_id == team_id)
                if agent_id:
                    base_stmt = base_stmt.where(table.c.agent_id == agent_id)
                if start_time:
                    base_stmt = base_stmt.where(table.c.created_at >= start_time.isoformat())
                if end_time:
                    base_stmt = base_stmt.where(table.c.created_at <= end_time.isoformat())
                if filter_expr:
                    try:
                        base_stmt = base_stmt.where(
                            filter_expr_to_sqlalchemy(filter_expr, table, allowed_columns=TRACE_COLUMNS)
                        )
                    except ValueError:
                        raise
                    except (KeyError, TypeError) as e:
                        raise ValueError(f"Invalid filter expression: {e}") from e

                count_stmt = select(func.count()).select_from(base_stmt.alias())
                total_count = sess.execute(count_stmt).scalar() or 0

                offset = (page - 1) * limit if page and limit else 0
                order_by: List[Any] = (
                    [func.max(table.c.created_at).desc()]
                    if group_by == "session"
                    else [func.count(table.c.trace_id).desc(), group_column]
                )
                paginated_stmt = base_stmt.order_by(*order_by).limit(limit).offset(offset)
                results = sess.execute(paginated_stmt).fetchall()

                stats_list = []
                for row in results:
                    first_trace_at = datetime.fromisoformat(str(row.first_trace_at).replace("Z", "+00:00"))
                    last_trace_at = datetime.fromisoformat(str(row.last_trace_at).replace("Z", "+00:00"))
                    if group_by == "session":
                        stats_list.append(
                            {
                                "session_id": row.session_id,
                                "user_id": from_db_user_id(row.user_id),
                                "agent_id": row.agent_id,
                                "team_id": row.team_id,
                                "workflow_id": row.workflow_id,
                                "total_traces": row.total_traces,
                                "first_trace_at": first_trace_at,
                                "last_trace_at": last_trace_at,
                            }
                        )
                    else:
                        stats_list.append(
                            {
                                group_label: getattr(row, group_label),
                                "total_traces": row.total_traces,
                                "total_sessions": row.total_sessions,
                                "avg_duration_ms": round(float(row.avg_duration_ms), 1)
                                if row.avg_duration_ms is not None
                                else None,
                                "p95_duration_ms": round(float(row.p95_duration_ms), 1)
                                if row.p95_duration_ms is not None
                                else None,
                                "max_duration_ms": row.max_duration_ms,
                                "error_traces": row.error_traces,
                                "first_trace_at": first_trace_at,
                                "last_trace_at": last_trace_at,
                            }
                        )
                return stats_list, total_count
        except Exception as e:
            log_error(f"Error getting trace stats: {str(e)}")
            return [], 0

    # -- Spans --
    def create_span(self, span: Any) -> None:
        try:
            table = self._get_table(table_type="spans", create_table_if_not_found=True)
            if table is None:
                return
            with self.Session() as sess, sess.begin():
                sess.execute(table.insert().values(span.to_dict()))
        except Exception as e:
            log_error(f"Error creating span: {str(e)}")

    def create_spans(self, spans: List) -> None:
        if not spans:
            return
        try:
            table = self._get_table(table_type="spans", create_table_if_not_found=True)
            if table is None:
                return
            with self.Session() as sess, sess.begin():
                for span in spans:
                    sess.execute(table.insert().values(span.to_dict()))
        except Exception as e:
            log_error(f"Error creating spans batch: {str(e)}")

    def get_span(self, span_id: str):
        try:
            from agno.tracing.schemas import Span

            table = self._get_table(table_type="spans")
            if table is None:
                return None
            with self.Session() as sess:
                result = sess.execute(select(table).where(table.c.span_id == span_id)).fetchone()
                if result:
                    return Span.from_dict(dict(result._mapping))
                return None
        except Exception as e:
            log_error(f"Error getting span: {str(e)}")
            return None

    def get_spans(
        self, trace_id: Optional[str] = None, parent_span_id: Optional[str] = None, limit: Optional[int] = 1000
    ) -> List:
        try:
            from agno.tracing.schemas import Span

            table = self._get_table(table_type="spans")
            if table is None:
                return []
            with self.Session() as sess:
                stmt = select(table)
                if trace_id:
                    stmt = stmt.where(table.c.trace_id == trace_id)
                if parent_span_id:
                    stmt = stmt.where(table.c.parent_span_id == parent_span_id)
                if limit:
                    stmt = stmt.limit(limit)
                results = sess.execute(stmt).fetchall()
                return [Span.from_dict(dict(row._mapping)) for row in results]
        except Exception as e:
            log_error(f"Error getting spans: {str(e)}")
            return []

    def get_learning(
        self,
        learning_type: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        try:
            table = self._get_table(table_type="learnings")
            if table is None:
                return None
            with self.Session() as sess:
                stmt = select(table).where(table.c.learning_type == learning_type)
                stmt = self._apply_learning_filters(
                    stmt, table, user_id, agent_id, team_id, None, session_id, namespace, entity_id, entity_type
                )
                result = sess.execute(stmt).fetchone()
                if result is None:
                    return None
                return {"content": dict(result._mapping).get("content")}
        except Exception as e:
            log_debug(f"Error retrieving learning: {e}")
            return None

    def _apply_learning_filters(
        self,
        stmt: Any,
        table: Table,
        user_id: Optional[str],
        agent_id: Optional[str],
        team_id: Optional[str],
        workflow_id: Optional[str],
        session_id: Optional[str],
        namespace: Optional[str],
        entity_id: Optional[str],
        entity_type: Optional[str],
    ) -> Any:
        if user_id is not None:
            stmt = stmt.where(table.c.user_id == to_db_user_id(user_id))
        if agent_id is not None:
            stmt = stmt.where(table.c.agent_id == agent_id)
        if team_id is not None:
            stmt = stmt.where(table.c.team_id == team_id)
        if workflow_id is not None:
            stmt = stmt.where(table.c.workflow_id == workflow_id)
        if session_id is not None:
            stmt = stmt.where(table.c.session_id == session_id)
        if namespace is not None:
            stmt = stmt.where(table.c.namespace == namespace)
        if entity_id is not None:
            stmt = stmt.where(table.c.entity_id == entity_id)
        if entity_type is not None:
            stmt = stmt.where(table.c.entity_type == entity_type)
        return stmt

    def upsert_learning(
        self,
        id: str,
        learning_type: str,
        content: Dict[str, Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            table = self._get_table(table_type="learnings", create_table_if_not_found=True)
            if table is None:
                return
            current_time = int(time.time())
            values = {
                "learning_id": id,
                "learning_type": learning_type,
                "namespace": namespace,
                "user_id": to_db_user_id(user_id),
                "agent_id": agent_id,
                "team_id": team_id,
                "session_id": session_id,
                "entity_id": entity_id,
                "entity_type": entity_type,
                "content": content,
                "metadata": metadata,
                "created_at": current_time,
                "updated_at": current_time,
            }
            with self.Session() as sess, sess.begin():
                merge_upsert(
                    sess, table, key_columns=["learning_id"], values=values, preserve_on_conflict=["created_at"]
                )
            log_debug(f"Upserted learning: {id}")
        except Exception as e:
            log_debug(f"Error upserting learning: {e}")

    def delete_learning(self, id: str) -> bool:
        try:
            table = self._get_table(table_type="learnings")
            if table is None:
                return False
            with self.Session() as sess, sess.begin():
                result = sess.execute(table.delete().where(table.c.learning_id == id))
                return result.rowcount > 0
        except Exception as e:
            log_debug(f"Error deleting learning: {e}")
            return False

    def update_learning(self, id: str, content: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None) -> bool:
        try:
            table = self._get_table(table_type="learnings")
            if table is None:
                return False
            with self.Session() as sess, sess.begin():
                stmt = (
                    table.update()
                    .where(table.c.learning_id == id)
                    .values(content=content, metadata=metadata, updated_at=int(time.time()))
                )
                result = sess.execute(stmt)
                return (result.rowcount or 0) > 0
        except Exception as e:
            log_error(f"Error updating learning: {e}")
            raise

    def delete_user_learnings(self, user_id: str, learning_type: Optional[str] = None) -> int:
        try:
            table = self._get_table(table_type="learnings")
            if table is None:
                return 0
            with self.Session() as sess, sess.begin():
                stmt = table.delete().where(table.c.user_id == to_db_user_id(user_id))
                if learning_type is not None:
                    stmt = stmt.where(table.c.learning_type == learning_type)
                result = sess.execute(stmt)
                return result.rowcount or 0
        except Exception as e:
            log_error(f"Error deleting user learnings: {e}")
            raise

    def get_learnings(
        self,
        learning_type: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        try:
            table = self._get_table(table_type="learnings")
            if table is None:
                return []
            with self.Session() as sess:
                stmt = select(table)
                if learning_type is not None:
                    stmt = stmt.where(table.c.learning_type == learning_type)
                stmt = self._apply_learning_filters(
                    stmt, table, user_id, agent_id, team_id, workflow_id, session_id, namespace, entity_id, entity_type
                )
                stmt = stmt.order_by(table.c.updated_at.desc())
                if limit is not None:
                    stmt = stmt.limit(limit)
                result = sess.execute(stmt).fetchall()
                rows = [dict(row._mapping) for row in result]
                for r in rows:
                    r["user_id"] = from_db_user_id(r.get("user_id"))
                return rows
        except Exception as e:
            log_debug(f"Error getting learnings: {e}")
            return []

    def search_learnings(
        self,
        query: str,
        learning_type: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Search learning records by text query.

        Contract (base.py): a database error MUST raise, never come back as
        an empty list -- a broken query must not be mistaken for an empty
        store. Nothing below catches or suppresses; a failure from
        sess.execute() propagates as-is.

        Matching happens in Python, not via Postgres's CAST-to-text ILIKE:
        content is a JSON column, and CAST rejects a native JSON source
        (ORA-22849, the same restriction get_user_memories' search_content
        works around). learning_search_patterns already returns SQL LIKE
        syntax (%, _, backslash-escaped); _like_pattern_to_regex translates
        that same pattern language to a compiled, case-insensitive regex
        instead of reimplementing the matching rules from scratch.
        """
        patterns = learning_search_patterns(query)
        if not patterns:
            return []
        regexes = [self._like_pattern_to_regex(p) for p in patterns]

        table = self._get_table(table_type="learnings")
        if table is None:
            return []

        stmt = select(table)
        if learning_type is not None:
            stmt = stmt.where(table.c.learning_type == learning_type)
        stmt = self._apply_learning_filters(
            stmt, table, user_id, agent_id, team_id, workflow_id, session_id, namespace, entity_id, entity_type
        )

        with self.Session() as sess:
            rows = sess.execute(stmt).fetchall()  # no try/except: a broken query must raise

        results = [dict(row._mapping) for row in rows]
        matched = [r for r in results if any(rx.search(json.dumps(r.get("content") or {})) for rx in regexes)]
        matched.sort(key=lambda r: r.get("updated_at") or 0, reverse=True)
        for r in matched:
            r["user_id"] = from_db_user_id(r.get("user_id"))
        if limit is not None:
            matched = matched[:limit]
        return matched

    @staticmethod
    def _like_pattern_to_regex(pattern: str):
        """Translate one SQL LIKE pattern (%, _, backslash-escaped) from
        learning_search_patterns into a compiled, case-insensitive regex."""
        import re as _re

        out = []
        i = 0
        while i < len(pattern):
            c = pattern[i]
            if c == "\\" and i + 1 < len(pattern):
                out.append(_re.escape(pattern[i + 1]))
                i += 2
                continue
            if c == "%":
                out.append(".*")
            elif c == "_":
                out.append(".")
            else:
                out.append(_re.escape(c))
            i += 1
        return _re.compile("".join(out), _re.IGNORECASE | _re.DOTALL)

    def get_learning_by_id(self, id: str) -> Optional[Dict[str, Any]]:
        try:
            table = self._get_table(table_type="learnings")
            if table is None:
                return None
            with self.Session() as sess:
                result = sess.execute(select(table).where(table.c.learning_id == id)).fetchone()
                if result is None:
                    return None
                row = dict(result._mapping)
                row["user_id"] = from_db_user_id(row.get("user_id"))
                return row
        except Exception as e:
            log_error(f"Error getting learning by id: {e}")
            raise

    def list_learnings(
        self,
        learning_type: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        include_global: bool = False,
        limit: int = 100,
        page: int = 1,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        try:
            table = self._get_table(table_type="learnings")
            if table is None:
                return [], 0
            with self.Session() as sess:
                stmt = select(table)
                if learning_type is not None:
                    stmt = stmt.where(table.c.learning_type == learning_type)
                if user_id is not None:
                    db_user_id = to_db_user_id(user_id)
                    if include_global:
                        stmt = stmt.where((table.c.user_id == db_user_id) | (table.c.user_id.is_(None)))
                    else:
                        stmt = stmt.where(table.c.user_id == db_user_id)
                if agent_id is not None:
                    stmt = stmt.where(table.c.agent_id == agent_id)
                if team_id is not None:
                    stmt = stmt.where(table.c.team_id == team_id)
                if session_id is not None:
                    stmt = stmt.where(table.c.session_id == session_id)
                if namespace is not None:
                    stmt = stmt.where(table.c.namespace == namespace)
                if entity_id is not None:
                    stmt = stmt.where(table.c.entity_id == entity_id)
                if entity_type is not None:
                    stmt = stmt.where(table.c.entity_type == entity_type)

                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = sess.execute(count_stmt).scalar() or 0

                stmt = apply_sorting(stmt, table, sort_by or "updated_at", sort_order or "desc")
                stmt = stmt.limit(limit).offset((page - 1) * limit)
                result = sess.execute(stmt).fetchall()
                rows = [dict(row._mapping) for row in result]
                for r in rows:
                    r["user_id"] = from_db_user_id(r.get("user_id"))
                return rows, int(total_count)
        except Exception as e:
            log_error(f"Error listing learnings: {e}")
            raise

    def get_learnings_user_stats(
        self,
        learning_type: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        user_id: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        validate_pagination(limit, page)
        try:
            table = self._get_table(table_type="learnings")
            if table is None:
                return [], 0
            with self.Session() as sess:
                last_updated_col = func.max(table.c.updated_at)
                stmt = select(table.c.user_id, last_updated_col.label("last_learning_updated_at"))
                if learning_type is not None:
                    stmt = stmt.where(table.c.learning_type == learning_type)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == to_db_user_id(user_id))
                else:
                    stmt = stmt.where(table.c.user_id.is_not(None))
                stmt = stmt.group_by(table.c.user_id)

                sort_columns = {"user_id": table.c.user_id, "last_learning_updated_at": last_updated_col}
                sort_col = sort_columns.get(sort_by or "last_learning_updated_at", last_updated_col)
                stmt = stmt.order_by(sort_col.asc() if sort_order == "asc" else sort_col.desc())

                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = sess.execute(count_stmt).scalar() or 0

                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset((page - 1) * limit)

                result = sess.execute(stmt).fetchall()
                return [
                    {"user_id": from_db_user_id(row.user_id), "last_learning_updated_at": row.last_learning_updated_at}
                    for row in result
                ], int(total_count)
        except Exception as e:
            log_error(f"Error getting learning user stats: {e}")
            raise
