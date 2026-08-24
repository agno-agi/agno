import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Sequence, Set, Tuple, Union, cast
from uuid import uuid4

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace

from agno.db import mcp_oauth_store
from agno.db.base import (
    DELETED_CONFIG_STAGE,
    PIN_LINK_KINDS,
    BaseDb,
    ComponentArchivedError,
    ComponentCycleError,
    ComponentDependencyError,
    ComponentDraftRequiredError,
    ComponentLastConfigError,
    ComponentType,
    ComponentVersionConflictError,
    SessionType,
    current_version_guard_clause,
    current_version_matches,
    project_config_identity,
)
from agno.db.migrations.manager import MigrationManager
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.mcp_oauth import (
    MCP_OAUTH_CLIENTS,
    MCP_OAUTH_CODES,
    MCP_OAUTH_KEYS,
    MCP_OAUTH_REFRESH_TOKENS,
    MCP_OAUTH_TABLE_NAME_ATTRS,
    MCP_OAUTH_TRANSACTIONS,
)
from agno.db.schemas.memory import UserMemory
from agno.db.schemas.service_accounts import (
    resolve_service_account_sort_column,
    validate_service_account_update,
)
from agno.db.sqlite.schemas import get_table_schema_definition
from agno.db.sqlite.utils import (
    apply_sorting,
    bulk_upsert_metrics,
    calculate_date_metrics,
    fetch_all_sessions_data,
    get_dates_to_calculate_metrics_for,
    is_table_available,
    is_valid_table,
)
from agno.db.utils import (
    HISTORY_SKIP_STATUSES,
    build_single_run_row,
    deserialize_run,
    deserialize_session,
    deserialize_session_json_fields,
    deserialize_sessions,
    filter_context_runs,
    json_serializer,
    learning_search_patterns,
    merge_runs_table_with_legacy_blob,
    metrics_starting_date_from_days,
    serialize_session_json_fields,
    table_schema_mismatch_error,
    validate_pagination,
)
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.string import generate_id

try:
    from sqlalchemy import Column, MetaData, String, Table, and_, func, or_, select, text
    from sqlalchemy.dialects import sqlite
    from sqlalchemy.engine import Engine, create_engine
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import scoped_session, sessionmaker
    from sqlalchemy.schema import ForeignKey, Index, UniqueConstraint
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


class SqliteDb(BaseDb):
    def __init__(
        self,
        db_file: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        db_url: Optional[str] = None,
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
        approvals_table: Optional[str] = None,
        auth_tokens_table: Optional[str] = None,
        service_accounts_table: Optional[str] = None,
        mcp_oauth_clients_table: Optional[str] = None,
        mcp_oauth_transactions_table: Optional[str] = None,
        mcp_oauth_codes_table: Optional[str] = None,
        mcp_oauth_refresh_tokens_table: Optional[str] = None,
        mcp_oauth_keys_table: Optional[str] = None,
        id: Optional[str] = None,
    ):
        """
        Interface for interacting with a SQLite database.

        The following order is used to determine the database connection:
            1. Use the db_engine
            2. Use the db_url
            3. Use the db_file
            4. Create a new database in the current directory

        Args:
            db_file (Optional[str]): The database file to connect to.
            db_engine (Optional[Engine]): The SQLAlchemy database engine to use.
            db_url (Optional[str]): The database URL to connect to.
            session_table (Optional[str]): Name of the table to store Agent, Team and Workflow sessions.
            runs_table (Optional[str]): Name of the table to store the runs of each session.
            memory_table (Optional[str]): Name of the table to store user memories.
            metrics_table (Optional[str]): Name of the table to store metrics.
            eval_table (Optional[str]): Name of the table to store evaluation runs data.
            knowledge_table (Optional[str]): Name of the table to store knowledge documents data.
            traces_table (Optional[str]): Name of the table to store run traces.
            spans_table (Optional[str]): Name of the table to store span events.
            versions_table (Optional[str]): Name of the table to store schema versions.
            components_table (Optional[str]): Name of the table to store components.
            component_configs_table (Optional[str]): Name of the table to store component configurations.
            component_links_table (Optional[str]): Name of the table to store component links.
            learnings_table (Optional[str]): Name of the table to store learning records.
            schedules_table (Optional[str]): Name of the table to store cron schedules.
            schedule_runs_table (Optional[str]): Name of the table to store schedule run history.
            mcp_oauth_clients_table (Optional[str]): Name of the table to store MCP OAuth client registrations.
            mcp_oauth_transactions_table (Optional[str]): Name of the table to store MCP OAuth transactions.
            mcp_oauth_codes_table (Optional[str]): Name of the table to store MCP OAuth authorization codes.
            mcp_oauth_refresh_tokens_table (Optional[str]): Name of the table to store MCP OAuth refresh tokens.
            mcp_oauth_keys_table (Optional[str]): Name of the table to store MCP OAuth signing keys.
            id (Optional[str]): ID of the database.

        Raises:
            ValueError: If none of the tables are provided.
        """
        if id is None:
            # Parenthesized on purpose: without them the conditional binds the
            # whole or-chain, db_url/db_file become dead code whenever no engine
            # is passed, and every instance seeds from the literal default -
            # giving physically different databases the same generated id.
            seed = db_url or db_file or (str(db_engine.url) if db_engine else "sqlite:///agno.db")
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
            approvals_table=approvals_table,
            auth_tokens_table=auth_tokens_table,
            service_accounts_table=service_accounts_table,
            mcp_oauth_clients_table=mcp_oauth_clients_table,
            mcp_oauth_transactions_table=mcp_oauth_transactions_table,
            mcp_oauth_codes_table=mcp_oauth_codes_table,
            mcp_oauth_refresh_tokens_table=mcp_oauth_refresh_tokens_table,
            mcp_oauth_keys_table=mcp_oauth_keys_table,
        )

        _engine: Optional[Engine] = db_engine
        if _engine is None:
            if db_url is not None:
                _engine = create_engine(db_url, json_serializer=json_serializer)
            elif db_file is not None:
                db_path = Path(db_file).resolve()
                db_path.parent.mkdir(parents=True, exist_ok=True)
                db_file = str(db_path)
                _engine = create_engine(f"sqlite:///{db_path}", json_serializer=json_serializer)
            else:
                # If none of db_engine, db_url, or db_file are provided, create a db in the current directory
                default_db_path = Path("./agno.db").resolve()
                _engine = create_engine(f"sqlite:///{default_db_path}", json_serializer=json_serializer)
                db_file = str(default_db_path)
                log_debug(f"Created SQLite database: {default_db_path}")

        self.db_engine: Engine = _engine
        self.db_url: Optional[str] = db_url
        self.db_file: Optional[str] = db_file
        self.metadata: MetaData = MetaData()

        # SQLite ignores FOREIGN KEY constraints by default — enable them on
        # every new connection so agno_runs.session_id → sessions.session_id
        # CASCADE actually fires. No-op on non-SQLite dialects.
        from sqlalchemy import event as _sa_event

        @_sa_event.listens_for(self.db_engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, connection_record):  # type: ignore[no-redef]
            try:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys = ON")
                # WAL replaces the default DELETE journal, which creates, fsyncs
                # and deletes a journal file on every commit. The mode persists
                # in the database file, so re-issuing it per connection is an
                # idempotent no-op. synchronous is left at its default (FULL):
                # commits still fsync, durability is unchanged. Where SQLite
                # cannot switch (in-memory databases, filesystems without
                # shared-memory support such as some network mounts) the pragma
                # reports the mode actually in effect — keep whatever it gives
                # back.
                cursor.execute("PRAGMA journal_mode=WAL")
                row = cursor.fetchone()
                mode = row[0] if row else None
                if isinstance(mode, str) and mode.lower() != "wal":
                    log_debug(f"SQLite journal_mode=WAL unavailable, running with journal_mode={mode}")
                cursor.close()
            except Exception:
                # Not SQLite (someone passed a different db_engine) — ignore.
                pass

        # Initialize database session
        self.Session: scoped_session = scoped_session(sessionmaker(bind=self.db_engine))

        # SingletonThreadPool (SQLite's pool for in-memory databases, any URL
        # spelling) gives every thread its own private database, so "this
        # table exists" is not a process-wide fact there. StaticPool (the
        # async in-memory arrangement) shares one connection and caches fine.
        from sqlalchemy.pool import SingletonThreadPool

        if isinstance(self.db_engine.pool, SingletonThreadPool):
            self._table_cache.enabled = False
            log_debug("Table cache: disabled for in-memory SQLite (per-thread private databases)")
        # Zero means never refreshed; get_metrics uses this to refresh lazily, at most once per minute
        self._metrics_refreshed_at: float = 0.0

    # -- Serialization methods --
    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                "db_file": self.db_file,
                "db_url": self.db_url,
                "type": "sqlite",
            }
        )
        return base

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SqliteDb":
        return cls(
            db_file=data.get("db_file"),
            db_url=data.get("db_url"),
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
        """Close database connections and dispose of the connection pool.

        Should be called during application shutdown to properly release
        all database connections.
        """
        if self.db_engine is not None:
            self.db_engine.dispose()

    # -- DB methods --
    def table_exists(self, table_name: str) -> bool:
        """Check if a table with the given name exists in the SQLite database.

        Args:
            table_name: Name of the table to check

        Returns:
            bool: True if the table exists in the database, False otherwise
        """
        with self.Session() as sess:
            return is_table_available(session=sess, table_name=table_name)

    def _create_all_tables(self):
        """Create all tables for the database."""
        tables_to_create = [
            (self.session_table_name, "sessions"),
            (self.runs_table_name, "runs"),
            (self.memory_table_name, "memories"),
            (self.metrics_table_name, "metrics"),
            (self.eval_table_name, "evals"),
            (self.knowledge_table_name, "knowledge"),
            (self.versions_table_name, "versions"),
            (self.components_table_name, "components"),
            (self.component_configs_table_name, "component_configs"),
            (self.component_links_table_name, "component_links"),
            (self.learnings_table_name, "learnings"),
            (self.schedules_table_name, "schedules"),
            (self.schedule_runs_table_name, "schedule_runs"),
            (self.approvals_table_name, "approvals"),
            (self.service_accounts_table_name, "service_accounts"),
            (self.tool_results_table_name, "tool_results"),
        ]

        for table_name, table_type in tables_to_create:
            # Re-verify against the live database (one existence check each), so
            # this call still recreates tables dropped externally - including
            # tables registered only as an FK side effect of another reflection
            if not self.table_exists(table_name):
                self._invalidate_table_cache(table_name)
            self._get_or_create_table(table_name=table_name, table_type=table_type, create_table_if_not_found=True)

    def _create_table(self, table_name: str, table_type: str) -> Table:
        """
        Create a table with the appropriate schema based on the table type.

        Supports:
        - _unique_constraints: [{"name": "...", "columns": [...]}]
        - __primary_key__: ["col1", "col2", ...]
        - __foreign_keys__: [{"columns":[...], "ref_table":"...", "ref_columns":[...]}]
        - column-level foreign_key: "logical_table.column" (resolved via _resolve_* helpers)

        Args:
            table_name (str): Name of the table to create
            table_type (str): Type of table (used to get schema definition)

        Returns:
            Table: SQLAlchemy Table object
        """
        # The runs table declares a FK to sessions — ensure the real sessions
        # Table object is registered in ``self.metadata`` first so SQLAlchemy
        # can resolve the FK reference at ``Table(...)`` construction.
        try:
            from sqlalchemy.schema import ForeignKeyConstraint, PrimaryKeyConstraint

            # Pass table names for foreign key resolution
            table_schema = get_table_schema_definition(
                table_type,
                traces_table_name=self.trace_table_name,
                schedules_table_name=self.schedules_table_name,
                session_table_name=self.session_table_name,
            ).copy()

            # Register FK parent tables on the metadata first, so SQLAlchemy
            # can resolve the FK references at ``Table(...)`` construction.
            # Gated on this dialect's schema actually declaring a foreign key:
            # the dependency map is a cross-dialect superset.
            declares_fk = bool(table_schema.get("__foreign_keys__")) or any(
                isinstance(cfg, dict) and "foreign_key" in cfg for cfg in table_schema.values()
            )
            if declares_fk:
                registered = {t.name for t in self.metadata.tables.values()}
                for ref_type, ref_name in self._fk_dependencies(table_type):
                    if ref_name not in registered:
                        # Under _resolve_lock: resolve directly so the parent is
                        # re-registered even if a stale cache entry exists
                        self._resolve_table(
                            table_name=ref_name,
                            table_type=ref_type,
                            create_table_if_not_found=True,
                        )

            columns: List[Column] = []
            indexes: List[str] = []

            # Extract special schema keys before iterating columns
            schema_unique_constraints = table_schema.pop("_unique_constraints", [])
            schema_primary_key = table_schema.pop("__primary_key__", None)
            schema_foreign_keys = table_schema.pop("__foreign_keys__", [])
            schema_composite_indexes = table_schema.pop("__composite_indexes__", [])
            schema_partial_unique_indexes = table_schema.pop("_partial_unique_indexes", [])

            # Build columns
            for col_name, col_config in table_schema.items():
                column_args = [col_name, col_config["type"]()]
                column_kwargs: Dict[str, Any] = {}

                # Column-level PK only if no composite PK is defined
                if col_config.get("primary_key", False) and schema_primary_key is None:
                    column_kwargs["primary_key"] = True

                if "nullable" in col_config:
                    column_kwargs["nullable"] = col_config["nullable"]

                if "default" in col_config:
                    column_kwargs["default"] = col_config["default"]

                if col_config.get("index", False):
                    indexes.append(col_name)

                if col_config.get("unique", False):
                    column_kwargs["unique"] = True

                # Single-column FK
                if "foreign_key" in col_config:
                    fk_ref = self._resolve_fk_reference(col_config["foreign_key"])
                    fk_kwargs: Dict[str, Any] = {}
                    if "ondelete" in col_config:
                        fk_kwargs["ondelete"] = col_config["ondelete"]
                    column_args.append(ForeignKey(fk_ref, **fk_kwargs))

                columns.append(Column(*column_args, **column_kwargs))  # type: ignore

            # Create the table object
            # In-memory SQLite (cache disabled): every thread has a private
            # database, so re-creation of an already-registered table is
            # legitimate; allow redefinition instead of "already defined"
            already_registered = any(t.name == table_name for t in self.metadata.tables.values())
            table = Table(table_name, self.metadata, *columns, extend_existing=not self._table_cache.enabled)

            # A pre-registered Table (extend_existing path) already carries its
            # constraints and indexes; re-appending duplicates them unboundedly
            attach_constraints = not already_registered

            # Composite PK
            if attach_constraints and schema_primary_key is not None:
                missing = [c for c in schema_primary_key if c not in table.c]
                if missing:
                    raise ValueError(f"Composite PK references missing columns in {table_name}: {missing}")

                pk_constraint_name = f"{table_name}_pkey"
                table.append_constraint(PrimaryKeyConstraint(*schema_primary_key, name=pk_constraint_name))

            # Composite FKs
            for fk_config in schema_foreign_keys if attach_constraints else []:
                fk_columns = fk_config["columns"]
                ref_table_logical = fk_config["ref_table"]
                ref_columns = fk_config["ref_columns"]

                if len(fk_columns) != len(ref_columns):
                    raise ValueError(
                        f"Composite FK in {table_name} has mismatched columns/ref_columns: {fk_columns} vs {ref_columns}"
                    )

                missing = [c for c in fk_columns if c not in table.c]
                if missing:
                    raise ValueError(f"Composite FK references missing columns in {table_name}: {missing}")

                resolved_ref_table = self._resolve_table_name(ref_table_logical)
                fk_constraint_name = f"{table_name}_{'_'.join(fk_columns)}_fkey"

                ref_column_strings = [f"{resolved_ref_table}.{col}" for col in ref_columns]

                table.append_constraint(
                    ForeignKeyConstraint(
                        fk_columns,
                        ref_column_strings,
                        name=fk_constraint_name,
                    )
                )

            # Multi-column unique constraints
            for constraint in schema_unique_constraints if attach_constraints else []:
                constraint_name = f"{table_name}_{constraint['name']}"
                constraint_columns = constraint["columns"]

                missing = [c for c in constraint_columns if c not in table.c]
                if missing:
                    raise ValueError(f"Unique constraint references missing columns in {table_name}: {missing}")

                table.append_constraint(UniqueConstraint(*constraint_columns, name=constraint_name))

            # Indexes
            for idx_col in indexes if attach_constraints else []:
                if idx_col not in table.c:
                    raise ValueError(f"Index references missing column in {table_name}: {idx_col}")
                idx_name = f"idx_{table_name}_{idx_col}"
                Index(idx_name, table.c[idx_col])  # Correct way; do NOT append as constraint

            # Composite indexes
            for idx_config in schema_composite_indexes if attach_constraints else []:
                idx_name = f"idx_{table_name}_{'_'.join(idx_config['columns'])}"
                idx_cols = [table.c[c] for c in idx_config["columns"]]
                Index(idx_name, *idx_cols)

            # Partial unique indexes
            for idx_config in schema_partial_unique_indexes if attach_constraints else []:
                idx_name = f"{table_name}_{idx_config['name']}"
                missing = [c for c in idx_config["columns"] if c not in table.c]
                if missing:
                    raise ValueError(f"Partial unique index references missing columns in {table_name}: {missing}")
                idx_cols = [table.c[c] for c in idx_config["columns"]]
                Index(idx_name, *idx_cols, unique=True, sqlite_where=text(idx_config["where"]))

            # Create table
            table_created = False
            if not self.table_exists(table_name):
                table.create(self.db_engine, checkfirst=True)
                log_debug(f"Successfully created table '{table_name}'")
                table_created = True
            else:
                log_debug(f"Table '{table_name}' already exists, skipping creation")

            # Create indexes (SQLite)
            for idx in table.indexes:
                try:
                    # Check if index already exists
                    with self.Session() as sess:
                        exists_query = text("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = :index_name")
                        exists = sess.execute(exists_query, {"index_name": idx.name}).scalar() is not None
                        if exists:
                            continue

                    idx.create(self.db_engine)
                    log_debug(f"Created index: {idx.name} for table {table_name}")

                except Exception as e:
                    log_warning(f"Error creating index {idx.name}: {str(e)}")

            # Store the schema version for the created table
            if table_name != self.versions_table_name and table_created:
                latest_schema_version = MigrationManager(self).latest_schema_version
                self.upsert_schema_version(table_name=table_name, version=latest_schema_version.public)

            return table

        except Exception as e:
            from traceback import print_exc

            print_exc()
            log_error(f"Could not create table '{table_name}': {str(e)}")
            raise e

    def _resolve_fk_reference(self, fk_ref: str) -> str:
        """
        Resolve a simple foreign key reference to the actual table name.

        Accepts:
        - "logical_table.column"  -> "{resolved_table}.{column}"
        - already-qualified refs  -> returned as-is
        """
        parts = fk_ref.split(".")
        if len(parts) == 2:
            table, column = parts
            resolved_table = self._resolve_table_name(table)
            return f"{resolved_table}.{column}"
        return fk_ref

    def _resolve_table_name(self, logical_name: str) -> str:
        """
        Resolve logical table name to configured table name.
        """
        table_map = {
            "components": self.components_table_name,
            "component_configs": self.component_configs_table_name,
            "component_links": self.component_links_table_name,
            "traces": self.trace_table_name,
            "spans": self.span_table_name,
            "sessions": self.session_table_name,
            "runs": self.runs_table_name,
            "memories": self.memory_table_name,
            "metrics": self.metrics_table_name,
            "evals": self.eval_table_name,
            "knowledge": self.knowledge_table_name,
            "versions": self.versions_table_name,
        }
        return table_map.get(logical_name, logical_name)

    def _get_table(self, table_type: str, create_table_if_not_found: Optional[bool] = False) -> Optional[Table]:
        if table_type == "sessions":
            self.session_table = self._get_or_create_table(
                table_name=self.session_table_name,
                table_type=table_type,
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.session_table

        elif table_type == "runs":
            self.runs_table = self._get_or_create_table(
                table_name=self.runs_table_name,
                table_type="runs",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.runs_table

        elif table_type == "memories":
            self.memory_table = self._get_or_create_table(
                table_name=self.memory_table_name,
                table_type="memories",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.memory_table

        elif table_type == "metrics":
            self.metrics_table = self._get_or_create_table(
                table_name=self.metrics_table_name,
                table_type="metrics",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.metrics_table

        elif table_type == "evals":
            self.eval_table = self._get_or_create_table(
                table_name=self.eval_table_name,
                table_type="evals",
                create_table_if_not_found=create_table_if_not_found,
            )

            return self.eval_table

        elif table_type == "knowledge":
            self.knowledge_table = self._get_or_create_table(
                table_name=self.knowledge_table_name,
                table_type="knowledge",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.knowledge_table

        elif table_type == "traces":
            self.traces_table = self._get_or_create_table(
                table_name=self.trace_table_name,
                table_type="traces",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.traces_table

        elif table_type == "spans":
            # Ensure traces table exists first (spans has FK to traces)
            if create_table_if_not_found:
                self._get_table(table_type="traces", create_table_if_not_found=True)

            self.spans_table = self._get_or_create_table(
                table_name=self.span_table_name,
                table_type="spans",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.spans_table

        elif table_type == "versions":
            self.versions_table = self._get_or_create_table(
                table_name=self.versions_table_name,
                table_type="versions",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.versions_table

        elif table_type == "components":
            self.components_table = self._get_or_create_table(
                table_name=self.components_table_name,
                table_type="components",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.components_table

        elif table_type == "component_configs":
            # Ensure components table exists first (configs references components)
            if create_table_if_not_found:
                self._get_table(table_type="components", create_table_if_not_found=True)

            self.component_configs_table = self._get_or_create_table(
                table_name=self.component_configs_table_name,
                table_type="component_configs",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.component_configs_table

        elif table_type == "component_links":
            # Ensure components and component_configs tables exist first
            if create_table_if_not_found:
                self._get_table(table_type="components", create_table_if_not_found=True)
                self._get_table(table_type="component_configs", create_table_if_not_found=True)

            self.component_links_table = self._get_or_create_table(
                table_name=self.component_links_table_name,
                table_type="component_links",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.component_links_table
        elif table_type == "learnings":
            self.learnings_table = self._get_or_create_table(
                table_name=self.learnings_table_name,
                table_type="learnings",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.learnings_table

        elif table_type == "schedules":
            self.schedules_table = self._get_or_create_table(
                table_name=self.schedules_table_name,
                table_type="schedules",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.schedules_table

        elif table_type == "schedule_runs":
            self.schedule_runs_table = self._get_or_create_table(
                table_name=self.schedule_runs_table_name,
                table_type="schedule_runs",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.schedule_runs_table

        elif table_type == "tool_results":
            self.tool_results_table = self._get_or_create_table(
                table_name=self.tool_results_table_name,
                table_type="tool_results",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.tool_results_table

        elif table_type == "approvals":
            self.approvals_table = self._get_or_create_table(
                table_name=self.approvals_table_name,
                table_type="approvals",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.approvals_table

        elif table_type == "auth_tokens":
            self.auth_tokens_table = self._get_or_create_table(
                table_name=self.auth_tokens_table_name,
                table_type="auth_tokens",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.auth_tokens_table

        elif table_type == "service_accounts":
            self.service_accounts_table = self._get_or_create_table(
                table_name=self.service_accounts_table_name,
                table_type="service_accounts",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.service_accounts_table

        elif table_type in MCP_OAUTH_TABLE_NAME_ATTRS:
            return self._get_or_create_table(
                table_name=getattr(self, MCP_OAUTH_TABLE_NAME_ATTRS[table_type]),
                table_type=table_type,
                create_table_if_not_found=create_table_if_not_found,
            )

        else:
            raise ValueError(f"Unknown table type: '{table_type}'")

    def _resolve_table(
        self,
        table_name: str,
        table_type: str,
        create_table_if_not_found: Optional[bool] = False,
    ) -> Optional[Table]:
        """
        Check if the table exists and is valid, else create it.

        Args:
            table_name (str): Name of the table to get or create
            table_type (str): Type of table (used to get schema definition)

        Returns:
            Table: SQLAlchemy Table object
        """
        with self.Session() as sess, sess.begin():
            table_is_available = is_table_available(session=sess, table_name=table_name)

        if not table_is_available:
            if not create_table_if_not_found:
                return None
            table = self._create_table(table_name=table_name, table_type=table_type)
            self._store_resolved_table(table_type, table_name, table)
            return table

        # SQLite version of table validation (no schema)
        if not is_valid_table(db_engine=self.db_engine, table_name=table_name, table_type=table_type):
            raise table_schema_mismatch_error(table_name, table_type=table_type)

        try:
            table = Table(table_name, self.metadata, autoload_with=self.db_engine)
            self._store_resolved_table(table_type, table_name, table)
            return table

        except Exception as e:
            log_error(f"Error loading existing table {table_name}: {str(e)}")
            raise e

    def get_latest_schema_version(self, table_name: str):
        """Get the latest version of the database schema."""
        table = self._get_table(table_type="versions", create_table_if_not_found=True)
        if table is None:
            return "2.0.0"
        with self.Session() as sess:
            stmt = select(table)
            # Latest version for the given table
            stmt = stmt.where(table.c.table_name == table_name)
            stmt = stmt.order_by(table.c.version.desc()).limit(1)
            result = sess.execute(stmt).fetchone()
            if result is None:
                return "2.0.0"
            version_dict = dict(result._mapping)
            return version_dict.get("version") or "2.0.0"

    def upsert_schema_version(self, table_name: str, version: str) -> None:
        """Upsert the schema version into the database."""
        table = self._get_table(table_type="versions", create_table_if_not_found=True)
        if table is None:
            return
        current_datetime = datetime.now().isoformat()
        with self.Session() as sess, sess.begin():
            stmt = sqlite.insert(table).values(
                table_name=table_name,
                version=version,
                created_at=current_datetime,  # Store as ISO format string
                updated_at=current_datetime,
            )
            # Update version if table_name already exists
            stmt = stmt.on_conflict_do_update(
                index_elements=["table_name"],
                set_=dict(version=version, updated_at=current_datetime),
            )
            sess.execute(stmt)

    def cleanup_legacy_runs_column(self, force: bool = False) -> bool:
        """Drop the legacy ``runs`` column from the sessions table.

        The v3.0.0 migration intentionally leaves the legacy ``runs`` column on
        the sessions table as a backup. Once you have verified the migration
        and taken a backup, call this to reclaim the storage.

        Args:
            force: If True, drop the column even if some sessions still hold
                non-null ``runs`` content (a sign that they were not migrated).
                Defaults to False.

        Returns:
            True if the column was dropped (or its content cleared on older
            SQLite versions that don't support DROP COLUMN), False if there
            was no legacy column to act on.
        """
        with self.Session() as sess, sess.begin():
            columns_info = sess.execute(text(f"PRAGMA table_info({self.session_table_name})")).fetchall()
            existing_columns = {col[1] for col in columns_info}
            if "runs" not in existing_columns:
                log_info(f"{self.session_table_name}.runs column does not exist, nothing to clean up")
                return False

            if not force:
                pending = (
                    sess.execute(
                        text(f"SELECT COUNT(*) FROM {self.session_table_name} WHERE runs IS NOT NULL")
                    ).scalar()
                    or 0
                )
                if pending > 0:
                    raise RuntimeError(
                        f"Refusing to drop {self.session_table_name}.runs: {pending} session(s) still have "
                        "non-null `runs` content. Run MigrationManager(db).up() first, or pass force=True."
                    )

            try:
                sess.execute(text(f"ALTER TABLE {self.session_table_name} DROP COLUMN runs"))
                log_info(f"Dropped legacy runs column from {self.session_table_name}")
            except Exception:
                # SQLite < 3.35 does not support DROP COLUMN; clear the column instead.
                sess.execute(text(f"UPDATE {self.session_table_name} SET runs = NULL"))
                log_info(
                    f"Could not drop runs column from {self.session_table_name} "
                    "(SQLite < 3.35); cleared its content instead."
                )

        self._invalidate_table_cache(self.session_table_name)
        return True

    # -- Run methods --
    def _get_session_runs_data(
        self, sess, runs_table: Table, session_id: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get the raw run_data dicts for the given session, in insertion order.

        When ``limit`` is set, only the most recent ``limit`` context-relevant runs
        are fetched (indexed ``ORDER BY run_index DESC LIMIT``) and returned in
        ascending (chronological) order. "Context-relevant" mirrors the pre-slice
        filtering in ``get_messages``: member sub-runs (``parent_run_id`` set) and
        terminal-skip statuses are excluded in SQL, so the DB-side last-N matches
        the in-memory history window.
        """
        # run_index is the monotonic insertion order (backfilled on write, see
        # upsert_run), so it drives the ordering and the (session_id, run_index)
        # index serves it; created_at/run_id are deterministic tiebreakers.
        if limit is not None:
            stmt = (
                select(runs_table.c.run_data)
                .where(runs_table.c.session_id == session_id)
                .where(runs_table.c.parent_run_id.is_(None))
                .where(or_(runs_table.c.status.is_(None), runs_table.c.status.notin_(HISTORY_SKIP_STATUSES)))
                .order_by(
                    runs_table.c.run_index.desc(),
                    runs_table.c.created_at.desc(),
                    runs_table.c.run_id.desc(),
                )
                .limit(limit)
            )
            rows = [json.loads(row[0]) if isinstance(row[0], str) else row[0] for row in sess.execute(stmt).fetchall()]
            rows.reverse()
            return rows
        stmt = (
            select(runs_table.c.run_data)
            .where(runs_table.c.session_id == session_id)
            .order_by(
                runs_table.c.run_index.asc(),
                runs_table.c.created_at.asc(),
                runs_table.c.run_id.asc(),
            )
        )
        return [json.loads(row[0]) if isinstance(row[0], str) else row[0] for row in sess.execute(stmt).fetchall()]

    def _get_sessions_runs_data(
        self, sess, runs_table: Table, session_ids: List[str]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get the raw run_data dicts for the given sessions, grouped by session_id."""
        if not session_ids:
            return {}
        stmt = (
            select(runs_table.c.session_id, runs_table.c.run_data)
            .where(runs_table.c.session_id.in_(session_ids))
            .order_by(runs_table.c.run_index.asc(), runs_table.c.created_at.asc())
        )
        runs_by_session: Dict[str, List[Dict[str, Any]]] = {}
        for session_id, run_data in sess.execute(stmt).fetchall():
            if isinstance(run_data, str):
                run_data = json.loads(run_data)
            runs_by_session.setdefault(session_id, []).append(run_data)
        return runs_by_session

    def get_run(
        self, run_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[RunOutput, TeamRunOutput, WorkflowRunOutput, Dict[str, Any]]]:
        """Read a single run from the runs table.

        Args:
            run_id (str): The ID of the run to read.
            deserialize (Optional[bool]): Whether to deserialize the run. Defaults to True.

        Returns:
            - When deserialize=True: RunOutput, TeamRunOutput or WorkflowRunOutput object
            - When deserialize=False: Run row dictionary
        """
        try:
            table = self._get_table(table_type="runs")
            if table is None:
                return None

            with self.Session() as sess:
                result = sess.execute(select(table).where(table.c.run_id == run_id)).fetchone()
                if result is None:
                    return None

                run_row = dict(result._mapping)
                if isinstance(run_row.get("run_data"), str):
                    run_row["run_data"] = json.loads(run_row["run_data"])

            if not deserialize:
                return run_row

            return deserialize_run(run_row.get("run_type"), run_row["run_data"])

        except Exception as e:
            log_error(f"Exception reading from runs table: {str(e)}")
            raise e

    def upsert_run(
        self,
        run: Union[RunOutput, TeamRunOutput, WorkflowRunOutput, Dict[str, Any]],
        session_id: str,
        user_id: Optional[str] = None,
        run_index: Optional[int] = None,
    ) -> None:
        """Upsert a single run to the runs table (O(1) operation).

        Optimized for updating existing runs (e.g., status changes in HITL or
        background mode) without re-upserting all runs in the session.

        For new runs, ``run_index`` should be provided or will be read from
        ``run_data``. For updates to existing runs, ``run_index`` is preserved
        from the original insert.

        Args:
            run: The run object or dictionary to upsert.
            session_id: The session ID this run belongs to.
            user_id: Optional user ID to associate with the run.
            run_index: Optional run index for new runs.

        Raises:
            ValueError: If the run has no run_id.
            Exception: If an error occurs during upsert.
        """
        try:
            runs_table = self._get_table(table_type="runs", create_table_if_not_found=True)
            if runs_table is None:
                return

            row = build_single_run_row(
                run=run,
                session_id=session_id,
                user_id=user_id,
                run_index=run_index,
            )

            with self.Session() as sess, sess.begin():
                # Backfill a monotonic run_index when the run arrives without one
                # (e.g. a background/continue save that couldn't resolve its position).
                # A NULL index has no position and breaks ORDER BY run_index.
                if row.get("run_index") is None:
                    # Computed INSIDE the insert statement: SQLite holds the
                    # database write lock for the whole statement, so two
                    # concurrent backfills cannot read the same MAX (the old
                    # two-statement read-then-insert could - a busy-waiting
                    # second writer landed a duplicate index after the first
                    # committed). ON CONFLICT still preserves existing indexes.
                    row["run_index"] = (
                        select(func.coalesce(func.max(runs_table.c.run_index) + 1, 0))
                        .where(runs_table.c.session_id == session_id)
                        .scalar_subquery()
                    )

                stmt = sqlite.insert(runs_table).values(**row)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["run_id"],
                    set_=dict(
                        status=stmt.excluded.status,
                        run_data=stmt.excluded.run_data,
                        user_id=stmt.excluded.user_id,
                        parent_run_id=stmt.excluded.parent_run_id,
                        updated_at=stmt.excluded.updated_at,
                        # Preserve a non-null run_index; only fill it in for a legacy row
                        # that was stored as NULL (COALESCE keeps the existing value if set).
                        run_index=func.coalesce(runs_table.c.run_index, stmt.excluded.run_index),
                    ),
                )
                sess.execute(stmt)

        except Exception as e:
            log_error(f"Exception upserting run to runs table: {str(e)}")
            raise e

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
        """Get all runs matching the given filters.

        Args:
            session_id (Optional[str]): The ID of the session to filter by.
            user_id (Optional[str]): The ID of the user to filter by.
            agent_id (Optional[str]): The ID of the agent to filter by.
            team_id (Optional[str]): The ID of the team to filter by.
            workflow_id (Optional[str]): The ID of the workflow to filter by.
            status (Optional[RunStatus]): The run status to filter by.
            limit (Optional[int]): The maximum number of runs to return.
            page (Optional[int]): The page number to return.
            sort_by (Optional[str]): The field to sort by. Defaults to run_index when filtering by session.
            sort_order (Optional[str]): The sort order.
            deserialize (Optional[bool]): Whether to deserialize the runs. Defaults to True.

        Returns:
            - When deserialize=True: List of run output objects
            - When deserialize=False: Tuple of (run row dictionaries, total count)
        """
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
                    stmt = stmt.where(table.c.user_id == user_id)
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
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset((page - 1) * limit)

                records = sess.execute(stmt).fetchall()
                run_rows = []
                for record in records:
                    run_row = dict(record._mapping)
                    if isinstance(run_row.get("run_data"), str):
                        run_row["run_data"] = json.loads(run_row["run_data"])
                    run_rows.append(run_row)

            if not deserialize:
                return run_rows, total_count

            return [deserialize_run(row.get("run_type"), row["run_data"]) for row in run_rows]

        except Exception as e:
            log_error(f"Exception reading from runs table: {str(e)}")
            raise e

    def _scrub_run_ids_from_legacy_blob(self, run_ids: List[str]) -> None:
        """Remove ``run_ids`` from every session row's legacy ``runs`` JSON column.

        Partial-migration state: v3 migration copied runs into the ``agno_runs``
        table but preserved the legacy embedded blob as a backup. Deleting a run
        row alone leaves the blob intact and ``merge_runs_table_with_legacy_blob``
        resurrects it on the next read. Skip cleanly on a fully-migrated DB
        (no ``runs`` column). Best-effort: a failure here must not roll back
        the primary runs-table delete.
        """
        if not run_ids:
            return
        try:
            import json as _json

            sessions_table = self._get_table(table_type="sessions")
            if sessions_table is None or "runs" not in sessions_table.c:
                return
            wanted = set(run_ids)
            with self.Session() as sess, sess.begin():
                rows = sess.execute(
                    select(sessions_table.c.session_id, sessions_table.c.runs).where(sessions_table.c.runs.isnot(None))
                ).fetchall()
                for sid, runs_raw in rows:
                    if isinstance(runs_raw, str):
                        try:
                            runs_list = _json.loads(runs_raw)
                        except (_json.JSONDecodeError, TypeError):
                            continue
                    else:
                        runs_list = runs_raw
                    if not isinstance(runs_list, list):
                        continue
                    kept = [r for r in runs_list if not (isinstance(r, dict) and r.get("run_id") in wanted)]
                    if len(kept) == len(runs_list):
                        continue
                    sess.execute(
                        sessions_table.update().where(sessions_table.c.session_id == sid).values(runs=_json.dumps(kept))
                    )
        except Exception:
            log_debug("legacy-runs scrub failed; the primary delete still succeeded", exc_info=True)

    def delete_run(self, run_id: str) -> bool:
        """Delete a single run from the runs table.

        Args:
            run_id (str): The ID of the run to delete.

        Returns:
            bool: True if the run was deleted, False otherwise.
        """
        try:
            table = self._get_table(table_type="runs")
            if table is None:
                return False

            with self.Session() as sess, sess.begin():
                result = sess.execute(table.delete().where(table.c.run_id == run_id))
                deleted = result.rowcount > 0

            # Also scrub the legacy blob so the merge helper doesn't resurrect
            # the deleted run on the next read (partial-migration state).
            self._scrub_run_ids_from_legacy_blob([run_id])
            return deleted

        except Exception as e:
            log_error(f"Error deleting run: {str(e)}")
            raise e

    def delete_runs(self, run_ids: List[str]) -> None:
        """Delete all given runs from the runs table.

        Args:
            run_ids (List[str]): The IDs of the runs to delete.
        """
        try:
            table = self._get_table(table_type="runs")
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                result = sess.execute(table.delete().where(table.c.run_id.in_(run_ids)))

            self._scrub_run_ids_from_legacy_blob(list(run_ids))
            log_debug(f"Successfully deleted {result.rowcount} runs")

        except Exception as e:
            log_error(f"Error deleting runs: {str(e)}")
            raise e

    # -- Session methods --

    def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """
        Delete a session from the database.

        Args:
            session_id (str): ID of the session to delete
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = self._get_table(table_type="sessions")
            if table is None:
                return False
            runs_table = self._get_table(table_type="runs")

            with self.Session() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.session_id == session_id)
                if user_id is not None:
                    delete_stmt = delete_stmt.where(table.c.user_id == user_id)
                result = sess.execute(delete_stmt)
                if result.rowcount == 0:
                    log_debug(f"No session found to delete with session_id: {session_id}")
                    return False

                # Also delete the runs belonging to the session
                if runs_table is not None:
                    sess.execute(runs_table.delete().where(runs_table.c.session_id == session_id))

                log_debug(f"Successfully deleted session with session_id: {session_id}")

            # Cascade offloaded tool results after the session delete commits.
            self._cascade_tool_results([session_id])
            return True

        except Exception as e:
            log_error(f"Error deleting session: {str(e)}")
            raise e

    def delete_sessions(self, session_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete all given sessions from the database.
        Can handle multiple session types in the same run.

        Args:
            session_ids (List[str]): The IDs of the sessions to delete.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = self._get_table(table_type="sessions")
            if table is None:
                return
            runs_table = self._get_table(table_type="runs")

            with self.Session() as sess, sess.begin():
                # The ids a user_id-scoped delete is allowed to touch. The
                # cascade below removes stored payloads, which no filter on the
                # sessions table would stop it from doing for another user's
                # session id.
                select_stmt = select(table.c.session_id).where(table.c.session_id.in_(session_ids))
                if user_id is not None:
                    select_stmt = select_stmt.where(table.c.user_id == user_id)
                deletable_ids = [row[0] for row in sess.execute(select_stmt)]
                # Stored payloads are cascaded only for sessions this delete
                # was allowed to remove. An unscoped delete has no other user
                # to protect, so it also cleans up after a session whose row
                # is already gone.
                cascade_ids = session_ids if user_id is None else deletable_ids

                delete_stmt = table.delete().where(table.c.session_id.in_(deletable_ids))
                result = sess.execute(delete_stmt)

                # Also delete the runs belonging to the sessions
                if runs_table is not None:
                    runs_delete_stmt = runs_table.delete().where(runs_table.c.session_id.in_(session_ids))
                    if user_id is not None:
                        runs_delete_stmt = runs_delete_stmt.where(runs_table.c.user_id == user_id)
                    sess.execute(runs_delete_stmt)

            log_debug(f"Successfully deleted {result.rowcount} sessions")

            # Cascade offloaded tool results after the session delete commits.
            self._cascade_tool_results(cascade_ids)

        except Exception as e:
            log_error(f"Error deleting sessions: {str(e)}")
            raise e

    def _cascade_tool_results(self, session_ids: List[str]) -> None:
        """Cascade result offloading on session delete: read the index rows,
        delete their payloads, then the index rows.

        Best-effort and outside the session delete, so a cascade failure can
        never poison or roll back the delete itself. Payloads are removed by
        the exact (namespace, path) of each index row, through the
        filesystems result stores registered on this db, or from the AgentFS
        table at its defaults when no store registered.
        """
        try:
            table = self._get_table(table_type="tool_results")
            if table is None:
                return
            with self.Session() as sess:
                rows = sess.execute(
                    select(table.c.result_id, table.c.namespace, table.c.path).where(
                        table.c.session_id.in_(session_ids)
                    )
                ).fetchall()
            if not rows:
                return
            # Payloads are removed through every filesystem a store on this db
            # registered, and from the default payload table as well: a fresh
            # process has no registrations, and the exact (namespace, path)
            # delete cannot touch anything but these rows. A row whose payload
            # was found nowhere is reported; its bytes live in a filesystem
            # this process cannot reach.
            removed = set()
            filesystems = list(getattr(self, "tool_result_filesystems", []) or [])
            if filesystems:
                from agno.fs import FileSystem

                for _, namespace, path in rows:
                    for fs in filesystems:
                        try:
                            if FileSystem(backend=fs.backend, namespace=str(namespace)).delete(str(path)):
                                removed.add((str(namespace), str(path)))
                        except Exception as e:
                            log_warning(f"Tool-result payload delete failed for {namespace}/{path}: {e}")
            with self.Session() as sess, sess.begin():
                if self._default_payload_table_exists(sess):
                    for _, namespace, path in rows:
                        if (str(namespace), str(path)) in removed:
                            continue
                        result = sess.execute(
                            text(f"DELETE FROM {self._default_payload_table()} WHERE namespace = :ns AND path = :p"),
                            {"ns": str(namespace), "p": str(path)},
                        )
                        if result.rowcount:
                            removed.add((str(namespace), str(path)))
            missing = [
                f"{namespace}/{path}" for _, namespace, path in rows if (str(namespace), str(path)) not in removed
            ]
            if missing:
                log_warning(
                    f"Tool-result cascade removed {len(rows) - len(missing)} of {len(rows)} payloads; "
                    f"{len(missing)} live in a filesystem this process has no store for: {missing[:3]}"
                )
            result_ids = [str(row[0]) for row in rows]
            for start in range(0, len(result_ids), 500):
                with self.Session() as sess, sess.begin():
                    sess.execute(table.delete().where(table.c.result_id.in_(result_ids[start : start + 500])))
        except Exception as e:
            log_warning(f"Tool-result cascade on session delete failed: {e}")

    @staticmethod
    def _default_payload_table() -> str:
        return "agno_fs"

    @staticmethod
    def _default_payload_table_exists(sess: Any) -> bool:
        return (
            sess.execute(text("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'agno_fs'")).first()
            is not None
        )

    # -- Tool Results (result offloading index) --

    def upsert_tool_result(self, row: Dict[str, Any]) -> None:
        table = self._get_table(table_type="tool_results", create_table_if_not_found=True)
        if table is None:
            raise ValueError(f"Could not create table: {self.tool_results_table_name}")
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = sqlite_insert(table).values(**row)
        update_columns = {key: stmt.excluded[key] for key in row.keys() if key != "result_id"}
        stmt = stmt.on_conflict_do_update(index_elements=["result_id"], set_=update_columns)
        with self.Session() as sess, sess.begin():
            sess.execute(stmt)

    def get_tool_result(self, result_id: str) -> Optional[Dict[str, Any]]:
        table = self._get_table(table_type="tool_results")
        if table is None:
            return None
        with self.Session() as sess:
            row = sess.execute(select(table).where(table.c.result_id == result_id)).fetchone()
            return dict(row._mapping) if row is not None else None

    def get_tool_results_for_session(self, session_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        table = self._get_table(table_type="tool_results")
        if table is None:
            return []
        stmt = (
            select(table).where(table.c.session_id == session_id).order_by(table.c.created_at.desc(), table.c.result_id)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        with self.Session() as sess:
            return [dict(row._mapping) for row in sess.execute(stmt).fetchall()]

    def delete_tool_results(self, result_ids: List[str]) -> int:
        if not result_ids:
            return 0
        table = self._get_table(table_type="tool_results")
        if table is None:
            return 0
        with self.Session() as sess, sess.begin():
            result = sess.execute(table.delete().where(table.c.result_id.in_(result_ids)))
        return result.rowcount or 0

    def get_expired_tool_results(self, now: int) -> List[Dict[str, Any]]:
        table = self._get_table(table_type="tool_results")
        if table is None:
            return []
        stmt = select(table).where(table.c.expires_at.is_not(None)).where(table.c.expires_at <= now)
        with self.Session() as sess:
            return [dict(row._mapping) for row in sess.execute(stmt).fetchall()]

    def get_session(
        self,
        session_id: str,
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
        runs_limit: Optional[int] = None,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """
        Read a session from the database.

        Args:
            session_id (str): ID of the session to read.
            session_type (SessionType): Type of session to get.
            user_id (Optional[str]): User ID to filter by. Defaults to None.
            deserialize (Optional[bool]): Whether to serialize the session. Defaults to True.
            runs_limit (Optional[int]): If set, attach only the most recent ``runs_limit``
                runs instead of the full history. For a fully-migrated session this is an
                indexed ``ORDER BY run_index DESC LIMIT`` query; for a session that still
                carries a legacy ``runs`` blob it falls back to a full load + merge, then
                slices, so no history is ever lost.

        Returns:
            Optional[Union[Session, Dict[str, Any]]]:
                - When deserialize=True: Session object
                - When deserialize=False: Session dictionary

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table = self._get_table(table_type="sessions")
            if table is None:
                return None
            runs_table = self._get_table(table_type="runs")

            with self.Session() as sess, sess.begin():
                stmt = select(table).where(table.c.session_id == session_id)

                # Filtering
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)

                result = sess.execute(stmt).fetchone()
                if result is None:
                    return None

                session_raw = deserialize_session_json_fields(dict(result._mapping))

                # Attach the runs stored in the runs table, merged with any runs still
                # sitting in the legacy `runs` column (so partially-migrated sessions
                # don't silently lose history).
                if session_raw is not None:
                    legacy_runs = session_raw.get("runs")
                    if runs_table is not None and runs_limit is not None and not legacy_runs:
                        # Fully migrated: push "most recent N" down to the DB (indexed).
                        session_raw["runs"] = self._get_session_runs_data(
                            sess=sess, runs_table=runs_table, session_id=session_id, limit=runs_limit
                        )
                    elif runs_table is not None:
                        # Full load + merge. Also the un-migrated fallback: the legacy blob
                        # holds the whole history in one column, so "last N" can't be pushed
                        # to SQL — load all, merge, then filter+slice to match the migrated path.
                        runs_data = self._get_session_runs_data(sess=sess, runs_table=runs_table, session_id=session_id)
                        merged = merge_runs_table_with_legacy_blob(runs_data, legacy_runs)
                        if runs_limit is not None:
                            merged = filter_context_runs(merged)[-runs_limit:]
                        session_raw["runs"] = merged
                    elif runs_limit is not None:
                        # No runs table yet (fully un-migrated): filter+slice the legacy blob.
                        merged = merge_runs_table_with_legacy_blob([], legacy_runs)
                        session_raw["runs"] = filter_context_runs(merged)[-runs_limit:]

                if not session_raw or not deserialize:
                    return session_raw

            return deserialize_session(session_type, session_raw)

        except Exception as e:
            log_debug(f"Exception reading from sessions table: {e}")
            raise e

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
        """
        Get all sessions in the given table. Can filter by user_id and entity_id.

        Pass ``include_runs=False`` to skip attaching each session's run history —
        a large, usually-unnecessary read for list views. The runs are untouched
        in storage; a single ``get_session`` still returns them. Defaults to True
        to preserve existing behavior.
        Args:
            session_type (Optional[SessionType]): The type of session to get.
            user_id (Optional[str]): The ID of the user to filter by.
            component_id (Optional[str]): The ID of the agent / workflow to filter by.
            session_name (Optional[str]): The name of the session to filter by.
            start_timestamp (Optional[int]): The start timestamp to filter by.
            end_timestamp (Optional[int]): The end timestamp to filter by.
            limit (Optional[int]): The maximum number of sessions to return. Defaults to None.
            page (Optional[int]): The page number to return. Defaults to None.
            sort_by (Optional[str]): The field to sort by. Defaults to None.
            sort_order (Optional[str]): The sort order. Defaults to None.
            deserialize (Optional[bool]): Whether to serialize the sessions. Defaults to True.
            create_table_if_not_found (Optional[bool]): Whether to create the table if it doesn't exist.

        Returns:
            List[Session]:
                - When deserialize=True: List of Session objects matching the criteria.
                - When deserialize=False: List of Session dictionaries matching the criteria.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        validate_pagination(limit, page)
        try:
            table = self._get_table(table_type="sessions")
            if table is None:
                return [] if deserialize else ([], 0)
            runs_table = self._get_table(table_type="runs")

            with self.Session() as sess, sess.begin():
                stmt = select(table)

                # Filtering
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
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
                    stmt = stmt.where(table.c.session_data.like(f"%{session_name}%"))
                if session_type is not None:
                    stmt = stmt.where(table.c.session_type == session_type.value)

                # Getting total count
                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = sess.execute(count_stmt).scalar() or 0

                # Sorting
                stmt = apply_sorting(stmt, table, sort_by, sort_order)

                # Paginating
                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset((page - 1) * limit)

                records = sess.execute(stmt).fetchall()
                if records is None:
                    return [] if deserialize else ([], 0)

                sessions_raw = [deserialize_session_json_fields(dict(record._mapping)) for record in records]

                # Attach the runs stored in the runs table. If a session has no rows in the
                # runs table, fall back to its legacy `runs` column content, if any.
                if include_runs and runs_table is not None and sessions_raw:
                    runs_by_session = self._get_sessions_runs_data(
                        sess=sess, runs_table=runs_table, session_ids=[s["session_id"] for s in sessions_raw]
                    )
                    for s in sessions_raw:
                        runs_data = runs_by_session.get(s["session_id"], [])
                        s["runs"] = merge_runs_table_with_legacy_blob(runs_data, s.get("runs"))
                elif not include_runs:
                    # List views don't need run history; leave it unattached (storage untouched).
                    for s in sessions_raw:
                        s["runs"] = None

                if not deserialize:
                    return sessions_raw, total_count
                if not sessions_raw:
                    return []

            return deserialize_sessions(session_type, sessions_raw)

        except Exception as e:
            log_debug(f"Exception reading from sessions table: {e}")
            raise e

    def rename_session(
        self,
        session_id: str,
        session_type: Optional[SessionType],
        session_name: str,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """
        Rename a session in the database.

        Args:
            session_id (str): The ID of the session to rename.
            session_type (Optional[SessionType]): The type of session to rename. Defaults to None.
            session_name (str): The new name for the session.
            user_id (Optional[str]): User ID to filter by. Defaults to None.
            deserialize (Optional[bool]): Whether to deserialize the session. Defaults to True.

        Returns:
            Optional[Union[Session, Dict[str, Any]]]:
                - When deserialize=True: Session object
                - When deserialize=False: Session dictionary

        Raises:
            Exception: If an error occurs during renaming.
        """
        try:
            # Get the current session as a deserialized object
            # Get the session record
            session = self.get_session(session_id, session_type, user_id=user_id, deserialize=True)
            if session is None:
                return None

            session = cast(Session, session)
            # Update the session name
            if session.session_data is None:
                session.session_data = {}
            session.session_data["session_name"] = session_name

            # Upsert the updated session back to the database
            return self.upsert_session(session, deserialize=deserialize)

        except Exception as e:
            log_error(f"Exception renaming session: {str(e)}")
            raise e

    def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """
        Insert or update a session in the database.

        Args:
            session (Session): The session data to upsert.
            deserialize (Optional[bool]): Whether to serialize the session. Defaults to True.

        Returns:
            Optional[Session]:
                - When deserialize=True: Session object
                - When deserialize=False: Session dictionary

        Raises:
            Exception: If an error occurs during upserting.
        """
        try:
            table = self._get_table(table_type="sessions", create_table_if_not_found=True)
            if table is None:
                return None

            serialized_session = serialize_session_json_fields(session.to_dict(include_runs=False))

            if isinstance(session, AgentSession):
                values = dict(
                    session_type=SessionType.AGENT.value,
                    agent_id=serialized_session.get("agent_id"),
                    user_id=serialized_session.get("user_id"),
                    agent_data=serialized_session.get("agent_data"),
                    session_data=serialized_session.get("session_data"),
                    summary=serialized_session.get("summary"),
                    metadata=serialized_session.get("metadata"),
                )
            elif isinstance(session, TeamSession):
                values = dict(
                    session_type=SessionType.TEAM.value,
                    team_id=serialized_session.get("team_id"),
                    user_id=serialized_session.get("user_id"),
                    team_data=serialized_session.get("team_data"),
                    session_data=serialized_session.get("session_data"),
                    summary=serialized_session.get("summary"),
                    metadata=serialized_session.get("metadata"),
                )
            else:
                values = dict(
                    session_type=SessionType.WORKFLOW.value,
                    workflow_id=serialized_session.get("workflow_id"),
                    user_id=serialized_session.get("user_id"),
                    workflow_data=serialized_session.get("workflow_data"),
                    session_data=serialized_session.get("session_data"),
                    summary=serialized_session.get("summary"),
                    metadata=serialized_session.get("metadata"),
                )

            update_values = {k: v for k, v in values.items() if k != "session_type"}
            # The legacy `runs` column is intentionally left untouched here. Runs now
            # live in the runs table; the legacy column stays as a frozen backup and is
            # only reclaimed by the explicit cleanup_legacy_runs_column() helper. Nulling
            # it on write would lose history for sessions not yet migrated to the runs table.

            with self.Session() as sess, sess.begin():
                stmt = sqlite.insert(table).values(
                    session_id=serialized_session.get("session_id"),
                    created_at=serialized_session.get("created_at") or int(time.time()),
                    updated_at=serialized_session.get("created_at") or int(time.time()),
                    **values,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["session_id"],
                    set_=dict(updated_at=int(time.time()), **update_values),
                    where=(table.c.user_id == serialized_session.get("user_id")) | (table.c.user_id.is_(None)),
                )
                stmt = stmt.returning(*table.columns)  # type: ignore
                result = sess.execute(stmt)
                row = result.fetchone()
                if row is None:
                    return None
                session_raw = deserialize_session_json_fields(dict(row._mapping))

            if not deserialize:
                session_raw["runs"] = [run if isinstance(run, dict) else run.to_dict() for run in session.runs or []]
                return session_raw

            session_raw.pop("runs", None)
            upserted_session = deserialize_session(None, session_raw)
            upserted_session.runs = session.runs  # type: ignore[union-attr]
            return upserted_session

        except Exception as e:
            log_warning(f"Exception upserting into table: {str(e)}")
            raise e

    def upsert_sessions(
        self,
        sessions: List[Session],
        deserialize: Optional[bool] = True,
        preserve_updated_at: bool = False,
    ) -> List[Union[Session, Dict[str, Any]]]:
        """
        Bulk upsert multiple sessions for improved performance on large datasets.

        Args:
            sessions (List[Session]): List of sessions to upsert.
            deserialize (Optional[bool]): Whether to deserialize the sessions. Defaults to True.
            preserve_updated_at (bool): If True, preserve the updated_at from the session object.

        Returns:
            List[Union[Session, Dict[str, Any]]]: List of upserted sessions.

        Raises:
            Exception: If an error occurs during bulk upsert.
        """
        if not sessions:
            return []

        try:
            table = self._get_table(table_type="sessions", create_table_if_not_found=True)
            if table is None:
                log_info("Sessions table not available, falling back to individual upserts")
                return [
                    result
                    for session in sessions
                    if session is not None
                    for result in [self.upsert_session(session, deserialize=deserialize)]
                    if result is not None
                ]

            # Group sessions by type for batch processing
            agent_sessions = []
            team_sessions = []
            workflow_sessions = []

            for session in sessions:
                if isinstance(session, AgentSession):
                    agent_sessions.append(session)
                elif isinstance(session, TeamSession):
                    team_sessions.append(session)
                elif isinstance(session, WorkflowSession):
                    workflow_sessions.append(session)

            sessions_by_id: Dict[str, Session] = {s.session_id: s for s in sessions}

            def _attach_runs(session_dict: Dict[str, Any]) -> Dict[str, Any]:
                original_session = sessions_by_id.get(session_dict.get("session_id"))  # type: ignore[arg-type]
                session_dict["runs"] = [
                    run if isinstance(run, dict) else run.to_dict()
                    for run in (original_session.runs if original_session else None) or []
                ]
                return session_dict

            results: List[Union[Session, Dict[str, Any]]] = []

            with self.Session() as sess, sess.begin():
                # Bulk upsert agent sessions
                if agent_sessions:
                    agent_data = []
                    for session in agent_sessions:
                        serialized_session = serialize_session_json_fields(session.to_dict(include_runs=False))
                        # Use preserved updated_at if flag is set and value exists, otherwise use current time
                        updated_at = serialized_session.get("updated_at") if preserve_updated_at else int(time.time())
                        agent_data.append(
                            {
                                "session_id": serialized_session.get("session_id"),
                                "session_type": SessionType.AGENT.value,
                                "agent_id": serialized_session.get("agent_id"),
                                "user_id": serialized_session.get("user_id"),
                                "agent_data": serialized_session.get("agent_data"),
                                "session_data": serialized_session.get("session_data"),
                                "metadata": serialized_session.get("metadata"),
                                "summary": serialized_session.get("summary"),
                                "created_at": serialized_session.get("created_at"),
                                "updated_at": updated_at,
                            }
                        )

                    if agent_data:
                        stmt = sqlite.insert(table)
                        stmt = stmt.on_conflict_do_update(
                            index_elements=["session_id"],
                            set_=dict(
                                agent_id=stmt.excluded.agent_id,
                                user_id=stmt.excluded.user_id,
                                agent_data=stmt.excluded.agent_data,
                                session_data=stmt.excluded.session_data,
                                metadata=stmt.excluded.metadata,
                                summary=stmt.excluded.summary,
                                updated_at=stmt.excluded.updated_at,
                            ),
                        )
                        sess.execute(stmt, agent_data)

                        # Fetch the results for agent sessions
                        agent_ids = [session.session_id for session in agent_sessions]
                        select_stmt = select(table).where(table.c.session_id.in_(agent_ids))
                        result = sess.execute(select_stmt).fetchall()

                        for row in result:
                            session_dict = _attach_runs(deserialize_session_json_fields(dict(row._mapping)))
                            if deserialize:
                                deserialized_agent_session = AgentSession.from_dict(session_dict)
                                if deserialized_agent_session is None:
                                    continue
                                results.append(deserialized_agent_session)
                            else:
                                results.append(session_dict)

                # Bulk upsert team sessions
                if team_sessions:
                    team_data = []
                    for session in team_sessions:
                        serialized_session = serialize_session_json_fields(session.to_dict(include_runs=False))
                        # Use preserved updated_at if flag is set and value exists, otherwise use current time
                        updated_at = serialized_session.get("updated_at") if preserve_updated_at else int(time.time())
                        team_data.append(
                            {
                                "session_id": serialized_session.get("session_id"),
                                "session_type": SessionType.TEAM.value,
                                "team_id": serialized_session.get("team_id"),
                                "user_id": serialized_session.get("user_id"),
                                "summary": serialized_session.get("summary"),
                                "created_at": serialized_session.get("created_at"),
                                "updated_at": updated_at,
                                "team_data": serialized_session.get("team_data"),
                                "session_data": serialized_session.get("session_data"),
                                "metadata": serialized_session.get("metadata"),
                            }
                        )

                    if team_data:
                        stmt = sqlite.insert(table)
                        stmt = stmt.on_conflict_do_update(
                            index_elements=["session_id"],
                            set_=dict(
                                team_id=stmt.excluded.team_id,
                                user_id=stmt.excluded.user_id,
                                team_data=stmt.excluded.team_data,
                                session_data=stmt.excluded.session_data,
                                metadata=stmt.excluded.metadata,
                                summary=stmt.excluded.summary,
                                updated_at=stmt.excluded.updated_at,
                            ),
                        )
                        sess.execute(stmt, team_data)

                        # Fetch the results for team sessions
                        team_ids = [session.session_id for session in team_sessions]
                        select_stmt = select(table).where(table.c.session_id.in_(team_ids))
                        result = sess.execute(select_stmt).fetchall()

                        for row in result:
                            session_dict = _attach_runs(deserialize_session_json_fields(dict(row._mapping)))
                            if deserialize:
                                deserialized_team_session = TeamSession.from_dict(session_dict)
                                if deserialized_team_session is None:
                                    continue
                                results.append(deserialized_team_session)
                            else:
                                results.append(session_dict)

                # Bulk upsert workflow sessions
                if workflow_sessions:
                    workflow_data = []
                    for session in workflow_sessions:
                        serialized_session = serialize_session_json_fields(session.to_dict(include_runs=False))
                        # Use preserved updated_at if flag is set and value exists, otherwise use current time
                        updated_at = serialized_session.get("updated_at") if preserve_updated_at else int(time.time())
                        workflow_data.append(
                            {
                                "session_id": serialized_session.get("session_id"),
                                "session_type": SessionType.WORKFLOW.value,
                                "workflow_id": serialized_session.get("workflow_id"),
                                "user_id": serialized_session.get("user_id"),
                                "summary": serialized_session.get("summary"),
                                "created_at": serialized_session.get("created_at"),
                                "updated_at": updated_at,
                                "workflow_data": serialized_session.get("workflow_data"),
                                "session_data": serialized_session.get("session_data"),
                                "metadata": serialized_session.get("metadata"),
                            }
                        )

                    if workflow_data:
                        stmt = sqlite.insert(table)
                        stmt = stmt.on_conflict_do_update(
                            index_elements=["session_id"],
                            set_=dict(
                                workflow_id=stmt.excluded.workflow_id,
                                user_id=stmt.excluded.user_id,
                                workflow_data=stmt.excluded.workflow_data,
                                session_data=stmt.excluded.session_data,
                                metadata=stmt.excluded.metadata,
                                summary=stmt.excluded.summary,
                                updated_at=stmt.excluded.updated_at,
                            ),
                        )
                        sess.execute(stmt, workflow_data)

                        # Fetch the results for workflow sessions
                        workflow_ids = [session.session_id for session in workflow_sessions]
                        select_stmt = select(table).where(table.c.session_id.in_(workflow_ids))
                        result = sess.execute(select_stmt).fetchall()

                        for row in result:
                            session_dict = _attach_runs(deserialize_session_json_fields(dict(row._mapping)))
                            if deserialize:
                                deserialized_workflow_session = WorkflowSession.from_dict(session_dict)
                                if deserialized_workflow_session is None:
                                    continue
                                results.append(deserialized_workflow_session)
                            else:
                                results.append(session_dict)

            return results

        except Exception as e:
            log_error(f"Exception during bulk session upsert, falling back to individual upserts: {str(e)}")
            # Fallback to individual upserts
            return [
                result
                for session in sessions
                if session is not None
                for result in [self.upsert_session(session, deserialize=deserialize)]
                if result is not None
            ]

    # -- Memory methods --

    def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None):
        """Delete a user memory from the database.

        Args:
            memory_id (str): The ID of the memory to delete.
            user_id (Optional[str]): The user ID to filter by. Defaults to None.

        Returns:
            bool: True if deletion was successful, False otherwise.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = self._get_table(table_type="memories")
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.memory_id == memory_id)
                if user_id is not None:
                    delete_stmt = delete_stmt.where(table.c.user_id == user_id)
                result = sess.execute(delete_stmt)

                success = result.rowcount > 0
                if success:
                    log_debug(f"Successfully deleted user memory id: {memory_id}")
                else:
                    log_debug(f"No user memory found with id: {memory_id}")

        except Exception as e:
            log_error(f"Error deleting user memory: {str(e)}")
            raise e

    def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete user memories from the database.

        Args:
            memory_ids (List[str]): The IDs of the memories to delete.
            user_id (Optional[str]): The user ID to filter by. Defaults to None.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = self._get_table(table_type="memories")
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.memory_id.in_(memory_ids))
                if user_id is not None:
                    delete_stmt = delete_stmt.where(table.c.user_id == user_id)
                result = sess.execute(delete_stmt)
                if result.rowcount == 0:
                    log_debug(f"No user memories found with ids: {memory_ids}")

        except Exception as e:
            log_error(f"Error deleting user memories: {str(e)}")
            raise e

    def get_all_memory_topics(self, user_id: Optional[str] = None) -> List[str]:
        """Get all memory topics from the database.

        Args:
            user_id (Optional[str]): The ID of the user to filter by.

        Returns:
            List[str]: List of memory topics.
        """
        try:
            table = self._get_table(table_type="memories")
            if table is None:
                return []

            with self.Session() as sess, sess.begin():
                stmt = select(table.c.topics).where(table.c.topics.is_not(None))
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                rows = sess.execute(stmt).fetchall()

                topics_set: set = set()
                for row in rows:
                    raw = row[0]
                    if not raw:
                        continue
                    if isinstance(raw, str):
                        try:
                            raw = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                    if isinstance(raw, list):
                        topics_set.update(raw)
                return list(topics_set)

        except Exception as e:
            log_debug(f"Exception reading from memory table: {e}")
            raise e

    def get_user_memory(
        self,
        memory_id: str,
        deserialize: Optional[bool] = True,
        user_id: Optional[str] = None,
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Get a memory from the database.

        Args:
            memory_id (str): The ID of the memory to get.
            deserialize (Optional[bool]): Whether to serialize the memory. Defaults to True.
            user_id (Optional[str]): The user ID to filter by. Defaults to None.

        Returns:
            Optional[Union[UserMemory, Dict[str, Any]]]:
                - When deserialize=True: UserMemory object
                - When deserialize=False: Memory dictionary

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table = self._get_table(table_type="memories")
            if table is None:
                return None

            with self.Session() as sess, sess.begin():
                stmt = select(table).where(table.c.memory_id == memory_id)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                result = sess.execute(stmt).fetchone()
                if result is None:
                    return None

                memory_raw = dict(result._mapping)
                if not memory_raw or not deserialize:
                    return memory_raw

            return UserMemory.from_dict(memory_raw)

        except Exception as e:
            log_debug(f"Exception reading from memorytable: {e}")
            raise e

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
        """Get all memories from the database as UserMemory objects.

        Args:
            user_id (Optional[str]): The ID of the user to filter by.
            agent_id (Optional[str]): The ID of the agent to filter by.
            team_id (Optional[str]): The ID of the team to filter by.
            topics (Optional[List[str]]): The topics to filter by.
            search_content (Optional[str]): The content to search for.
            limit (Optional[int]): The maximum number of memories to return.
            page (Optional[int]): The page number.
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by.
            deserialize (Optional[bool]): Whether to serialize the memories. Defaults to True.


        Returns:
            Union[List[UserMemory], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of UserMemory objects
                - When deserialize=False: List of UserMemory dictionaries and total count

        Raises:
            Exception: If an error occurs during retrieval.
        """
        validate_pagination(limit, page)
        try:
            table = self._get_table(table_type="memories")
            if table is None:
                return [] if deserialize else ([], 0)

            with self.Session() as sess, sess.begin():
                stmt = select(table)

                # Filtering
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                if agent_id is not None:
                    stmt = stmt.where(table.c.agent_id == agent_id)
                if team_id is not None:
                    stmt = stmt.where(table.c.team_id == team_id)
                if topics is not None:
                    for topic in topics:
                        stmt = stmt.where(func.cast(table.c.topics, String).like(f'%"{topic}"%'))
                if search_content is not None:
                    stmt = stmt.where(table.c.memory.ilike(f"%{search_content}%"))

                # Get total count after applying filtering
                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = sess.execute(count_stmt).scalar()

                # Sorting
                stmt = apply_sorting(stmt, table, sort_by, sort_order)
                # Paginating
                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset((page - 1) * limit)

                result = sess.execute(stmt).fetchall()
                if not result:
                    return [] if deserialize else ([], 0)

                memories_raw = [record._mapping for record in result]

                if not deserialize:
                    return memories_raw, total_count

            return [UserMemory.from_dict(record) for record in memories_raw]

        except Exception as e:
            log_error(f"Error reading from memory table: {str(e)}")
            raise e

    def get_user_memory_stats(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get user memories stats.

        Args:
            limit (Optional[int]): The maximum number of user stats to return.
            page (Optional[int]): The page number.
            user_id (Optional[str]): User ID for filtering.

        Returns:
            Tuple[List[Dict[str, Any]], int]: A list of dictionaries containing user stats and total count.

        Example:
        (
            [
                {
                    "user_id": "123",
                    "total_memories": 10,
                    "last_memory_updated_at": 1714560000,
                },
            ],
            total_count: 1,
        )
        """
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
                    stmt = stmt.where(table.c.user_id == user_id)
                else:
                    stmt = stmt.where(table.c.user_id.is_not(None))
                stmt = stmt.group_by(table.c.user_id)
                stmt = stmt.order_by(func.max(table.c.updated_at).desc())

                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = sess.execute(count_stmt).scalar() or 0

                # Pagination
                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset((page - 1) * limit)

                result = sess.execute(stmt).fetchall()
                if not result:
                    return [], 0

                return [
                    {
                        "user_id": record.user_id,  # type: ignore
                        "total_memories": record.total_memories,
                        "last_memory_updated_at": record.last_memory_updated_at,
                    }
                    for record in result
                ], total_count

        except Exception as e:
            log_error(f"Error getting user memory stats: {str(e)}")
            raise e

    def upsert_user_memory(
        self, memory: UserMemory, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Upsert a user memory in the database.

        Args:
            memory (UserMemory): The user memory to upsert.
            deserialize (Optional[bool]): Whether to serialize the memory. Defaults to True.

        Returns:
            Optional[Union[UserMemory, Dict[str, Any]]]:
                - When deserialize=True: UserMemory object
                - When deserialize=False: UserMemory dictionary

        Raises:
            Exception: If an error occurs during upsert.
        """
        try:
            table = self._get_table(table_type="memories", create_table_if_not_found=True)
            if table is None:
                return None

            if memory.memory_id is None:
                memory.memory_id = str(uuid4())

            current_time = int(time.time())

            with self.Session() as sess, sess.begin():
                stmt = sqlite.insert(table).values(
                    user_id=memory.user_id,
                    agent_id=memory.agent_id,
                    team_id=memory.team_id,
                    memory_id=memory.memory_id,
                    memory=memory.memory,
                    topics=memory.topics,
                    input=memory.input,
                    feedback=memory.feedback,
                    created_at=memory.created_at,
                    updated_at=memory.created_at,
                )
                stmt = stmt.on_conflict_do_update(  # type: ignore
                    index_elements=["memory_id"],
                    set_=dict(
                        memory=memory.memory,
                        topics=memory.topics,
                        input=memory.input,
                        agent_id=memory.agent_id,
                        team_id=memory.team_id,
                        feedback=memory.feedback,
                        updated_at=current_time,
                        # Preserve created_at on update - don't overwrite existing value
                        created_at=table.c.created_at,
                    ),
                ).returning(table)

                result = sess.execute(stmt)
                row = result.fetchone()

                if row is None:
                    return None

            memory_raw = row._mapping
            if not memory_raw or not deserialize:
                return memory_raw

            return UserMemory.from_dict(memory_raw)

        except Exception as e:
            log_error(f"Error upserting user memory: {str(e)}")
            raise e

    def upsert_memories(
        self,
        memories: List[UserMemory],
        deserialize: Optional[bool] = True,
        preserve_updated_at: bool = False,
    ) -> List[Union[UserMemory, Dict[str, Any]]]:
        """
        Bulk upsert multiple user memories for improved performance on large datasets.

        Args:
            memories (List[UserMemory]): List of memories to upsert.
            deserialize (Optional[bool]): Whether to deserialize the memories. Defaults to True.

        Returns:
            List[Union[UserMemory, Dict[str, Any]]]: List of upserted memories.

        Raises:
            Exception: If an error occurs during bulk upsert.
        """
        if not memories:
            return []

        try:
            table = self._get_table(table_type="memories", create_table_if_not_found=True)
            if table is None:
                log_info("Memories table not available, falling back to individual upserts")
                return [
                    result
                    for memory in memories
                    if memory is not None
                    for result in [self.upsert_user_memory(memory, deserialize=deserialize)]
                    if result is not None
                ]
            # Prepare bulk data
            bulk_data = []
            current_time = int(time.time())

            for memory in memories:
                if memory.memory_id is None:
                    memory.memory_id = str(uuid4())

                # Use preserved updated_at if flag is set and value exists, otherwise use current time
                updated_at = memory.updated_at if preserve_updated_at else current_time

                bulk_data.append(
                    {
                        "user_id": memory.user_id,
                        "agent_id": memory.agent_id,
                        "team_id": memory.team_id,
                        "memory_id": memory.memory_id,
                        "memory": memory.memory,
                        "topics": memory.topics,
                        "input": memory.input,
                        "feedback": memory.feedback,
                        "created_at": memory.created_at,
                        "updated_at": updated_at,
                    }
                )

            results: List[Union[UserMemory, Dict[str, Any]]] = []

            with self.Session() as sess, sess.begin():
                # Bulk upsert memories using SQLite ON CONFLICT DO UPDATE
                stmt = sqlite.insert(table)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["memory_id"],
                    set_=dict(
                        memory=stmt.excluded.memory,
                        topics=stmt.excluded.topics,
                        input=stmt.excluded.input,
                        agent_id=stmt.excluded.agent_id,
                        team_id=stmt.excluded.team_id,
                        feedback=stmt.excluded.feedback,
                        updated_at=stmt.excluded.updated_at,
                        # Preserve created_at on update
                        created_at=table.c.created_at,
                    ),
                )
                sess.execute(stmt, bulk_data)

                # Fetch results
                memory_ids = [memory.memory_id for memory in memories if memory.memory_id]
                select_stmt = select(table).where(table.c.memory_id.in_(memory_ids))
                result = sess.execute(select_stmt).fetchall()

                for row in result:
                    memory_dict = dict(row._mapping)
                    if deserialize:
                        results.append(UserMemory.from_dict(memory_dict))
                    else:
                        results.append(memory_dict)

            return results

        except Exception as e:
            log_error(f"Exception during bulk memory upsert, falling back to individual upserts: {str(e)}")

            # Fallback to individual upserts
            return [
                result
                for memory in memories
                if memory is not None
                for result in [self.upsert_user_memory(memory, deserialize=deserialize)]
                if result is not None
            ]

    def clear_memories(self) -> None:
        """Delete all memories from the database.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = self._get_table(table_type="memories")
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                sess.execute(table.delete())

        except Exception as e:
            from agno.utils.log import log_warning

            log_warning(f"Exception deleting all memories: {str(e)}")
            raise e

    # -- Metrics methods --

    def _get_all_sessions_for_metrics_calculation(
        self, start_timestamp: Optional[int] = None, end_timestamp: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all sessions of all types (agent, team, workflow) as raw dictionaries.

         Args:
            start_timestamp (Optional[int]): The start timestamp to filter by. Defaults to None.
            end_timestamp (Optional[int]): The end timestamp to filter by. Defaults to None.

        Returns:
            List[Dict[str, Any]]: List of session dictionaries with session_type field.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table = self._get_table(table_type="sessions")
            if table is None:
                return []
            runs_table = self._get_table(table_type="runs")

            columns = [
                table.c.session_id,
                table.c.user_id,
                table.c.session_data,
                table.c.created_at,
                table.c.session_type,
            ]
            # Include the legacy runs column if it still exists, to count not yet migrated runs
            if "runs" in table.c:
                columns.append(table.c.runs)

            stmt = select(*columns)

            if start_timestamp is not None:
                stmt = stmt.where(table.c.created_at >= start_timestamp)
            if end_timestamp is not None:
                stmt = stmt.where(table.c.created_at <= end_timestamp)

            with self.Session() as sess:
                result = sess.execute(stmt).fetchall()
                sessions = [dict(record._mapping) for record in result]

                # Attach lightweight run info (model and provider) from the runs table
                if runs_table is not None and sessions:
                    session_ids = [s["session_id"] for s in sessions]
                    runs_stmt = select(
                        runs_table.c.session_id,
                        func.json_extract(runs_table.c.run_data, "$.model").label("model"),
                        func.json_extract(runs_table.c.run_data, "$.model_provider").label("model_provider"),
                    ).where(runs_table.c.session_id.in_(session_ids))

                    runs_by_session: Dict[str, List[Dict[str, Any]]] = {}
                    for session_id, model, model_provider in sess.execute(runs_stmt).fetchall():
                        runs_by_session.setdefault(session_id, []).append(
                            {"model": model, "model_provider": model_provider}
                        )

                    for s in sessions:
                        runs_data = runs_by_session.get(s["session_id"], [])
                        if runs_data or not s.get("runs"):
                            s["runs"] = runs_data

                return sessions

        except Exception as e:
            log_error(f"Error reading from sessions table: {str(e)}")
            raise e

    def _get_metrics_calculation_starting_date(self, table: Table) -> Optional[date]:
        """Get the first date for which metrics calculation is needed:

        1. If there are metrics records, return the date of the first day without a complete metrics record.
        2. If there are no metrics records, return the date of the first recorded session.
        3. If there are no metrics records and no sessions records, return None.

        Args:
            table (Table): The table to get the starting date for.

        Returns:
            Optional[date]: The starting date for which metrics calculation is needed.
        """
        with self.Session() as sess:
            # resume at the earliest incomplete day after the latest completed one, otherwise the
            # day after that one: a day holding a completed row was rebuilt after it ended, so an
            # incomplete row sharing it belongs to an owner whose sessions have gone and can never
            # be rebuilt
            latest_completed = sess.execute(select(func.max(table.c.date)).where(table.c.completed.is_(True))).scalar()

            incomplete_stmt = select(func.min(table.c.date)).where(table.c.completed.is_(False))
            if latest_completed is not None:
                incomplete_stmt = incomplete_stmt.where(table.c.date > latest_completed)
            earliest_incomplete = sess.execute(incomplete_stmt).scalar()

            starting_date = metrics_starting_date_from_days(latest_completed, earliest_incomplete)
            if starting_date is not None:
                return starting_date

        # 2. No metrics records. Return the date of the first recorded session.
        first_session, _ = self.get_sessions(sort_by="created_at", sort_order="asc", limit=1, deserialize=False)
        first_session_date = first_session[0]["created_at"] if first_session else None  # type: ignore

        # 3. No metrics records and no sessions records. Return None.
        if not first_session_date:
            return None

        return datetime.fromtimestamp(first_session_date, tz=timezone.utc).date()

    def calculate_metrics(self) -> Optional[list[dict]]:
        """Calculate metrics for all dates without complete metrics.

        Returns:
            Optional[list[dict]]: The calculated metrics.

        Raises:
            Exception: If an error occurs during metrics calculation.
        """
        try:
            # Stamp first so failed runs are throttled too instead of retried on every read
            self._metrics_refreshed_at = time.time()

            table = self._get_table(table_type="metrics", create_table_if_not_found=True)
            if table is None:
                return None

            starting_date = self._get_metrics_calculation_starting_date(table)
            if starting_date is None:
                log_info("No session data found. Won't calculate metrics.")
                return None

            dates_to_process = get_dates_to_calculate_metrics_for(starting_date)
            if not dates_to_process:
                log_info("Metrics already calculated for all relevant dates.")
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
                sessions=sessions,
                dates_to_process=dates_to_process,
                start_timestamp=start_timestamp,
            )
            if not all_sessions_data:
                log_info("No new session data found. Won't calculate metrics.")
                return None

            results = []
            metrics_records = []

            for date_to_process in dates_to_process:
                date_key = date_to_process.isoformat()
                sessions_for_date = all_sessions_data.get(date_key, {})

                # Skip dates with no sessions
                if not any(len(sessions) > 0 for sessions in sessions_for_date.values()):
                    continue

                # One record per user_id, plus the empty-string bucket for unowned sessions
                metrics_records.extend(calculate_date_metrics(date_to_process, sessions_for_date))

            if metrics_records:
                with self.Session() as sess, sess.begin():
                    results = bulk_upsert_metrics(session=sess, table=table, metrics_records=metrics_records)

            log_debug("Updated metrics calculations")

            return results

        except Exception as e:
            log_error(f"Error refreshing metrics: {str(e)}")
            raise e

    def get_metrics(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[dict], Optional[int]]:
        """Get all metrics matching the given date range.

        Metrics are refreshed lazily, at most once per minute per process, so results
        stay current even on deployments where nothing calls the refresh endpoint.

        Args:
            starting_date (Optional[date]): The starting date to filter metrics by.
            ending_date (Optional[date]): The ending date to filter metrics by.
            user_id (Optional[str]): Return only this user's bucket. ``None`` returns every
                bucket, including the empty-string unowned one.

        Returns:
            Tuple[List[dict], Optional[int]]: A tuple containing the metrics and the timestamp of the latest update.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            # Refresh at most once per minute per process: recalculating the current
            # day scans all of today's sessions, too costly for every read.
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
                    stmt = stmt.where(table.c.user_id == user_id)
                result = sess.execute(stmt).fetchall()
                if not result:
                    return [], None

                # Get the latest updated_at, scoped to the same user filter
                latest_stmt = select(func.max(table.c.updated_at))
                if user_id is not None:
                    latest_stmt = latest_stmt.where(table.c.user_id == user_id)
                latest_updated_at = sess.execute(latest_stmt).scalar()

            # Map the sentinel empty-string user_id back to None for API consumers
            rows: List[dict] = []
            for row in result:
                row_dict = dict(row._mapping)
                if row_dict.get("user_id") == "":
                    row_dict["user_id"] = None
                rows.append(row_dict)
            return rows, latest_updated_at

        except Exception as e:
            log_error(f"Error getting metrics: {str(e)}")
            raise e

    # -- Knowledge methods --
    # Reads also match unowned (shared) rows; deletes are strict to the owner. A ``None``
    # user_id drops the predicate entirely.

    def delete_knowledge_content(self, id: str, user_id: Optional[str] = None):
        """Delete a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to delete.
            user_id (Optional[str]): When set, only delete the row if it is owned by this user.

        Raises:
            Exception: If an error occurs during deletion.
        """
        table = self._get_table(table_type="knowledge")
        if table is None:
            return

        try:
            with self.Session() as sess, sess.begin():
                stmt = table.delete().where(table.c.id == id)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                sess.execute(stmt)

        except Exception as e:
            log_error(f"Error deleting knowledge content: {str(e)}")
            raise e

    def get_knowledge_content(self, id: str, user_id: Optional[str] = None) -> Optional[KnowledgeRow]:
        """Get a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to get.
            user_id (Optional[str]): When set, match rows owned by this user or unowned rows.

        Returns:
            Optional[KnowledgeRow]: The knowledge row, or None if it doesn't exist.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        table = self._get_table(table_type="knowledge")
        if table is None:
            return None

        try:
            with self.Session() as sess, sess.begin():
                stmt = select(table).where(table.c.id == id)
                if user_id is not None:
                    stmt = stmt.where(or_(table.c.user_id == user_id, table.c.user_id.is_(None)))
                result = sess.execute(stmt).fetchone()
                if result is None:
                    return None

                return KnowledgeRow.model_validate(result._mapping)

        except Exception as e:
            log_error(f"Error getting knowledge content: {str(e)}")
            raise e

    def get_knowledge_contents(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        linked_to: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[KnowledgeRow], int]:
        """Get all knowledge contents from the database.

        Args:
            limit (Optional[int]): The maximum number of knowledge contents to return.
            page (Optional[int]): The page number.
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by.
            linked_to (Optional[str]): Filter by linked_to value (knowledge instance name).
            user_id (Optional[str]): When set, match rows owned by this user or unowned rows.

        Returns:
            Tuple[List[KnowledgeRow], int]: The knowledge contents and total count.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        table = self._get_table(table_type="knowledge")
        if table is None:
            return [], 0

        validate_pagination(limit, page)
        try:
            with self.Session() as sess, sess.begin():
                stmt = select(table)

                # Apply linked_to filter if provided
                if linked_to is not None:
                    stmt = stmt.where(table.c.linked_to == linked_to)

                # Apply owner scoping if provided
                if user_id is not None:
                    stmt = stmt.where(or_(table.c.user_id == user_id, table.c.user_id.is_(None)))

                # Apply sorting
                if sort_by is not None:
                    stmt = stmt.order_by(getattr(table.c, sort_by) * (1 if sort_order == "asc" else -1))

                # Get total count before applying limit and pagination
                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = sess.execute(count_stmt).scalar()

                # Apply pagination after count
                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset((page - 1) * limit)

                result = sess.execute(stmt).fetchall()
                return [KnowledgeRow.model_validate(record._mapping) for record in result], total_count

        except Exception as e:
            log_error(f"Error getting knowledge contents: {str(e)}")
            raise e

    def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        """Upsert knowledge content in the database.

        Args:
            knowledge_row (KnowledgeRow): The knowledge row to upsert.

        Returns:
            Optional[KnowledgeRow]: The upserted knowledge row, or None if the operation fails.
        """
        try:
            table = self._get_table(table_type="knowledge", create_table_if_not_found=True)
            if table is None:
                return None

            with self.Session() as sess, sess.begin():
                # A scoped write must not overwrite a row it does not own
                if knowledge_row.user_id is not None and knowledge_row.id:
                    stored = sess.execute(select(table.c.user_id).where(table.c.id == knowledge_row.id)).fetchone()
                    if stored is not None and stored[0] != knowledge_row.user_id:
                        raise ValueError(f"Knowledge content {knowledge_row.id} not found")

                update_fields = {
                    k: v
                    for k, v in {
                        "name": knowledge_row.name,
                        "description": knowledge_row.description,
                        "metadata": knowledge_row.metadata,
                        "type": knowledge_row.type,
                        "size": knowledge_row.size,
                        "linked_to": knowledge_row.linked_to,
                        "access_count": knowledge_row.access_count,
                        "status": knowledge_row.status,
                        "status_message": knowledge_row.status_message,
                        "user_id": knowledge_row.user_id,
                        "created_at": knowledge_row.created_at,
                        "updated_at": knowledge_row.updated_at,
                        "external_id": knowledge_row.external_id,
                    }.items()
                    # Filtering out None fields if updating
                    if v is not None
                }

                stmt = (
                    sqlite.insert(table)
                    .values(knowledge_row.model_dump())
                    .on_conflict_do_update(index_elements=["id"], set_=update_fields)
                )
                sess.execute(stmt)

            return knowledge_row

        except Exception as e:
            log_error(f"Error upserting knowledge content: {str(e)}")
            raise e

    # -- Eval methods --

    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        """Create an EvalRunRecord in the database.

        Args:
            eval_run (EvalRunRecord): The eval run to create.

        Returns:
            Optional[EvalRunRecord]: The created eval run, or None if the operation fails.

        Raises:
            Exception: If an error occurs during creation.
        """
        try:
            table = self._get_table(table_type="evals", create_table_if_not_found=True)
            if table is None:
                return None

            with self.Session() as sess, sess.begin():
                current_time = int(time.time())
                stmt = sqlite.insert(table).values(
                    {
                        "created_at": current_time,
                        "updated_at": current_time,
                        **eval_run.model_dump(),
                    }
                )
                sess.execute(stmt)
                sess.commit()

            log_debug(f"Created eval run with id '{eval_run.run_id}'")

            return eval_run

        except Exception as e:
            log_error(f"Error creating eval run: {str(e)}")
            raise e

    def delete_eval_run(self, eval_run_id: str) -> None:
        """Delete an eval run from the database.

        Args:
            eval_run_id (str): The ID of the eval run to delete.
        """
        try:
            table = self._get_table(table_type="evals")
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                stmt = table.delete().where(table.c.run_id == eval_run_id)
                result = sess.execute(stmt)
                if result.rowcount == 0:
                    log_warning(f"No eval run found with ID: {eval_run_id}")
                else:
                    log_debug(f"Deleted eval run with ID: {eval_run_id}")

        except Exception as e:
            log_error(f"Error deleting eval run {eval_run_id}: {str(e)}")
            raise e

    def delete_eval_runs(self, eval_run_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete multiple eval runs from the database.

        Args:
            eval_run_ids (List[str]): List of eval run IDs to delete.
            user_id (Optional[str]): If set, only delete runs owned by this user.
        """
        try:
            table = self._get_table(table_type="evals")
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                stmt = table.delete().where(table.c.run_id.in_(eval_run_ids))
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                result = sess.execute(stmt)
                if result.rowcount == 0:
                    log_debug(f"No eval runs found with IDs: {eval_run_ids}")
                else:
                    log_debug(f"Deleted {result.rowcount} eval runs")

        except Exception as e:
            log_error(f"Error deleting eval runs {eval_run_ids}: {str(e)}")
            raise e

    def get_eval_run(
        self, eval_run_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Get an eval run from the database.

        Args:
            eval_run_id (str): The ID of the eval run to get.
            deserialize (Optional[bool]): Whether to serialize the eval run. Defaults to True.
            user_id (Optional[str]): If set, only return the run if owned by this user.

        Returns:
            Optional[Union[EvalRunRecord, Dict[str, Any]]]:
                - When deserialize=True: EvalRunRecord object
                - When deserialize=False: EvalRun dictionary

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table = self._get_table(table_type="evals")
            if table is None:
                return None

            with self.Session() as sess, sess.begin():
                stmt = select(table).where(table.c.run_id == eval_run_id)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                result = sess.execute(stmt).fetchone()
                if result is None:
                    return None

                eval_run_raw = dict(result._mapping)
                if not eval_run_raw or not deserialize:
                    return eval_run_raw

            return EvalRunRecord.model_validate(eval_run_raw)

        except Exception as e:
            log_error(f"Exception getting eval run {eval_run_id}: {str(e)}")
            raise e

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
        """Get all eval runs from the database.

        Args:
            limit (Optional[int]): The maximum number of eval runs to return.
            page (Optional[int]): The page number.
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by.
            agent_id (Optional[str]): The ID of the agent to filter by.
            team_id (Optional[str]): The ID of the team to filter by.
            workflow_id (Optional[str]): The ID of the workflow to filter by.
            model_id (Optional[str]): The ID of the model to filter by.
            user_id (Optional[str]): If set, only return runs owned by this user.
            eval_type (Optional[List[EvalType]]): The type(s) of eval to filter by.
            filter_type (Optional[EvalFilterType]): Filter by component type (agent, team, workflow).
            deserialize (Optional[bool]): Whether to serialize the eval runs. Defaults to True.
            create_table_if_not_found (Optional[bool]): Whether to create the table if it doesn't exist.

        Returns:
            Union[List[EvalRunRecord], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of EvalRunRecord objects
                - When deserialize=False: List of EvalRun dictionaries and total count

        Raises:
            Exception: If an error occurs during retrieval.
        """
        validate_pagination(limit, page)
        try:
            table = self._get_table(table_type="evals")
            if table is None:
                return [] if deserialize else ([], 0)

            with self.Session() as sess, sess.begin():
                stmt = select(table)

                # Filtering
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                if agent_id is not None:
                    stmt = stmt.where(table.c.agent_id == agent_id)
                if team_id is not None:
                    stmt = stmt.where(table.c.team_id == team_id)
                if workflow_id is not None:
                    stmt = stmt.where(table.c.workflow_id == workflow_id)
                if model_id is not None:
                    stmt = stmt.where(table.c.model_id == model_id)
                if eval_type is not None and len(eval_type) > 0:
                    stmt = stmt.where(table.c.eval_type.in_(eval_type))
                if filter_type is not None:
                    if filter_type == EvalFilterType.AGENT:
                        stmt = stmt.where(table.c.agent_id.is_not(None))
                    elif filter_type == EvalFilterType.TEAM:
                        stmt = stmt.where(table.c.team_id.is_not(None))
                    elif filter_type == EvalFilterType.WORKFLOW:
                        stmt = stmt.where(table.c.workflow_id.is_not(None))

                # Get total count after applying filtering
                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = sess.execute(count_stmt).scalar()

                # Sorting - apply default sort by created_at desc if no sort parameters provided
                if sort_by is None:
                    stmt = stmt.order_by(table.c.created_at.desc())
                else:
                    stmt = apply_sorting(stmt, table, sort_by, sort_order)
                # Paginating
                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset((page - 1) * limit)

                result = sess.execute(stmt).fetchall()
                if not result:
                    return [] if deserialize else ([], 0)

                eval_runs_raw = [dict(row._mapping) for row in result]
                if not deserialize:
                    return eval_runs_raw, total_count

            return [EvalRunRecord.model_validate(row) for row in eval_runs_raw]

        except Exception as e:
            log_error(f"Exception getting eval runs: {str(e)}")
            raise e

    def rename_eval_run(
        self, eval_run_id: str, name: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Upsert the name of an eval run in the database, returning raw dictionary.

        Args:
            eval_run_id (str): The ID of the eval run to update.
            name (str): The new name of the eval run.
            deserialize (Optional[bool]): Whether to serialize the eval run. Defaults to True.
            user_id (Optional[str]): If set, only rename the run if owned by this user.

        Returns:
            Optional[Union[EvalRunRecord, Dict[str, Any]]]:
                - When deserialize=True: EvalRunRecord object
                - When deserialize=False: EvalRun dictionary

        Raises:
            Exception: If an error occurs during update.
        """
        try:
            table = self._get_table(table_type="evals")
            if table is None:
                return None

            with self.Session() as sess, sess.begin():
                stmt = (
                    table.update().where(table.c.run_id == eval_run_id).values(name=name, updated_at=int(time.time()))
                )
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                sess.execute(stmt)

            eval_run_raw = self.get_eval_run(eval_run_id=eval_run_id, deserialize=deserialize, user_id=user_id)

            log_debug(f"Renamed eval run with id '{eval_run_id}' to '{name}'")

            if not eval_run_raw or not deserialize:
                return eval_run_raw

            return EvalRunRecord.model_validate(eval_run_raw)

        except Exception as e:
            log_error(f"Error renaming eval run {eval_run_id}: {str(e)}")
            raise e

    def update_eval_run_user_id(self, eval_run_id: str, user_id: str) -> None:
        """Set the owner (user_id) on an existing eval run.

        Args:
            eval_run_id (str): The ID of the eval run to update.
            user_id (str): The owner to set.
        """
        try:
            table = self._get_table(table_type="evals")
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                stmt = table.update().where(table.c.run_id == eval_run_id).values(user_id=user_id)
                sess.execute(stmt)

        except Exception as e:
            log_error(f"Error setting owner on eval run {eval_run_id}: {str(e)}")
            raise e

    # -- Trace methods --

    def _get_traces_base_query(self, table: Table, spans_table: Optional[Table] = None):
        """Build base query for traces with aggregated span counts.

        Args:
            table: The traces table.
            spans_table: The spans table (optional).

        Returns:
            SQLAlchemy select statement with total_spans and error_count calculated dynamically.
        """
        from sqlalchemy import case, func, literal

        if spans_table is not None:
            # JOIN with spans table to calculate total_spans and error_count
            return (
                select(
                    table,
                    func.coalesce(func.count(spans_table.c.span_id), 0).label("total_spans"),
                    func.coalesce(func.sum(case((spans_table.c.status_code == "ERROR", 1), else_=0)), 0).label(
                        "error_count"
                    ),
                )
                .select_from(table.outerjoin(spans_table, table.c.trace_id == spans_table.c.trace_id))
                .group_by(table.c.trace_id)
            )
        else:
            # Fallback if spans table doesn't exist
            return select(table, literal(0).label("total_spans"), literal(0).label("error_count"))

    def _get_trace_component_level_expr(self, workflow_id_col, team_id_col, agent_id_col, name_col):
        """Build a SQL CASE expression that returns the component level for a trace.

        Component levels (higher = more important):
            - 3: Workflow root (.run or .arun with workflow_id)
            - 2: Team root (.run or .arun with team_id)
            - 1: Agent root (.run or .arun with agent_id)
            - 0: Child span (not a root)

        Args:
            workflow_id_col: SQL column/expression for workflow_id
            team_id_col: SQL column/expression for team_id
            agent_id_col: SQL column/expression for agent_id
            name_col: SQL column/expression for name

        Returns:
            SQLAlchemy CASE expression returning the component level as an integer.
        """
        from sqlalchemy import and_, case, or_

        is_root_name = or_(name_col.contains(".run"), name_col.contains(".arun"))

        return case(
            # Workflow root (level 3)
            (and_(workflow_id_col.isnot(None), is_root_name), 3),
            # Team root (level 2)
            (and_(team_id_col.isnot(None), is_root_name), 2),
            # Agent root (level 1)
            (and_(agent_id_col.isnot(None), is_root_name), 1),
            # Child span or unknown (level 0)
            else_=0,
        )

    def upsert_trace(self, trace: "Trace") -> None:
        """Create or update a single trace record in the database.

        Uses INSERT ... ON CONFLICT DO UPDATE (upsert) to handle concurrent inserts
        atomically and avoid race conditions.

        Args:
            trace: The Trace object to store (one per trace_id).
        """
        from sqlalchemy import case

        try:
            table = self._get_table(table_type="traces", create_table_if_not_found=True)
            if table is None:
                return

            trace_dict = trace.to_dict()
            trace_dict.pop("total_spans", None)
            trace_dict.pop("error_count", None)

            with self.Session() as sess, sess.begin():
                # Use upsert to handle concurrent inserts atomically
                # On conflict, update fields while preserving existing non-null context values
                # and keeping the earliest start_time
                insert_stmt = sqlite.insert(table).values(trace_dict)

                # Build component level expressions for comparing trace priority
                new_level = self._get_trace_component_level_expr(
                    insert_stmt.excluded.workflow_id,
                    insert_stmt.excluded.team_id,
                    insert_stmt.excluded.agent_id,
                    insert_stmt.excluded.name,
                )
                existing_level = self._get_trace_component_level_expr(
                    table.c.workflow_id,
                    table.c.team_id,
                    table.c.agent_id,
                    table.c.name,
                )

                # Build the ON CONFLICT DO UPDATE clause
                # Use MIN for start_time, MAX for end_time to capture full trace duration
                # SQLite stores timestamps as ISO strings, so string comparison works for ISO format
                # Duration is calculated as: (MAX(end_time) - MIN(start_time)) in milliseconds
                # SQLite doesn't have epoch extraction, so we calculate duration using julianday
                upsert_stmt = insert_stmt.on_conflict_do_update(
                    index_elements=["trace_id"],
                    set_={
                        "end_time": func.max(table.c.end_time, insert_stmt.excluded.end_time),
                        "start_time": func.min(table.c.start_time, insert_stmt.excluded.start_time),
                        # Calculate duration in milliseconds using julianday (SQLite-specific)
                        # julianday returns days, so multiply by 86400000 to get milliseconds
                        "duration_ms": (
                            func.julianday(func.max(table.c.end_time, insert_stmt.excluded.end_time))
                            - func.julianday(func.min(table.c.start_time, insert_stmt.excluded.start_time))
                        )
                        * 86400000,
                        "status": insert_stmt.excluded.status,
                        # Update name only if new trace is from a higher-level component
                        # Priority: workflow (3) > team (2) > agent (1) > child spans (0)
                        "name": case(
                            (new_level > existing_level, insert_stmt.excluded.name),
                            else_=table.c.name,
                        ),
                        # Preserve existing non-null context values: COALESCE returns
                        # the first non-null arg, so put the existing column first.
                        # Otherwise a later upsert from a child span (e.g. a post-hook
                        # agent's run with a different session_id) would overwrite
                        # the trace's already-correct context.
                        "run_id": func.coalesce(table.c.run_id, insert_stmt.excluded.run_id),
                        "session_id": func.coalesce(table.c.session_id, insert_stmt.excluded.session_id),
                        "user_id": func.coalesce(table.c.user_id, insert_stmt.excluded.user_id),
                        "agent_id": func.coalesce(table.c.agent_id, insert_stmt.excluded.agent_id),
                        "team_id": func.coalesce(table.c.team_id, insert_stmt.excluded.team_id),
                        "workflow_id": func.coalesce(table.c.workflow_id, insert_stmt.excluded.workflow_id),
                    },
                )
                sess.execute(upsert_stmt)

        except Exception as e:
            log_error(f"Error creating trace: {str(e)}")
            # Don't raise - tracing should not break the main application flow

    def get_trace(
        self,
        trace_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ):
        """Get a single trace by trace_id (or run_id).

        See ``BaseDb.get_trace`` for why no other filters are accepted here.
        Ownership checks live at the route layer.

        Args:
            trace_id: The unique trace identifier.
            run_id: Fallback unique-alternative-key lookup.

        Returns:
            Optional[Trace]: The trace if found, None otherwise.
        """
        try:
            from agno.tracing.schemas import Trace

            table = self._get_table(table_type="traces")
            if table is None:
                return None

            # Get spans table for JOIN
            spans_table = self._get_table(table_type="spans")

            with self.Session() as sess:
                # Build query with aggregated span counts
                stmt = self._get_traces_base_query(table, spans_table)

                if trace_id:
                    stmt = stmt.where(table.c.trace_id == trace_id)
                elif run_id:
                    stmt = stmt.where(table.c.run_id == run_id)
                else:
                    log_debug("get_trace called without any filter parameters")
                    return None

                # Order by most recent and get first result
                stmt = stmt.order_by(table.c.start_time.desc()).limit(1)
                result = sess.execute(stmt).fetchone()

                if result:
                    return Trace.from_dict(dict(result._mapping))
                return None

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
    ) -> tuple[List, int]:
        """Get traces matching the provided filters with pagination.

        Args:
            run_id: Filter by run ID.
            session_id: Filter by session ID.
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            workflow_id: Filter by workflow ID.
            status: Filter by status (OK, ERROR, UNSET).
            start_time: Filter traces starting after this datetime.
            end_time: Filter traces ending before this datetime.
            limit: Maximum number of traces to return per page.
            page: Page number (1-indexed).
            filter_expr: Advanced filter expression dict (from FilterExpr.to_dict()).

        Returns:
            tuple[List[Trace], int]: Tuple of (list of matching traces, total count).
        """
        try:
            from sqlalchemy import func

            from agno.tracing.schemas import Trace

            log_debug(
                f"get_traces called with filters: run_id={run_id}, session_id={session_id}, user_id={user_id}, agent_id={agent_id}, page={page}, limit={limit}"
            )

            table = self._get_table(table_type="traces")
            if table is None:
                log_debug(" Traces table not found")
                return [], 0

            # Get spans table for JOIN
            spans_table = self._get_table(table_type="spans")

            with self.Session() as sess:
                # Build base query with aggregated span counts
                base_stmt = self._get_traces_base_query(table, spans_table)

                # Apply filters
                if run_id:
                    base_stmt = base_stmt.where(table.c.run_id == run_id)
                if session_id:
                    base_stmt = base_stmt.where(table.c.session_id == session_id)
                if user_id is not None:
                    base_stmt = base_stmt.where(table.c.user_id == user_id)
                if agent_id:
                    base_stmt = base_stmt.where(table.c.agent_id == agent_id)
                if team_id:
                    base_stmt = base_stmt.where(table.c.team_id == team_id)
                if workflow_id:
                    base_stmt = base_stmt.where(table.c.workflow_id == workflow_id)
                if status:
                    base_stmt = base_stmt.where(table.c.status == status)
                if start_time:
                    # Convert datetime to ISO string for comparison
                    base_stmt = base_stmt.where(table.c.start_time >= start_time.isoformat())
                if end_time:
                    # Convert datetime to ISO string for comparison
                    base_stmt = base_stmt.where(table.c.end_time <= end_time.isoformat())

                # Apply advanced filter expression
                if filter_expr:
                    try:
                        from agno.db.filter_converter import TRACE_COLUMNS, filter_expr_to_sqlalchemy

                        base_stmt = base_stmt.where(
                            filter_expr_to_sqlalchemy(filter_expr, table, allowed_columns=TRACE_COLUMNS)
                        )
                    except ValueError:
                        # Re-raise ValueError for proper 400 response at API layer
                        raise
                    except (KeyError, TypeError) as e:
                        raise ValueError(f"Invalid filter expression: {e}") from e

                # Get total count
                count_stmt = select(func.count()).select_from(base_stmt.alias())
                total_count = sess.execute(count_stmt).scalar() or 0

                # Apply pagination
                offset = (page - 1) * limit if page and limit else 0
                paginated_stmt = base_stmt.order_by(table.c.start_time.desc()).limit(limit).offset(offset)

                results = sess.execute(paginated_stmt).fetchall()

                traces = [Trace.from_dict(dict(row._mapping)) for row in results]
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
        group_by: Literal["session", "agent", "team", "workflow", "endpoint"] = "session",
    ) -> tuple[List[Dict[str, Any]], int]:
        """Get trace statistics grouped by session or by component.

        Args:
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            workflow_id: Filter by workflow ID.
            start_time: Filter sessions with traces created after this datetime.
            end_time: Filter sessions with traces created before this datetime.
            limit: Maximum number of groups to return per page.
            page: Page number (1-indexed).
            filter_expr: Advanced filter expression dict (from FilterExpr.to_dict()).
            group_by: Grouping key. "session" (default) groups by session_id and keeps
                the original output shape, ordered by last activity. "agent", "team" and
                "workflow" group by the corresponding component id, add duration and
                error aggregates, and are ordered by total_traces descending; traces
                without the grouping id are excluded. "endpoint" groups traces that
                carry no component id at all (HTTP/MCP entrypoint wrappers) by trace
                name, with the same aggregates. SQLite has no percentile function,
                so p95_duration_ms is always None.

        Returns:
            tuple[List[Dict], int]: Tuple of (list of stats dicts, total count).
                With group_by="session", each dict contains: session_id, user_id,
                agent_id, team_id, workflow_id, total_traces, first_trace_at, last_trace_at.
                With a component grouping, each dict contains: <group>_id, total_traces,
                total_sessions, avg_duration_ms, p95_duration_ms (always None),
                max_duration_ms, error_traces (traces with status ERROR), first_trace_at,
                last_trace_at. With group_by="endpoint", the grouping key is name
                instead of <group>_id.
        """
        if group_by not in ("session", "agent", "team", "workflow", "endpoint"):
            raise ValueError(f"Invalid group_by value: {group_by!r}. Allowed: session, agent, team, workflow, endpoint")

        try:
            from sqlalchemy import and_, case, distinct, func

            table = self._get_table(table_type="traces")
            if table is None:
                log_debug("Traces table not found")
                return [], 0

            with self.Session() as sess:
                if group_by == "session":
                    # Build base query grouped by session_id
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
                        .where(table.c.session_id.isnot(None))  # Only sessions with session_id
                        .group_by(table.c.session_id)
                    )
                else:
                    if group_by == "endpoint":
                        # Endpoint-level traces (HTTP/MCP entrypoint wrappers) carry no component ids
                        group_column = table.c.name
                        group_label = "name"
                        group_filter = and_(
                            table.c.agent_id.is_(None),
                            table.c.team_id.is_(None),
                            table.c.workflow_id.is_(None),
                        )
                    else:
                        group_column = {
                            "agent": table.c.agent_id,
                            "team": table.c.team_id,
                            "workflow": table.c.workflow_id,
                        }[group_by]
                        group_label = f"{group_by}_id"
                        group_filter = group_column.isnot(None)  # Only traces attributed to the grouping component
                    base_stmt = (
                        select(
                            group_column.label(group_label),
                            func.count(table.c.trace_id).label("total_traces"),
                            func.count(distinct(table.c.session_id)).label("total_sessions"),
                            func.avg(table.c.duration_ms).label("avg_duration_ms"),
                            func.max(table.c.duration_ms).label("max_duration_ms"),
                            func.sum(case((table.c.status == "ERROR", 1), else_=0)).label("error_traces"),
                            func.min(table.c.created_at).label("first_trace_at"),
                            func.max(table.c.created_at).label("last_trace_at"),
                        )
                        .where(group_filter)
                        .group_by(group_column)
                    )

                # Apply filters
                if user_id is not None:
                    base_stmt = base_stmt.where(table.c.user_id == user_id)
                if workflow_id:
                    base_stmt = base_stmt.where(table.c.workflow_id == workflow_id)
                if team_id:
                    base_stmt = base_stmt.where(table.c.team_id == team_id)
                if agent_id:
                    base_stmt = base_stmt.where(table.c.agent_id == agent_id)
                if start_time:
                    # Convert datetime to ISO string for comparison
                    base_stmt = base_stmt.where(table.c.created_at >= start_time.isoformat())
                if end_time:
                    # Convert datetime to ISO string for comparison
                    base_stmt = base_stmt.where(table.c.created_at <= end_time.isoformat())

                # Apply advanced filter expression
                if filter_expr:
                    try:
                        from agno.db.filter_converter import TRACE_COLUMNS, filter_expr_to_sqlalchemy

                        base_stmt = base_stmt.where(
                            filter_expr_to_sqlalchemy(filter_expr, table, allowed_columns=TRACE_COLUMNS)
                        )
                    except ValueError:
                        # Re-raise ValueError for proper 400 response at API layer
                        raise
                    except (KeyError, TypeError) as e:
                        raise ValueError(f"Invalid filter expression: {e}") from e

                # Get total count of groups
                count_stmt = select(func.count()).select_from(base_stmt.alias())
                total_count = sess.execute(count_stmt).scalar() or 0

                # Apply pagination and ordering
                offset = (page - 1) * limit if page and limit else 0
                order_by: List[Any] = (
                    [func.max(table.c.created_at).desc()]
                    if group_by == "session"
                    else [func.count(table.c.trace_id).desc(), group_column]
                )
                paginated_stmt = base_stmt.order_by(*order_by).limit(limit).offset(offset)

                results = sess.execute(paginated_stmt).fetchall()

                # Convert to list of dicts with datetime objects
                from datetime import datetime

                stats_list = []
                for row in results:
                    # Parse ISO format strings to datetime objects
                    first_trace_at = datetime.fromisoformat(row.first_trace_at.replace("Z", "+00:00"))
                    last_trace_at = datetime.fromisoformat(row.last_trace_at.replace("Z", "+00:00"))

                    if group_by == "session":
                        stats_list.append(
                            {
                                "session_id": row.session_id,
                                "user_id": row.user_id,
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
                                "p95_duration_ms": None,
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

    # -- Span methods --

    def create_span(self, span: "Span") -> None:
        """Create a single span in the database.

        Args:
            span: The Span object to store.
        """
        try:
            table = self._get_table(table_type="spans", create_table_if_not_found=True)
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                stmt = sqlite.insert(table).values(span.to_dict())
                sess.execute(stmt)

        except Exception as e:
            log_error(f"Error creating span: {str(e)}")

    def create_spans(self, spans: List) -> None:
        """Create multiple spans in the database as a batch.

        Args:
            spans: List of Span objects to store.
        """
        if not spans:
            return

        try:
            table = self._get_table(table_type="spans", create_table_if_not_found=True)
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                for span in spans:
                    stmt = sqlite.insert(table).values(span.to_dict())
                    sess.execute(stmt)

        except Exception as e:
            log_error(f"Error creating spans batch: {str(e)}")

    def get_span(self, span_id: str):
        """Get a single span by its span_id.

        Args:
            span_id: The unique span identifier.

        Returns:
            Optional[Span]: The span if found, None otherwise.
        """
        try:
            from agno.tracing.schemas import Span

            table = self._get_table(table_type="spans")
            if table is None:
                return None

            with self.Session() as sess:
                stmt = table.select().where(table.c.span_id == span_id)
                result = sess.execute(stmt).fetchone()
                if result:
                    return Span.from_dict(dict(result._mapping))
                return None

        except Exception as e:
            log_error(f"Error getting span: {str(e)}")
            return None

    def get_spans(
        self,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
    ) -> List:
        """Get spans matching the provided filters.

        Args:
            trace_id: Filter by trace ID.
            parent_span_id: Filter by parent span ID.

        Returns:
            List[Span]: List of matching spans.
        """
        try:
            from agno.tracing.schemas import Span

            table = self._get_table(table_type="spans")
            if table is None:
                return []

            with self.Session() as sess:
                stmt = table.select()

                # Apply filters
                if trace_id:
                    stmt = stmt.where(table.c.trace_id == trace_id)
                if parent_span_id:
                    stmt = stmt.where(table.c.parent_span_id == parent_span_id)

                results = sess.execute(stmt).fetchall()
                return [Span.from_dict(dict(row._mapping)) for row in results]

        except Exception as e:
            log_error(f"Error getting spans: {str(e)}")
            return []

    def get_span_stats(
        self,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        name: Optional[str] = None,
        span_type: Optional[str] = None,
        limit: Optional[int] = 20,
        page: Optional[int] = 1,
        sort_by: str = "total_calls",
        sort_order: str = "desc",
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get span statistics aggregated SQL-side by span name and span type.

        Only span names, durations and status are aggregated. The span attributes
        payload, which can hold full conversation content, is never selected — the
        single "openinference.span.kind" key is extracted in SQL as the span type.
        SQLite has no percentile function, so p95_duration_ms is always None and
        sorting by p95_duration_ms falls back to total_calls.

        Args:
            agent_id: Only include spans belonging to traces of this agent.
            team_id: Only include spans belonging to traces of this team.
            workflow_id: Only include spans belonging to traces of this workflow.
            start_time: Only include spans starting after this datetime.
            end_time: Only include spans starting before this datetime.
            name: Filter by exact span name.
            span_type: Filter by span type (e.g. AGENT, LLM, TOOL, CHAIN).
            limit: Maximum number of groups to return per page.
            page: Page number (1-indexed).
            sort_by: Aggregate to sort by: total_calls, avg_duration_ms,
                max_duration_ms, error_count or last_called_at.
            sort_order: "asc" or "desc".

        Returns:
            Tuple[List[Dict], int]: Tuple of (list of stats dicts, total count of groups).
                Each dict contains: name, span_type, total_calls, avg_duration_ms,
                p95_duration_ms (always None), max_duration_ms, error_count,
                last_called_at (datetime).
        """
        try:
            from sqlalchemy import case, func

            table = self._get_table(table_type="spans")
            if table is None:
                log_debug("Spans table not found")
                return [], 0

            span_type_col = func.json_extract(table.c.attributes, '$."openinference.span.kind"')

            total_calls_col = func.count(table.c.span_id)
            avg_duration_col = func.avg(table.c.duration_ms)
            max_duration_col = func.max(table.c.duration_ms)
            error_count_col = func.sum(case((table.c.status_code == "ERROR", 1), else_=0))
            last_called_at_col = func.max(table.c.start_time)

            with self.Session() as sess:
                stmt = select(
                    table.c.name,
                    span_type_col.label("span_type"),
                    total_calls_col.label("total_calls"),
                    avg_duration_col.label("avg_duration_ms"),
                    max_duration_col.label("max_duration_ms"),
                    error_count_col.label("error_count"),
                    last_called_at_col.label("last_called_at"),
                ).group_by(table.c.name, span_type_col)

                # Component filters live on the traces table
                if agent_id or team_id or workflow_id:
                    traces_table = self._get_table(table_type="traces")
                    if traces_table is None:
                        log_debug("Traces table not found")
                        return [], 0
                    stmt = stmt.select_from(table.join(traces_table, table.c.trace_id == traces_table.c.trace_id))
                    if agent_id:
                        stmt = stmt.where(traces_table.c.agent_id == agent_id)
                    if team_id:
                        stmt = stmt.where(traces_table.c.team_id == team_id)
                    if workflow_id:
                        stmt = stmt.where(traces_table.c.workflow_id == workflow_id)

                if start_time:
                    # Convert datetime to ISO string for comparison
                    stmt = stmt.where(table.c.start_time >= start_time.isoformat())
                if end_time:
                    # Convert datetime to ISO string for comparison
                    stmt = stmt.where(table.c.start_time <= end_time.isoformat())
                if name:
                    stmt = stmt.where(table.c.name == name)
                if span_type:
                    stmt = stmt.where(span_type_col == span_type)

                # Get total count of groups
                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = sess.execute(count_stmt).scalar() or 0

                sort_columns = {
                    "total_calls": total_calls_col,
                    "avg_duration_ms": avg_duration_col,
                    "max_duration_ms": max_duration_col,
                    "error_count": error_count_col,
                    "last_called_at": last_called_at_col,
                }
                sort_col = sort_columns.get(sort_by)
                if sort_col is None:
                    log_debug(f"Sort field '{sort_by}' not available on SQLite. Sorting by total_calls.")
                    sort_col = total_calls_col
                order_by = sort_col.asc() if sort_order == "asc" else sort_col.desc()

                offset = (page - 1) * limit if page and limit else 0
                paginated_stmt = stmt.order_by(order_by, table.c.name, span_type_col).limit(limit).offset(offset)

                results = sess.execute(paginated_stmt).fetchall()

                from datetime import datetime

                stats_list = []
                for row in results:
                    last_called_at = (
                        datetime.fromisoformat(row.last_called_at.replace("Z", "+00:00"))
                        if row.last_called_at
                        else None
                    )
                    stats_list.append(
                        {
                            "name": row.name,
                            "span_type": row.span_type,
                            "total_calls": row.total_calls,
                            "avg_duration_ms": round(float(row.avg_duration_ms), 1)
                            if row.avg_duration_ms is not None
                            else None,
                            "p95_duration_ms": None,
                            "max_duration_ms": row.max_duration_ms,
                            "error_count": row.error_count,
                            "last_called_at": last_called_at,
                        }
                    )

                return stats_list, total_count

        except Exception as e:
            log_error(f"Error getting span stats: {str(e)}")
            return [], 0

    # -- Migrations --

    def migrate_table_from_v1_to_v2(self, v1_db_schema: str, v1_table_name: str, v1_table_type: str):
        """Migrate all content in the given table to the right v2 table"""

        from agno.db.migrations.v1_to_v2 import (
            get_all_table_content,
            parse_agent_sessions,
            parse_memories,
            parse_team_sessions,
            parse_workflow_sessions,
        )

        # Get all content from the old table
        old_content: list[dict[str, Any]] = get_all_table_content(
            db=self,
            db_schema=v1_db_schema,
            table_name=v1_table_name,
        )
        if not old_content:
            log_info(f"No content to migrate from table {v1_table_name}")
            return

        # Parse the content into the new format
        memories: List[UserMemory] = []
        sessions: Sequence[Union[AgentSession, TeamSession, WorkflowSession]] = []
        if v1_table_type == "agent_sessions":
            sessions = parse_agent_sessions(old_content)
        elif v1_table_type == "team_sessions":
            sessions = parse_team_sessions(old_content)
        elif v1_table_type == "workflow_sessions":
            sessions = parse_workflow_sessions(old_content)
        elif v1_table_type == "memories":
            memories = parse_memories(old_content)
        else:
            raise ValueError(f"Invalid table type: {v1_table_type}")

        # Insert the new content into the new table
        if v1_table_type == "agent_sessions":
            for session in sessions:
                self.upsert_session(session)
            log_info(f"Migrated {len(sessions)} Agent sessions to table: {self.session_table_name}")

        elif v1_table_type == "team_sessions":
            for session in sessions:
                self.upsert_session(session)
            log_info(f"Migrated {len(sessions)} Team sessions to table: {self.session_table_name}")

        elif v1_table_type == "workflow_sessions":
            for session in sessions:
                self.upsert_session(session)
            log_info(f"Migrated {len(sessions)} Workflow sessions to table: {self.session_table_name}")

        elif v1_table_type == "memories":
            for memory in memories:
                self.upsert_user_memory(memory)
            log_info(f"Migrated {len(memories)} memories to table: {self.memory_table}")

    # --- Components ---
    def get_component(
        self,
        component_id: str,
        component_type: Optional[ComponentType] = None,
        user_id: Optional[str] = None,
        include_deleted: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Get a component by ID.

        Args:
            component_id: The component ID.
            component_type: Optional type filter (agent|team|workflow).
            user_id: If set, return the component only if this user may see it:
                owned by them, unowned (shared), or published.
            include_deleted: Also return an archived (soft-deleted) row.

        Returns:
            Component dictionary or None if not found.
        """
        try:
            table = self._get_table(table_type="components")
            if table is None:
                return None

            with self.Session() as sess:
                stmt = select(table).where(table.c.component_id == component_id)
                if not include_deleted:
                    stmt = stmt.where(table.c.deleted_at.is_(None))
                if component_type is not None:
                    stmt = stmt.where(table.c.component_type == component_type.value)
                if user_id is not None:
                    # Same catalog visibility rule as get_component: own rows,
                    # unowned (shared) rows, and anything published.
                    stmt = stmt.where(
                        or_(
                            table.c.user_id == user_id,
                            table.c.user_id.is_(None),
                            # Live published rows only. Archiving is the off-switch:
                            # it withdraws a component from every other user even
                            # under include_deleted, which relaxes the tombstone
                            # filter for the OWNER's own history, never across owners.
                            and_(
                                table.c.current_version.isnot(None),
                                table.c.deleted_at.is_(None),
                            ),
                        )
                    )

                result = sess.execute(stmt).fetchone()
                return dict(result._mapping) if result else None

        except Exception as e:
            log_error(f"Error getting component: {str(e)}")
            raise

    def upsert_component(
        self,
        component_id: str,
        component_type: Optional[ComponentType] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        current_version: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create or update a component.

        Args:
            component_id: Unique identifier.
            component_type: Type (agent|team|workflow). Required for create, optional for update.
            name: Display name.
            description: Optional description.
            current_version: Optional current version.
            metadata: Optional metadata dict.
            user_id: Owner to set when creating; scopes the update to this user when set.

        Returns:
            Created/updated component dictionary.

        Raises:
            ValueError: If creating and component_type is not provided.
        """
        try:
            table = self._get_table(table_type="components", create_table_if_not_found=True)
            if table is None:
                raise ValueError("Components table not found")

            # Resolved outside the transaction: _get_table may open its own.
            configs_table = self._get_table(table_type="component_configs") if current_version is not None else None

            with self.Session() as sess, sess.begin():
                existing_stmt = select(table).where(table.c.component_id == component_id)
                if user_id is not None:
                    existing_stmt = existing_stmt.where(table.c.user_id == user_id)
                existing = sess.execute(existing_stmt).fetchone()

                if existing is None:
                    # The row can exist under another owner: fail closed instead of creating
                    if user_id is not None:
                        unscoped = sess.execute(
                            select(table.c.component_id).where(table.c.component_id == component_id)
                        ).fetchone()
                        if unscoped is not None:
                            raise ValueError(f"Component {component_id} not found")

                    # Create new component
                    if component_type is None:
                        raise ValueError("component_type is required when creating a new component")

                    sess.execute(
                        table.insert().values(
                            component_id=component_id,
                            component_type=component_type.value if hasattr(component_type, "value") else component_type,
                            name=name or component_id,
                            user_id=user_id,
                            description=description,
                            current_version=None,
                            metadata=metadata,
                            created_at=int(time.time()),
                        )
                    )
                    log_debug(f"Created component {component_id}")

                elif existing.deleted_at is not None:
                    # Archived ids are reserved and their rows immutable. The old
                    # implicit reactivation let a create silently inherit a dead
                    # component's history; restore is explicit now.
                    raise ComponentArchivedError(
                        f"Component {component_id} is archived; restore it explicitly before writing to it"
                    )

                else:
                    # Update existing
                    updates: Dict[str, Any] = {"updated_at": int(time.time())}
                    if component_type is not None:
                        new_type = component_type.value if hasattr(component_type, "value") else component_type
                        # A component's type is part of its identity, not a
                        # field: it decides the run endpoint every schedule
                        # stores, which loader rebuilds it, and how every
                        # stored reference resolves. Rewriting it silently
                        # invalidates all of them - and the archive cascade,
                        # which matches on (type, id), would then miss the very
                        # schedules it exists to disable. Create a new
                        # component instead.
                        if str(existing.component_type) != str(new_type):
                            raise ValueError(
                                f"Cannot change component {component_id} from {existing.component_type} "
                                f"to {new_type}; a component's type is fixed at creation."
                            )
                        updates["component_type"] = new_type
                    if name is not None:
                        updates["name"] = name
                    if description is not None:
                        updates["description"] = description
                    if current_version is not None:
                        # The current pointer names what the platform runs, and
                        # what every actor can see: the catalog's visibility
                        # predicate reads "has a current version" as published.
                        # So the same invariant set_current_version enforces is
                        # enforced here - the version must exist and be
                        # published - or this writer becomes the way around it.
                        if configs_table is not None:
                            target_stage = sess.execute(
                                select(configs_table.c.stage).where(
                                    configs_table.c.component_id == component_id,
                                    configs_table.c.version == current_version,
                                )
                            ).scalar()
                            if target_stage == DELETED_CONFIG_STAGE:
                                raise ValueError(
                                    f"Cannot set deleted config {component_id} v{current_version} as current"
                                )
                            if target_stage is None:
                                raise ValueError(
                                    f"Cannot set missing config {component_id} v{current_version} as current"
                                )
                            if target_stage != "published":
                                raise ValueError(
                                    f"Cannot set draft config {component_id} v{current_version} as current. "
                                    "Only published configs can be current."
                                )
                        updates["current_version"] = current_version
                    if metadata is not None:
                        updates["metadata"] = metadata

                    # deleted_at is re-asserted on the UPDATE itself: the
                    # archived pre-check above is check-then-write, so a
                    # concurrent archive committing in the gap must fail this
                    # write rather than be overtaken by it.
                    update_result = sess.execute(
                        table.update()
                        .where(
                            table.c.component_id == component_id,
                            table.c.deleted_at.is_(None),
                        )
                        .values(**updates)
                    )
                    if update_result.rowcount == 0:
                        raise ComponentArchivedError(
                            f"Component {component_id} is archived; restore it explicitly before writing to it"
                        )
                    log_debug(f"Updated component {component_id}")

                # The answer is read inside the transaction that wrote it, and
                # without the archived filter. A read taken after the commit can
                # be overtaken by an archive on another connection, and reporting
                # a committed write as a failure hands the caller a 4xx for a
                # write that landed.
                written = sess.execute(select(table).where(table.c.component_id == component_id)).fetchone()
                if written is None:
                    raise ValueError(f"Failed to get component {component_id} after upsert")
                result = dict(written._mapping)

            return result

        except Exception as e:
            log_error(f"Error upserting component: {str(e)}")
            raise

    def delete_component(
        self,
        component_id: str,
        hard_delete: bool = False,
        user_id: Optional[str] = None,
        expected_current_version: Optional[int] = None,
        require_no_dependents: bool = True,
        cascade_stats: Optional[Dict[str, int]] = None,
    ) -> bool:
        """Delete a component. Soft delete archives it; the id stays reserved.

        Every schedule aimed at the component is disabled in the same
        transaction, so no delete surface can leave a schedule firing at a
        target that is gone; a cascade failure rolls the delete back.

        Args:
            component_id: The component ID.
            hard_delete: If True, permanently delete rows and links. Otherwise archive.
            user_id: If set, only delete the component if owned by this user.
            expected_current_version: Optional CAS guard on current_version.
            require_no_dependents: Refuse when other components pin this one.

        Returns:
            True if deleted, False if not found.
        """
        try:
            components_table = self._get_table(table_type="components")
            configs_table = self._get_table(table_type="component_configs")
            links_table = self._get_table(table_type="component_links")
            schedules_table = self._get_table(table_type="schedules")

            if components_table is None:
                return False

            # Scope to owner: a non-owner must not delete the component or its configs/links.
            if user_id is not None:
                # Reads treat unowned as shared, but delete stays strict: only the owner (or admin) removes it
                component = self.get_component(component_id, user_id=user_id, include_deleted=hard_delete)
                if component is None or component.get("user_id") != user_id:
                    return False

            if require_no_dependents:
                # An archive breaks only live parents; a hard delete breaks even an
                # archived parent's history, so it checks every link. This read is
                # the early, friendly refusal; the one that cannot be overtaken
                # runs after the write below.
                # Scoped to parents this caller owns (plus unowned ones).
                # Publishing shares a component for composing, so any other
                # tenant can pin it from a draft the owner can never see, edit
                # or reach - and an unscoped veto would then make the owner's
                # own component permanently unarchivable, with the blocking id
                # redacted out of the message. A parent the caller cannot act
                # on does not get to veto; archiving is exactly the signal that
                # such a parent must stop resolving. An unscoped caller (an
                # operator) still sees every parent.
                dependents = self.get_dependents(
                    component_id, active_parents_only=not hard_delete, parent_user_id=user_id
                )
                if dependents:
                    parents = sorted(
                        {str(d["parent_component_id"]) for d in dependents if d.get("parent_component_id")}
                    )
                    raise ComponentDependencyError(
                        f"Cannot delete {component_id}: referenced by {', '.join(str(x) for x in parents)}"
                    )

            with self.Session() as sess, sess.begin():
                # Locked read (a no-op lock on SQLite, a row lock on Postgres):
                # the guard is decided before any row goes, and a concurrent
                # writer pinning this component serializes here.
                row = sess.execute(
                    select(
                        components_table.c.current_version,
                        components_table.c.component_type,
                        components_table.c.user_id,
                    )
                    .where(components_table.c.component_id == component_id)
                    .with_for_update()
                ).fetchone()
                if row is None:
                    return False
                # The scope above is the friendly early exit, read on its own
                # connection; this is the one that cannot be overtaken. Ids are
                # caller-chosen and reusable, so a component freed and
                # re-claimed by another owner in the gap must not be deleted
                # under the first caller's authority.
                if user_id is not None and row.user_id != user_id:
                    return False
                component_type = str(row.component_type)
                if expected_current_version is not None and not current_version_matches(
                    row.current_version, expected_current_version
                ):
                    raise ComponentVersionConflictError(
                        f"Component {component_id} current version is {row.current_version}, "
                        f"expected {expected_current_version}"
                    )

                if hard_delete:
                    # FK order: links and configs go before the component row
                    # (the FKs have no ON DELETE CASCADE, so the reverse order
                    # violates them on every populated component). The guard
                    # was taken as a locked read above; the predicate on the
                    # final DELETE is the belt over that lock.
                    if links_table is not None:
                        # This component's OWN outgoing pins go first. They are
                        # not the evidence the guard below reads, and deleting
                        # them takes the write lock, which is what makes that
                        # read see a parent committed since the friendly
                        # pre-read - the same reason the archive branch
                        # re-asserts after its UPDATE rather than before it.
                        sess.execute(links_table.delete().where(links_table.c.parent_component_id == component_id))
                    if require_no_dependents:
                        # Same check-then-write gap the archive branch closes,
                        # and it has to run while the incoming links still
                        # exist: those rows ARE the evidence. Raising here rolls
                        # the whole delete back.
                        self._refuse_if_dependents(
                            sess,
                            links_table,
                            components_table,
                            configs_table,
                            component_id,
                            active_parents_only=False,
                            parent_user_id=user_id,
                        )
                    if links_table is not None:
                        sess.execute(links_table.delete().where(links_table.c.child_component_id == component_id))
                    if configs_table is not None:
                        sess.execute(configs_table.delete().where(configs_table.c.component_id == component_id))
                    component_delete = components_table.delete().where(components_table.c.component_id == component_id)
                    if user_id is not None:
                        component_delete = component_delete.where(components_table.c.user_id == user_id)
                    if expected_current_version is not None:
                        component_delete = component_delete.where(
                            current_version_guard_clause(components_table.c.current_version, expected_current_version)
                        )
                    result = sess.execute(component_delete)
                    if result.rowcount == 0 and expected_current_version is not None:
                        raise ComponentVersionConflictError(
                            f"Component {component_id} current version changed; expected {expected_current_version}"
                        )
                else:
                    # Archive: stamp deleted_at on a live row only, so the call is
                    # idempotent-visible (a second archive returns False). The
                    # guard rides the UPDATE, so a raced pointer move conflicts
                    # instead of archiving the wrong state.
                    now = int(time.time())
                    archive_update = (
                        components_table.update()
                        .where(
                            components_table.c.component_id == component_id,
                            components_table.c.deleted_at.is_(None),
                        )
                        .values(deleted_at=now, updated_at=now)
                    )
                    if user_id is not None:
                        # The scope rides the WRITE, not just the reads above:
                        # the locked read is still check-then-write against an
                        # id that was hard-deleted and re-claimed by another
                        # owner in the gap, and this UPDATE would otherwise
                        # match that new row.
                        archive_update = archive_update.where(components_table.c.user_id == user_id)
                    if expected_current_version is not None:
                        archive_update = archive_update.where(
                            current_version_guard_clause(components_table.c.current_version, expected_current_version)
                        )
                    result = sess.execute(archive_update)
                    if result.rowcount == 0 and expected_current_version is not None:
                        still_live = sess.execute(
                            select(components_table.c.component_id).where(
                                components_table.c.component_id == component_id,
                                components_table.c.deleted_at.is_(None),
                            )
                        ).scalar_one_or_none()
                        if still_live is not None:
                            raise ComponentVersionConflictError(
                                f"Component {component_id} current version changed; expected {expected_current_version}"
                            )

                    if require_no_dependents and result.rowcount > 0:
                        # The guard above is check-then-write: SQLite takes the
                        # write lock at the first write, so a parent that pinned
                        # this component in the gap becomes visible only now.
                        # Re-asserting rolls the archive back instead of leaving
                        # a live parent pinning an archived child.
                        self._refuse_if_dependents(
                            sess,
                            links_table,
                            components_table,
                            configs_table,
                            component_id,
                            active_parents_only=True,
                            parent_user_id=user_id,
                        )

                if result.rowcount > 0 and schedules_table is not None:
                    # A component that is gone cannot serve a run, so the
                    # schedules aimed at it go off in the SAME transaction as
                    # the delete. Left to the caller, the cascade reaches only
                    # the surfaces that remember it (the SDK deletes did not),
                    # and run after the commit it leaves a window where the
                    # target is gone and the poller still fires. A failure here
                    # rolls the delete back rather than parting the two halves.
                    disabled = self._disable_schedules_for_target_in_session(
                        sess,
                        schedules_table,
                        target_type=component_type,
                        target_id=component_id,
                        reason=f"target_archived:{component_type}:{component_id}",
                    )
                    if cascade_stats is not None:
                        cascade_stats["schedules_disabled"] = disabled
                    if disabled:
                        log_debug(f"Disabled {disabled} schedule(s) targeting {component_type} '{component_id}'")

            return result.rowcount > 0

        except Exception as e:
            log_error(f"Error deleting component: {str(e)}")
            raise

    def restore_component(
        self,
        component_id: str,
        user_id: Optional[str] = None,
    ) -> bool:
        """Restore an archived component: clear deleted_at, keep every version."""
        try:
            components_table = self._get_table(table_type="components")
            if components_table is None:
                return False

            if user_id is not None:
                component = self.get_component(component_id, user_id=user_id, include_deleted=True)
                if component is None or component.get("user_id") != user_id:
                    return False

            links_table = self._get_table(table_type="component_links")

            with self.Session() as sess, sess.begin():
                # Locked read (a row lock on Postgres, a no-op on SQLite).
                row = sess.execute(
                    select(components_table.c.current_version, components_table.c.user_id)
                    .where(components_table.c.component_id == component_id)
                    .with_for_update()
                ).fetchone()
                if row is None:
                    return False
                # Same reason as delete: the scope read above ran on its own
                # connection, so it re-rides the locked row here.
                if user_id is not None and row.user_id != user_id:
                    return False

                restore_update = (
                    components_table.update()
                    .where(
                        components_table.c.component_id == component_id,
                        components_table.c.deleted_at.is_not(None),
                    )
                    .values(deleted_at=None, updated_at=int(time.time()))
                )
                if user_id is not None:
                    # The scope rides the write here too: the reads above are
                    # check-then-write against a reusable id.
                    restore_update = restore_update.where(components_table.c.user_id == user_id)
                result = sess.execute(restore_update)
                if result.rowcount == 0:
                    return False

                # A restore returns the component to dispatch, so its live
                # version's pinned children must be live too: archiving allowed
                # parent-then-child, and restoring only the parent would publish
                # a component whose members can never rebuild. Restore children
                # first. The check runs after the restore write, inside the
                # transaction that holds the write lock: read before it, the
                # guard is check-then-write and an archive of a child committing
                # in the gap leaves a live parent pinning it - a state this
                # guard is supposed to make unreachable.
                if row.current_version is not None and links_table is not None:
                    link_rows = sess.execute(
                        select(links_table.c.child_component_id).where(
                            links_table.c.parent_component_id == component_id,
                            links_table.c.parent_version == row.current_version,
                            links_table.c.link_kind.in_(PIN_LINK_KINDS),
                        )
                    ).fetchall()
                    child_ids = {link.child_component_id for link in link_rows if link.child_component_id}
                    if child_ids:
                        child_rows = sess.execute(
                            select(components_table.c.component_id, components_table.c.deleted_at)
                            .where(components_table.c.component_id.in_(child_ids))
                            .with_for_update()
                        ).fetchall()
                        archived_children = sorted(
                            str(child.component_id) for child in child_rows if child.deleted_at is not None
                        )
                        if archived_children:
                            raise ComponentDependencyError(
                                f"Cannot restore {component_id}: pinned child(ren) "
                                f"{', '.join(archived_children)} are archived. Restore them first."
                            )

            return True

        except Exception as e:
            log_error(f"Error restoring component: {str(e)}")
            raise

    def list_components(
        self,
        component_type: Optional[ComponentType] = None,
        include_deleted: bool = False,
        limit: int = 20,
        offset: int = 0,
        exclude_component_ids: Optional[Set[str]] = None,
        user_id: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """List components with pagination.

        Args:
            component_type: Filter by type (agent|team|workflow).
            include_deleted: Include soft-deleted components.
            limit: Maximum number of items to return.
            offset: Number of items to skip.
            exclude_component_ids: Component IDs to exclude from results.
            user_id: If set, list the components this user may see: their own,
                unowned (shared) ones, and published ones.
            name: Exact-match filter on the component name; the returned total
                counts the filtered set.

        Returns:
            Tuple of (list of component dicts, total count).
        """
        try:
            table = self._get_table(table_type="components")
            if table is None:
                return [], 0

            with self.Session() as sess:
                # Build base where clause
                where_clauses = []
                if component_type is not None:
                    where_clauses.append(table.c.component_type == component_type.value)
                if user_id is not None:
                    # Same catalog visibility rule as get_component: own rows,
                    # unowned (shared) rows, and anything published.
                    where_clauses.append(
                        or_(
                            table.c.user_id == user_id,
                            table.c.user_id.is_(None),
                            # Live published rows only. Archiving is the off-switch:
                            # it withdraws a component from every other user even
                            # under include_deleted, which relaxes the tombstone
                            # filter for the OWNER's own history, never across owners.
                            and_(
                                table.c.current_version.isnot(None),
                                table.c.deleted_at.is_(None),
                            ),
                        )
                    )
                if not include_deleted:
                    where_clauses.append(table.c.deleted_at.is_(None))
                if exclude_component_ids:
                    where_clauses.append(table.c.component_id.notin_(exclude_component_ids))
                if name is not None:
                    where_clauses.append(table.c.name == name)

                # Get total count
                count_stmt = select(func.count()).select_from(table)
                for clause in where_clauses:
                    count_stmt = count_stmt.where(clause)
                total_count = sess.execute(count_stmt).scalar() or 0

                # Get paginated results
                stmt = select(table).order_by(
                    table.c.created_at.desc(),
                    table.c.component_id,
                )
                for clause in where_clauses:
                    stmt = stmt.where(clause)
                stmt = stmt.limit(limit).offset(offset)

                results = sess.execute(stmt).fetchall()
                return [dict(row._mapping) for row in results], total_count

        except Exception as e:
            log_error(f"Error listing components: {str(e)}")
            raise

    def create_component_with_config(
        self,
        component_id: str,
        component_type: ComponentType,
        name: Optional[str],
        config: Dict[str, Any],
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        label: Optional[str] = None,
        stage: str = "draft",
        notes: Optional[str] = None,
        links: Optional[List[Dict[str, Any]]] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Create a component with its initial config atomically.

        Args:
            component_id: Unique identifier.
            component_type: Type (agent|team|workflow).
            name: Display name.
            config: The config data.
            description: Optional description.
            metadata: Optional metadata dict.
            label: Optional config label.
            stage: "draft" or "published".
            notes: Optional notes.
            links: Optional list of links. Each must have child_version set.
            user_id: Owner to attribute the component to.

        Returns:
            Tuple of (component dict, config dict).

        Raises:
            ValueError: If component ID is already taken, invalid stage, or link missing child_version.
        """
        if stage not in {"draft", "published"}:
            raise ValueError(f"Invalid stage: {stage}")

        # Validate links have child_version
        if links:
            for link in links:
                if link.get("child_version") is None:
                    raise ValueError(f"child_version is required for link to {link['child_component_id']}")

        try:
            components_table = self._get_table(table_type="components", create_table_if_not_found=True)
            configs_table = self._get_table(table_type="component_configs", create_table_if_not_found=True)
            links_table = self._get_table(table_type="component_links", create_table_if_not_found=True)

            if components_table is None:
                raise ValueError("Components table not found")
            if configs_table is None:
                raise ValueError("Component configs table not found")

            with self.Session() as sess, sess.begin():
                # Check if component already exists
                existing = sess.execute(
                    select(components_table.c.component_id).where(components_table.c.component_id == component_id)
                ).scalar_one_or_none()

                if existing is not None:
                    # Generic wording: must not confirm another user's component exists
                    raise ValueError(f"Component ID {component_id} is not available")

                if links:
                    self._validate_links_in_session(sess, component_id, links, components_table, links_table)

                if stage == "published" and links:
                    # A published component pins published children (PIN_LINK_KINDS);
                    # a draft child can change in place under the pin. The versioned
                    # edit paths bind children with require_published, but a direct
                    # create_component_with_config (and versions=False creates) reach
                    # here without that check.
                    for link in links:
                        if link.get("link_kind") not in PIN_LINK_KINDS:
                            continue
                        child_stage = sess.execute(
                            select(configs_table.c.stage).where(
                                configs_table.c.component_id == link["child_component_id"],
                                configs_table.c.version == link["child_version"],
                            )
                        ).scalar()
                        if child_stage != "published":
                            raise ComponentDependencyError(
                                f"Cannot create {component_id} as published: pinned "
                                f"{link['link_kind']} '{link['child_component_id']}' "
                                f"v{link['child_version']} is {child_stage or 'missing'}; "
                                "publish the child first."
                            )

                # Check label uniqueness
                if label is not None:
                    existing_label = sess.execute(
                        select(configs_table.c.version).where(
                            configs_table.c.component_id == component_id,
                            configs_table.c.label == label,
                        )
                    ).first()
                    if existing_label:
                        raise ValueError(f"Label '{label}' already exists for {component_id}")

                now = int(time.time())
                version = 1

                # Create component
                sess.execute(
                    components_table.insert().values(
                        component_id=component_id,
                        component_type=component_type.value,
                        name=name,
                        user_id=user_id,
                        description=description,
                        metadata=metadata,
                        current_version=version if stage == "published" else None,
                        created_at=now,
                    )
                )

                # Create initial config
                sess.execute(
                    configs_table.insert().values(
                        component_id=component_id,
                        version=version,
                        label=label,
                        stage=stage,
                        config=config,
                        notes=notes,
                        created_at=now,
                    )
                )

                # Create links if provided
                if links and links_table is not None:
                    for link in links:
                        sess.execute(
                            links_table.insert().values(
                                parent_component_id=component_id,
                                parent_version=version,
                                link_kind=link["link_kind"],
                                link_key=link["link_key"],
                                child_component_id=link["child_component_id"],
                                child_version=link["child_version"],
                                position=link["position"],
                                meta=link.get("meta"),
                                created_at=now,
                            )
                        )

                if stage == "published" and links and links_table is not None:
                    # The pin checks above are check-then-write: they run before
                    # any row is written, take no lock, and a child archived in
                    # the gap would leave a brand-new PUBLISHED parent pinning
                    # an archived child - the state upsert_config's publish gate
                    # raises to prevent. Re-assert the liveness half here, where
                    # the write lock is held, so a lost race rolls the creation
                    # back rather than committing that state.
                    for link in links:
                        if link.get("link_kind") not in PIN_LINK_KINDS:
                            continue
                        child_deleted_at = sess.execute(
                            select(components_table.c.deleted_at)
                            .where(components_table.c.component_id == link["child_component_id"])
                            .with_for_update()
                        ).scalar()
                        if child_deleted_at is not None:
                            raise ComponentDependencyError(
                                f"Cannot publish {component_id} v{version}: pinned "
                                f"{link['link_kind']} '{link['child_component_id']}' is archived; "
                                "restore it first."
                            )

                # Both halves of the answer are read inside the transaction that
                # wrote them, and without the archived filter. A read taken after
                # the commit can be overtaken by an archive on another connection,
                # and reporting a committed creation as a failure hands the caller
                # a 4xx for a write that landed.
                component_row = sess.execute(
                    select(components_table).where(components_table.c.component_id == component_id)
                ).fetchone()
                config_row = sess.execute(
                    select(configs_table).where(
                        configs_table.c.component_id == component_id,
                        configs_table.c.version == version,
                    )
                ).fetchone()

                if component_row is None:
                    raise ValueError(f"Failed to get component {component_id} after creation")
                if config_row is None:
                    raise ValueError(f"Failed to get config for {component_id} after creation")

                component = dict(component_row._mapping)
                config_result = dict(config_row._mapping)

            return component, config_result

        except Exception as e:
            log_error(f"Error creating component with config: {str(e)}")
            raise

    # --- Config ---
    def get_config(
        self,
        component_id: str,
        version: Optional[int] = None,
        label: Optional[str] = None,
        include_deleted: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Get a config by component ID and version or label.

        Args:
            component_id: The component ID.
            version: Specific version number. If None, uses current or latest draft.
            label: Config label to lookup. Ignored if version is provided.
            include_deleted: Also return a tombstoned version (explicit version only).

        Returns:
            Config dictionary or None if not found.
        """
        try:
            configs_table = self._get_table(table_type="component_configs")
            components_table = self._get_table(table_type="components")

            if configs_table is None or components_table is None:
                return None

            with self.Session() as sess:
                # Always verify component exists and is not deleted
                component_row = (
                    sess.execute(
                        select(components_table.c.current_version, components_table.c.component_id).where(
                            components_table.c.component_id == component_id,
                            components_table.c.deleted_at.is_(None),
                        )
                    )
                    .mappings()
                    .one_or_none()
                )

                if component_row is None:
                    return None

                current_version = component_row["current_version"]

                if version is not None:
                    stmt = select(configs_table).where(
                        configs_table.c.component_id == component_id,
                        configs_table.c.version == version,
                    )
                    if not include_deleted:
                        stmt = stmt.where(configs_table.c.stage != DELETED_CONFIG_STAGE)
                elif label is not None:
                    stmt = select(configs_table).where(
                        configs_table.c.component_id == component_id,
                        configs_table.c.label == label,
                        configs_table.c.stage != DELETED_CONFIG_STAGE,
                    )
                elif current_version is not None:
                    # Use the current published version. The stage filter keeps
                    # a corrupted pointer (naming a tombstoned version) from
                    # serving the dead payload; the read returns None instead,
                    # matching get_current_config.
                    stmt = select(configs_table).where(
                        configs_table.c.component_id == component_id,
                        configs_table.c.version == current_version,
                        configs_table.c.stage != DELETED_CONFIG_STAGE,
                    )
                else:
                    # No current_version set (draft only) - get the latest visible version
                    stmt = (
                        select(configs_table)
                        .where(
                            configs_table.c.component_id == component_id,
                            configs_table.c.stage != DELETED_CONFIG_STAGE,
                        )
                        .order_by(configs_table.c.version.desc())
                        .limit(1)
                    )

                result = sess.execute(stmt).fetchone()
                return dict(result._mapping) if result else None

        except Exception as e:
            log_error(f"Error getting config: {str(e)}")
            raise

    def get_current_config(self, component_id: str) -> Optional[Dict[str, Any]]:
        """The current published config, or None when nothing is published."""
        component = self.get_component(component_id)
        if component is None or component.get("current_version") is None:
            return None
        return self.get_config(component_id, version=component["current_version"])

    def get_latest_config(self, component_id: str) -> Optional[Dict[str, Any]]:
        """The latest visible (non-tombstoned) config version, draft or published."""
        try:
            configs_table = self._get_table(table_type="component_configs")
            components_table = self._get_table(table_type="components")
            if configs_table is None or components_table is None:
                return None
            with self.Session() as sess:
                exists = sess.execute(
                    select(components_table.c.component_id).where(
                        components_table.c.component_id == component_id,
                        components_table.c.deleted_at.is_(None),
                    )
                ).fetchone()
                if exists is None:
                    return None
                result = sess.execute(
                    select(configs_table)
                    .where(
                        configs_table.c.component_id == component_id,
                        configs_table.c.stage != DELETED_CONFIG_STAGE,
                    )
                    .order_by(configs_table.c.version.desc())
                    .limit(1)
                ).fetchone()
                return dict(result._mapping) if result else None
        except Exception as e:
            log_error(f"Error getting latest config: {str(e)}")
            raise

    def upsert_config(
        self,
        component_id: str,
        config: Optional[Dict[str, Any]] = None,
        version: Optional[int] = None,
        label: Optional[str] = None,
        stage: Optional[str] = None,
        notes: Optional[str] = None,
        links: Optional[List[Dict[str, Any]]] = None,
        expected_latest_version: Optional[int] = None,
        expected_current_version: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create or update a config version for a component.

        Rules:
            - Draft configs can be edited freely
            - Published configs are immutable
            - Publishing a config automatically sets it as current_version

        Args:
            component_id: The component ID.
            config: The config data. Required for create, optional for update.
            version: If None, creates new version. If provided, updates that version.
            label: Optional human-readable label.
            stage: "draft" or "published". Defaults to "draft" for new configs.
            notes: Optional notes.
            links: Optional list of links. Each link must have child_version set.
            user_id: When set, the write applies only if this user owns the
                component; checked on the component row inside the write
                transaction.

        Returns:
            Created/updated config dictionary.

        Raises:
            ValueError: If component doesn't exist, version not found, label conflict,
                        or attempting to update a published config.
        """
        if stage is not None and stage not in {"draft", "published"}:
            raise ValueError(f"Invalid stage: {stage}")

        try:
            configs_table = self._get_table(table_type="component_configs", create_table_if_not_found=True)
            components_table = self._get_table(table_type="components")
            links_table = self._get_table(table_type="component_links", create_table_if_not_found=True)

            if components_table is None:
                raise ValueError("Components table not found")
            if configs_table is None:
                raise ValueError("Component configs table not found")

            with self.Session() as sess, sess.begin():
                # Verify component exists and is not archived
                component = sess.execute(
                    select(
                        components_table.c.component_id, components_table.c.deleted_at, components_table.c.user_id
                    ).where(components_table.c.component_id == component_id)
                ).fetchone()

                if component is None:
                    raise ValueError(f"Component {component_id} not found")
                # Writes are owner-scoped always. Checked before the archived
                # verdict and answering exactly as a missing component, so a
                # scoped caller learns nothing about a row it does not own.
                if user_id is not None and component.user_id != user_id:
                    raise ValueError(f"Component {component_id} not found")
                if component.deleted_at is not None:
                    raise ComponentArchivedError(
                        f"Component {component_id} is archived; restore it explicitly before writing to it"
                    )

                # Optional compare-and-set against the latest VISIBLE version:
                # a mismatch means someone else wrote since the caller read.
                if expected_latest_version is not None:
                    latest_visible = sess.execute(
                        select(configs_table.c.version)
                        .where(
                            configs_table.c.component_id == component_id,
                            configs_table.c.stage != DELETED_CONFIG_STAGE,
                        )
                        .order_by(configs_table.c.version.desc())
                        .limit(1)
                    ).scalar()
                    if latest_visible != expected_latest_version:
                        raise ComponentVersionConflictError(
                            f"Component {component_id} latest version is {latest_visible}, "
                            f"expected {expected_latest_version}"
                        )

                # Links must point at real, unarchived children and must not
                # close a cycle. The published-parents-pin-published-children
                # rule is enforced below, at the promote transition.
                if links:
                    self._validate_links_in_session(sess, component_id, links, components_table, links_table)

                # Label uniqueness check (a tombstoned version frees its label)
                if label is not None:
                    label_query = select(configs_table.c.version).where(
                        configs_table.c.component_id == component_id,
                        configs_table.c.label == label,
                        configs_table.c.stage != DELETED_CONFIG_STAGE,
                    )
                    if version is not None:
                        label_query = label_query.where(configs_table.c.version != version)

                    if sess.execute(label_query).first():
                        raise ValueError(f"Label '{label}' already exists for {component_id}")

                # Validate links have child_version
                if links:
                    for link in links:
                        if link.get("child_version") is None:
                            raise ValueError(f"child_version is required for link to {link['child_component_id']}")

                if version is None:
                    if config is None:
                        raise ValueError("config is required when creating a new version")

                    # Default to draft for new configs
                    if stage is None:
                        stage = "draft"

                    # High-water over EVERY row including tombstones: numbers are
                    # never recycled into a history someone may still cite.
                    max_version = sess.execute(
                        select(configs_table.c.version)
                        .where(configs_table.c.component_id == component_id)
                        .order_by(configs_table.c.version.desc())
                        .limit(1)
                    ).scalar()

                    final_version = (max_version or 0) + 1

                    try:
                        sess.execute(
                            configs_table.insert().values(
                                component_id=component_id,
                                version=final_version,
                                label=label,
                                stage=stage,
                                config=config,
                                notes=notes,
                                created_at=int(time.time()),
                            )
                        )
                    except IntegrityError as exc:
                        # Two appends raced for one number; the (component_id,
                        # version) primary key is the backstop.
                        raise ComponentVersionConflictError(
                            f"Concurrent append on {component_id}: version {final_version} was taken"
                        ) from exc

                    if expected_latest_version is not None:
                        # Re-verify the guard AFTER the insert: the pre-check
                        # and the insert are separate statements, so a raced
                        # append can land between them (both writers reading
                        # the same latest). Exactly one row can be the direct
                        # successor of the expected version; a loser removes
                        # its own row and conflicts.
                        prior = sess.execute(
                            select(configs_table.c.version)
                            .where(
                                configs_table.c.component_id == component_id,
                                configs_table.c.stage != DELETED_CONFIG_STAGE,
                                configs_table.c.version < final_version,
                            )
                            .order_by(configs_table.c.version.desc())
                            .limit(1)
                        ).scalar()
                        if prior != expected_latest_version:
                            sess.execute(
                                configs_table.delete().where(
                                    configs_table.c.component_id == component_id,
                                    configs_table.c.version == final_version,
                                )
                            )
                            raise ComponentVersionConflictError(
                                f"Component {component_id} latest version is {prior}, "
                                f"expected {expected_latest_version}"
                            )
                else:
                    existing = sess.execute(
                        select(configs_table.c.version, configs_table.c.stage).where(
                            configs_table.c.component_id == component_id,
                            configs_table.c.version == version,
                        )
                    ).fetchone()

                    if existing is None or existing.stage == DELETED_CONFIG_STAGE:
                        raise ValueError(f"Config {component_id} v{version} not found")

                    # Published configs are immutable
                    if existing.stage == "published":
                        raise ValueError(f"Cannot update published config {component_id} v{version}")

                    # Build update dict with only provided fields
                    updates: Dict[str, Any] = {"updated_at": int(time.time())}
                    if label is not None:
                        updates["label"] = label
                    if stage is not None:
                        updates["stage"] = stage
                    if config is not None:
                        updates["config"] = config
                    if notes is not None:
                        updates["notes"] = notes

                    sess.execute(
                        configs_table.update()
                        .where(
                            configs_table.c.component_id == component_id,
                            configs_table.c.version == version,
                        )
                        .values(**updates)
                    )
                    final_version = version

                # The archive precondition at the top is check-then-write:
                # SQLite opens its transaction at the first write, so an archive
                # can commit in the gap. The config row is written by now, which
                # holds the write lock, so this re-read is final - an archive
                # that got in first rolls the whole edit back instead of letting
                # it mutate a row that is already immutable.
                archived_at = sess.execute(
                    select(components_table.c.deleted_at).where(components_table.c.component_id == component_id)
                ).scalar()
                if archived_at is not None:
                    raise ComponentArchivedError(
                        f"Component {component_id} is archived; restore it explicitly before writing to it"
                    )

                if links is not None and links_table is not None:
                    sess.execute(
                        links_table.delete().where(
                            links_table.c.parent_component_id == component_id,
                            links_table.c.parent_version == final_version,
                        )
                    )
                    for link in links:
                        sess.execute(
                            links_table.insert().values(
                                parent_component_id=component_id,
                                parent_version=final_version,
                                link_kind=link["link_kind"],
                                link_key=link["link_key"],
                                child_component_id=link["child_component_id"],
                                child_version=link["child_version"],
                                position=link["position"],
                                meta=link.get("meta"),
                                created_at=int(time.time()),
                            )
                        )

                # Determine final stage (could be from update or create)
                final_stage = stage if stage is not None else (existing.stage if version is not None else "draft")

                if final_stage == "published":
                    # A published parent pins published children: a draft child
                    # can change in place under the pin. One gate here covers
                    # every promote surface (Studio publish, edit+publish, REST
                    # PATCH stage). Only member/step links carry rebuild pins;
                    # other link kinds pass through.
                    if links_table is not None:
                        link_rows = sess.execute(
                            select(
                                links_table.c.child_component_id,
                                links_table.c.child_version,
                                links_table.c.link_kind,
                            ).where(
                                links_table.c.parent_component_id == component_id,
                                links_table.c.parent_version == final_version,
                            )
                        ).fetchall()
                        for link_row in link_rows:
                            if link_row.link_kind not in PIN_LINK_KINDS:
                                continue
                            child_stage = sess.execute(
                                select(configs_table.c.stage).where(
                                    configs_table.c.component_id == link_row.child_component_id,
                                    configs_table.c.version == link_row.child_version,
                                )
                            ).scalar()
                            if child_stage != "published":
                                raise ComponentDependencyError(
                                    f"Cannot publish {component_id} v{final_version}: pinned "
                                    f"{link_row.link_kind} '{link_row.child_component_id}' "
                                    f"v{link_row.child_version} is {child_stage or 'missing'}; "
                                    "publish the child first."
                                )
                            # A pinned child must also still be LIVE. A config
                            # keeps its published stage after its component is
                            # archived, so a stage-only gate lets a version go
                            # live pinning an archived child, and the parent
                            # then loads with that member missing. The lock is a
                            # no-op on SQLite and a row lock on Postgres, where
                            # it serializes this against a concurrent archive.
                            # A child with no catalog row is code-defined and
                            # passes, exactly as the link validator allows.
                            child_deleted_at = sess.execute(
                                select(components_table.c.deleted_at)
                                .where(components_table.c.component_id == link_row.child_component_id)
                                .with_for_update()
                            ).scalar()
                            if child_deleted_at is not None:
                                raise ComponentDependencyError(
                                    f"Cannot publish {component_id} v{final_version}: pinned "
                                    f"{link_row.link_kind} '{link_row.child_component_id}' is archived; "
                                    "restore it first."
                                )
                    # Publishing moves the pointer and re-projects the config's
                    # denormalized identity onto the row in one transaction, so
                    # listings never show a stale name for the live version.
                    projection: Dict[str, Any] = {"current_version": final_version, "updated_at": int(time.time())}
                    published_config = config
                    if published_config is None and version is not None:
                        stored = sess.execute(
                            select(configs_table.c.config).where(
                                configs_table.c.component_id == component_id,
                                configs_table.c.version == final_version,
                            )
                        ).scalar()
                        published_config = stored if isinstance(stored, dict) else None
                    if isinstance(published_config, dict):
                        projection.update(project_config_identity(published_config))
                    projection_update = (
                        components_table.update()
                        .where(
                            components_table.c.component_id == component_id,
                            components_table.c.deleted_at.is_(None),
                        )
                        .values(**projection)
                    )
                    if expected_current_version is not None:
                        # CAS on the pointer being replaced: the guard rides the
                        # UPDATE so two publishers expecting the same current
                        # version cannot both win.
                        projection_update = projection_update.where(
                            current_version_guard_clause(components_table.c.current_version, expected_current_version)
                        )
                    projection_result = sess.execute(projection_update)
                    if projection_result.rowcount == 0:
                        # Zero rows: the row was archived underneath this
                        # publish, or the CAS guard lost. Re-read to answer
                        # which, holding the write transaction.
                        still_live = sess.execute(
                            select(components_table.c.component_id).where(
                                components_table.c.component_id == component_id,
                                components_table.c.deleted_at.is_(None),
                            )
                        ).fetchone()
                        if still_live is None:
                            raise ComponentArchivedError(
                                f"Component {component_id} is archived; restore it explicitly before writing to it"
                            )
                        if expected_current_version is not None:
                            raise ComponentVersionConflictError(
                                f"Component {component_id} current version changed; expected {expected_current_version}"
                            )

                # The answer is built inside the transaction that wrote it. A
                # read taken after the commit can be overtaken by an archive on
                # another connection, and reporting a committed publish as a
                # failure hands the caller a 4xx for a write that landed.
                written = sess.execute(
                    select(configs_table).where(
                        configs_table.c.component_id == component_id,
                        configs_table.c.version == final_version,
                    )
                ).fetchone()
                if written is None:
                    raise ValueError(f"Failed to get config {component_id} v{final_version} after upsert")
                result = dict(written._mapping)

            return result

        except Exception as e:
            log_error(f"Error upserting config: {str(e)}")
            raise

    def delete_config(
        self,
        component_id: str,
        version: int,
        user_id: Optional[str] = None,
    ) -> bool:
        """Tombstone a specific config version. Its number is never reused.

        Only draft configs can be deleted. Published configs are immutable.
        Never the current version, never the last visible version, and never a
        version an ACTIVE parent pins - a parent that is archived, or whose own
        version is tombstoned, holds no pin.

        Args:
            component_id: The component ID.
            version: The version to delete.
            user_id: When set, the delete applies only if this user owns the
                component; checked on the component row inside the write
                transaction. A foreign or shared row answers False, the same
                as a missing version.

        Returns:
            True if deleted, False if not found (or already tombstoned).

        Raises:
            ComponentDraftRequiredError: If the version is published.
            ComponentArchivedError: If the component is archived; its history is
                frozen so restore brings every version back.
            ComponentLastConfigError: If it is the last visible version.
            ComponentDependencyError: If an active parent pins this version.
            ValueError: If it is the current version.
        """
        try:
            configs_table = self._get_table(table_type="component_configs")
            links_table = self._get_table(table_type="component_links")
            components_table = self._get_table(table_type="components")

            if configs_table is None or components_table is None:
                return False

            with self.Session() as sess, sess.begin():
                # The component row is read first, locked (a row lock on
                # Postgres, a no-op on SQLite), doing two jobs: the owner
                # scope must answer before ANY stage verdict - a foreign probe
                # learns nothing, not even that a version is published - and
                # the lock serializes this call against a concurrent publish
                # of the same component.
                component_row = sess.execute(
                    select(
                        components_table.c.current_version,
                        components_table.c.user_id,
                        components_table.c.deleted_at,
                    )
                    .where(components_table.c.component_id == component_id)
                    .with_for_update()
                ).fetchone()

                # Writes are owner-scoped always. A foreign or shared row
                # answers the same False a missing version answers, inside
                # the write transaction.
                if user_id is not None and (component_row is None or component_row.user_id != user_id):
                    return False

                # An archived component's history is frozen: archive reserves
                # the id and keeps every version so restore can bring them
                # back, which a tombstoned draft would silently break. Every
                # other writer refuses an archived row; this one is the last.
                if component_row is not None and component_row.deleted_at is not None:
                    raise ComponentArchivedError(
                        f"Component {component_id} is archived; restore it explicitly before writing to it"
                    )

                # Get config stage and check if it's current
                config_row = sess.execute(
                    select(configs_table.c.stage).where(
                        configs_table.c.component_id == component_id,
                        configs_table.c.version == version,
                    )
                ).fetchone()

                if config_row is None or config_row.stage == DELETED_CONFIG_STAGE:
                    return False

                if config_row.stage == "published":
                    raise ComponentDraftRequiredError(
                        f"Cannot delete published config {component_id} v{version}; only drafts are deletable"
                    )

                if component_row is not None and component_row.current_version == version:
                    raise ValueError(f"Cannot delete current config {component_id} v{version}")

                # A component keeps at least one visible version
                visible = sess.execute(
                    select(func.count())
                    .select_from(configs_table)
                    .where(
                        configs_table.c.component_id == component_id,
                        configs_table.c.stage != DELETED_CONFIG_STAGE,
                    )
                ).scalar()
                if (visible or 0) <= 1:
                    raise ComponentLastConfigError(f"Cannot delete the last visible config of {component_id}")

                # Another ACTIVE component may pin this exact version. A parent
                # that is archived, or whose own version is tombstoned, has no
                # claim left: it cannot dispatch, so holding a draft hostage
                # would leave the only release destroying the parent's history.
                # The release must be PROVEN, never assumed from an absent row -
                # a link whose parent config row is missing keeps its pin, since
                # nothing there says the parent is gone.
                pinned_stmt = None
                if links_table is not None:
                    archived_parent = (
                        select(components_table.c.component_id)
                        .where(
                            components_table.c.component_id == links_table.c.parent_component_id,
                            components_table.c.deleted_at.is_not(None),
                        )
                        .correlate(links_table)
                        .exists()
                    )
                    tombstoned_parent_version = (
                        select(configs_table.c.version)
                        .where(
                            configs_table.c.component_id == links_table.c.parent_component_id,
                            configs_table.c.version == links_table.c.parent_version,
                            configs_table.c.stage == DELETED_CONFIG_STAGE,
                        )
                        .correlate(links_table)
                        .exists()
                    )
                    pinned_stmt = select(links_table.c.parent_component_id).where(
                        links_table.c.child_component_id == component_id,
                        links_table.c.child_version == version,
                        ~archived_parent,
                        ~tombstoned_parent_version,
                    )
                    pinned_by = sess.execute(pinned_stmt).fetchall()
                    if pinned_by:
                        parents = sorted({r.parent_component_id for r in pinned_by if r.parent_component_id})
                        raise ComponentDependencyError(
                            f"Cannot delete {component_id} v{version}: pinned by {', '.join(parents)}"
                        )

                # Tombstone: keep the row so the version number is never reused
                # and free its label. The draft predicate rides the UPDATE -
                # every read above is check-then-write, and a publish of this
                # very version committing in the gap would otherwise leave the
                # live pointer naming a deleted config.
                result = sess.execute(
                    configs_table.update()
                    .where(
                        configs_table.c.component_id == component_id,
                        configs_table.c.version == version,
                        configs_table.c.stage == "draft",
                    )
                    .values(stage=DELETED_CONFIG_STAGE, label=None, updated_at=int(time.time()))
                )
                if result.rowcount == 0:
                    stage_now = sess.execute(
                        select(configs_table.c.stage).where(
                            configs_table.c.component_id == component_id,
                            configs_table.c.version == version,
                        )
                    ).scalar()
                    if stage_now is None or stage_now == DELETED_CONFIG_STAGE:
                        return False
                    raise ComponentDraftRequiredError(
                        f"Cannot delete published config {component_id} v{version}; only drafts are deletable"
                    )

                # The other three guards ride the same transaction: the write
                # above holds the write lock, so these re-reads see every
                # committed writer and nothing can move underneath them. A
                # violation rolls the tombstone back.
                current_after = sess.execute(
                    select(components_table.c.current_version).where(components_table.c.component_id == component_id)
                ).scalar()
                if current_after == version:
                    raise ValueError(f"Cannot delete current config {component_id} v{version}")

                visible_after = sess.execute(
                    select(func.count())
                    .select_from(configs_table)
                    .where(
                        configs_table.c.component_id == component_id,
                        configs_table.c.stage != DELETED_CONFIG_STAGE,
                    )
                ).scalar()
                if (visible_after or 0) < 1:
                    raise ComponentLastConfigError(f"Cannot delete the last visible config of {component_id}")

                if pinned_stmt is not None:
                    pinned_after = sess.execute(pinned_stmt).fetchall()
                    if pinned_after:
                        parents = sorted({r.parent_component_id for r in pinned_after if r.parent_component_id})
                        raise ComponentDependencyError(
                            f"Cannot delete {component_id} v{version}: pinned by {', '.join(parents)}"
                        )

                # Drop the version's outgoing links last: nothing below can
                # refuse the delete now.
                if links_table is not None:
                    sess.execute(
                        links_table.delete().where(
                            links_table.c.parent_component_id == component_id,
                            links_table.c.parent_version == version,
                        )
                    )

            return True

        except Exception as e:
            log_error(f"Error deleting config: {str(e)}")
            raise

    def list_configs(
        self,
        component_id: str,
        include_config: bool = False,
        include_deleted: bool = False,
    ) -> List[Dict[str, Any]]:
        """List all config versions for a component.

        Args:
            component_id: The component ID.
            include_config: If True, include full config blob. Otherwise just metadata.

        Returns:
            List of config dictionaries, newest first.
            Returns empty list if component not found or deleted.
        """
        try:
            configs_table = self._get_table(table_type="component_configs")
            components_table = self._get_table(table_type="components")

            if configs_table is None or components_table is None:
                return []

            with self.Session() as sess:
                # Verify component exists and is not deleted
                exists = sess.execute(
                    select(components_table.c.component_id).where(
                        components_table.c.component_id == component_id,
                        components_table.c.deleted_at.is_(None),
                    )
                ).fetchone()

                if exists is None:
                    return []

                # Select columns based on include_config flag
                if include_config:
                    stmt = select(configs_table)
                else:
                    stmt = select(
                        configs_table.c.component_id,
                        configs_table.c.version,
                        configs_table.c.label,
                        configs_table.c.stage,
                        configs_table.c.notes,
                        configs_table.c.created_at,
                        configs_table.c.updated_at,
                    )

                stmt = stmt.where(configs_table.c.component_id == component_id)
                if not include_deleted:
                    stmt = stmt.where(configs_table.c.stage != DELETED_CONFIG_STAGE)
                stmt = stmt.order_by(configs_table.c.version.desc())

                results = sess.execute(stmt).fetchall()
                return [dict(row._mapping) for row in results]

        except Exception as e:
            log_error(f"Error listing configs: {str(e)}")
            raise

    def set_current_version(
        self,
        component_id: str,
        version: int,
        expected_current_version: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> bool:
        """Set a specific published version as current.

        Only published configs can be set as current. This is used for
        rollback scenarios where you want to switch to a previous
        published version.

        Args:
            component_id: The component ID.
            version: The version to set as current (must be published).
            user_id: When set, the pointer moves only if this user owns the
                component; the predicate rides the UPDATE itself. A foreign
                or shared row answers False, the same as a missing component.

        Returns:
            True if successful, False if component or version not found.

        Raises:
            ValueError: If attempting to set a draft config as current.
            ComponentDependencyError: If the version pins an archived child.
        """
        try:
            configs_table = self._get_table(table_type="component_configs")
            components_table = self._get_table(table_type="components")
            links_table = self._get_table(table_type="component_links")

            if configs_table is None or components_table is None:
                return False

            with self.Session() as sess, sess.begin():
                # Verify component exists and is not deleted
                component_row = sess.execute(
                    select(components_table.c.component_id, components_table.c.user_id).where(
                        components_table.c.component_id == component_id,
                        components_table.c.deleted_at.is_(None),
                    )
                ).fetchone()

                if component_row is None:
                    return False

                # Writes are owner-scoped always: a foreign or shared row
                # answers the same False a missing component answers.
                if user_id is not None and component_row.user_id != user_id:
                    return False

                # Verify version exists and get stage
                stage = sess.execute(
                    select(configs_table.c.stage).where(
                        configs_table.c.component_id == component_id,
                        configs_table.c.version == version,
                    )
                ).fetchone()

                if stage is None:
                    return False

                # Only published configs can be set as current
                if stage.stage != "published":
                    raise ValueError(
                        f"Cannot set draft config {component_id} v{version} as current. "
                        "Only published configs can be current."
                    )

                if expected_current_version is not None:
                    pointer = sess.execute(
                        select(components_table.c.current_version).where(
                            components_table.c.component_id == component_id
                        )
                    ).scalar()
                    if not current_version_matches(pointer, expected_current_version):
                        raise ComponentVersionConflictError(
                            f"Component {component_id} current version is {pointer}, "
                            f"expected {expected_current_version}"
                        )

                # Update pointer. The guards ride the UPDATE itself: the
                # pre-reads give the friendly messages, these predicates give
                # correctness under concurrent writers. deleted_at is
                # re-asserted here because the liveness pre-read above is
                # check-then-write: a concurrent archive committing in the gap
                # must make this a no-op, never a pointer move onto an
                # archived (immutable) row. The owner scope rides the same way,
                # so a delete-and-recreate under a new owner in that gap is a
                # no-op too, never a pointer move on someone else's row.
                pointer_update = (
                    components_table.update()
                    .where(
                        components_table.c.component_id == component_id,
                        components_table.c.deleted_at.is_(None),
                    )
                    .values(current_version=version, updated_at=int(time.time()))
                )
                if user_id is not None:
                    pointer_update = pointer_update.where(components_table.c.user_id == user_id)
                if expected_current_version is not None:
                    pointer_update = pointer_update.where(
                        current_version_guard_clause(components_table.c.current_version, expected_current_version)
                    )
                result = sess.execute(pointer_update)
                if result.rowcount == 0:
                    # Zero rows: the row was archived or changed owner
                    # underneath us, or the CAS guard lost. Re-read to answer
                    # which (holding the write transaction, so the answer
                    # cannot move again), under the same scope the UPDATE used.
                    still_live_stmt = select(components_table.c.component_id).where(
                        components_table.c.component_id == component_id,
                        components_table.c.deleted_at.is_(None),
                    )
                    if user_id is not None:
                        still_live_stmt = still_live_stmt.where(components_table.c.user_id == user_id)
                    still_live = sess.execute(still_live_stmt).fetchone()
                    if still_live is None:
                        # Concurrent archive won: same verdict as the pre-check.
                        return False
                    raise ComponentVersionConflictError(
                        f"Component {component_id} current version changed; expected {expected_current_version}"
                    )

                # The live version must not pin an archived child: the component
                # would resolve and dispatch with that member missing. Stage
                # alone does not say this - a config keeps its published stage
                # after its component is archived. Checked after the pointer
                # write so the guard rides the transaction holding the write
                # lock; a violation rolls the pointer move back. Children with
                # no catalog row are code-defined and pass.
                if links_table is not None:
                    pinned = sess.execute(
                        select(links_table.c.child_component_id).where(
                            links_table.c.parent_component_id == component_id,
                            links_table.c.parent_version == version,
                            links_table.c.link_kind.in_(PIN_LINK_KINDS),
                        )
                    ).fetchall()
                    child_ids = {row.child_component_id for row in pinned if row.child_component_id}
                    if child_ids:
                        child_rows = sess.execute(
                            select(components_table.c.component_id, components_table.c.deleted_at)
                            .where(components_table.c.component_id.in_(child_ids))
                            .with_for_update()
                        ).fetchall()
                        archived_children = sorted(
                            str(row.component_id) for row in child_rows if row.deleted_at is not None
                        )
                        if archived_children:
                            raise ComponentDependencyError(
                                f"Cannot make {component_id} v{version} current: pinned child(ren) "
                                f"{', '.join(archived_children)} are archived. Restore them first."
                            )

            log_debug(f"Set {component_id} current version to {version}")
            return True

        except Exception as e:
            log_error(f"Error setting current version: {str(e)}")
            raise

    # --- Component Links ---
    def get_links(
        self,
        component_id: str,
        version: int,
        link_kind: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get links for a config version.

        Args:
            component_id: The component ID.
            version: The config version.
            link_kind: Optional filter by link kind (member|step).

        Returns:
            List of link dictionaries, ordered by position.
        """
        try:
            table = self._get_table(table_type="component_links")
            if table is None:
                return []

            with self.Session() as sess:
                stmt = (
                    select(table)
                    .where(
                        table.c.parent_component_id == component_id,
                        table.c.parent_version == version,
                    )
                    .order_by(table.c.position)
                )
                if link_kind is not None:
                    stmt = stmt.where(table.c.link_kind == link_kind)

                results = sess.execute(stmt).fetchall()
                return [dict(row._mapping) for row in results]

        except Exception as e:
            log_error(f"Error getting links: {str(e)}")
            raise

    def get_dependents(
        self,
        component_id: str,
        version: Optional[int] = None,
        active_parents_only: bool = False,
        parent_user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Find all components that reference this component.

        Args:
            component_id: The component ID to find dependents of.
            version: Optional specific version. If None, finds links to any version.
            active_parents_only: Only count links whose parent component is not
                archived and whose parent version is not tombstoned.
            parent_user_id: When set, count only parents this user owns, plus
                unowned (shared) ones. Used where the answer decides an
                owner-scoped write: a parent the caller can neither see nor
                edit must not veto that caller's own delete.

        Returns:
            List of link dictionaries showing what depends on this component.
        """
        try:
            table = self._get_table(table_type="component_links")
            if table is None:
                return []
            components_table = self._get_table(table_type="components")
            configs_table = self._get_table(table_type="component_configs")

            with self.Session() as sess:
                return self._dependents_in_session(
                    sess,
                    table,
                    components_table,
                    configs_table,
                    component_id,
                    version=version,
                    active_parents_only=active_parents_only,
                    parent_user_id=parent_user_id,
                )

        except Exception as e:
            log_error(f"Error getting dependents: {str(e)}")
            raise

    def _dependents_in_session(
        self,
        sess,
        links_table,
        components_table,
        configs_table,
        component_id: str,
        version: Optional[int] = None,
        active_parents_only: bool = False,
        parent_user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """The dependents read, run on a session the caller already holds.

        The tables are passed in because the caller may hold an open
        transaction on this scoped session; _get_table would try to begin a
        second one.
        """
        if links_table is None:
            return []
        stmt = select(links_table).where(links_table.c.child_component_id == component_id)
        if version is not None:
            stmt = stmt.where(links_table.c.child_version == version)
        if active_parents_only and components_table is not None and configs_table is not None:
            stmt = (
                stmt.join(
                    components_table,
                    components_table.c.component_id == links_table.c.parent_component_id,
                )
                .join(
                    configs_table,
                    and_(
                        configs_table.c.component_id == links_table.c.parent_component_id,
                        configs_table.c.version == links_table.c.parent_version,
                    ),
                )
                .where(
                    components_table.c.deleted_at.is_(None),
                    configs_table.c.stage != DELETED_CONFIG_STAGE,
                )
            )
            if parent_user_id is not None:
                stmt = stmt.where(
                    or_(
                        components_table.c.user_id == parent_user_id,
                        components_table.c.user_id.is_(None),
                    )
                )
        elif parent_user_id is not None and components_table is not None:
            # The scope needs the parent row even when liveness does not.
            stmt = stmt.join(
                components_table,
                components_table.c.component_id == links_table.c.parent_component_id,
            ).where(
                or_(
                    components_table.c.user_id == parent_user_id,
                    components_table.c.user_id.is_(None),
                )
            )

        results = sess.execute(stmt).fetchall()
        # The join widens the row; keep only the link columns.
        return [{k: v for k, v in row._mapping.items() if k in links_table.c.keys()} for row in results]

    def _refuse_if_dependents(
        self,
        sess,
        links_table,
        components_table,
        configs_table,
        component_id: str,
        active_parents_only: bool,
        parent_user_id: Optional[str] = None,
    ) -> None:
        """Raise ComponentDependencyError when another component pins this one."""
        dependents = self._dependents_in_session(
            sess,
            links_table,
            components_table,
            configs_table,
            component_id,
            active_parents_only=active_parents_only,
            parent_user_id=parent_user_id,
        )
        if dependents:
            parents = sorted({str(d["parent_component_id"]) for d in dependents if d.get("parent_component_id")})
            raise ComponentDependencyError(
                f"Cannot delete {component_id}: referenced by {', '.join(str(x) for x in parents)}"
            )

    def _validate_links_in_session(
        self,
        sess,
        parent_component_id: str,
        links: List[Dict[str, Any]],
        components_table,
        links_table,
    ) -> None:
        """Backstop validation for links being written under one parent.

        Checks that every child exists and is not archived, and that the new
        edges do not close a cycle through the existing active links. Stage
        rules (published parents pin published children) and link-kind typing
        stay at the control plane; unknown link kinds (for example a future
        "prompt" kind) pass through untouched.

        The tables are passed in because the caller holds an open transaction
        on this scoped session; _get_table would try to begin a second one.
        """
        if components_table is None:
            return

        child_ids = {link["child_component_id"] for link in links if link.get("child_component_id")}
        # Self-links are the smallest cycle.
        if parent_component_id in child_ids:
            raise ComponentCycleError(f"Component {parent_component_id} cannot reference itself")

        if child_ids:
            rows = sess.execute(
                select(components_table.c.component_id, components_table.c.deleted_at).where(
                    components_table.c.component_id.in_(child_ids)
                )
            ).fetchall()
            found = {r.component_id: r.deleted_at for r in rows}
            for child_id in sorted(child_ids):
                if child_id not in found:
                    # A code-defined child has no row; the control plane decides
                    # whether that is allowed, so absence is not an error here.
                    continue
                if found[child_id] is not None:
                    raise ComponentArchivedError(f"Cannot link {parent_component_id} to archived component {child_id}")

        # Cycle check: DFS from the new children through the existing links.
        # Only the new edges can introduce a cycle, so the walk starts there
        # instead of loading the whole table.
        if links_table is None or not child_ids:
            return
        visited: set = set()
        frontier = list(child_ids)
        while frontier:
            current = frontier.pop()
            if current in visited:
                continue
            visited.add(current)
            rows = sess.execute(
                select(links_table.c.child_component_id).where(links_table.c.parent_component_id == current)
            ).fetchall()
            for row in rows:
                nxt = row.child_component_id
                if nxt == parent_component_id:
                    raise ComponentCycleError(
                        f"Linking {parent_component_id} -> {current} would close a reference cycle"
                    )
                if nxt not in visited:
                    frontier.append(nxt)

    def resolve_version(
        self,
        component_id: str,
        version: Optional[int],
    ) -> Optional[int]:
        """Resolve a version number, handling NULL (current) case.

        Args:
            component_id: The component ID.
            version: Version number or None for current.

        Returns:
            Resolved version number or None if component not found.
        """
        if version is not None:
            return version

        try:
            components_table = self._get_table(table_type="components")
            if components_table is None:
                return None

            with self.Session() as sess:
                result = sess.execute(
                    select(components_table.c.current_version).where(components_table.c.component_id == component_id)
                ).scalar()
                return result

        except Exception as e:
            log_error(f"Error resolving version: {str(e)}")
            raise

    def load_component_graph(
        self,
        component_id: str,
        version: Optional[int] = None,
        label: Optional[str] = None,
        _visited: Optional[Set[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Load a component with its full resolved graph.

        Tracks the ACTIVE recursion path, not every node seen, so a shared
        child in a valid DAG loads normally while a true cycle returns a stub
        with cycle_detected=True instead of recursing forever.

        Args:
            component_id: The component ID.
            version: Specific version or None for current.
            label: Optional label of the component.

        Returns:
            Dictionary with component, config, links, and resolved children.
        """
        try:
            if _visited is None:
                _visited = set()
            if component_id in _visited:
                return {
                    "component": {"component_id": component_id},
                    "config": None,
                    "children": [],
                    "resolved_versions": {},
                    "cycle_detected": True,
                }
            _visited = _visited | {component_id}

            # Get component
            component = self.get_component(component_id)
            if component is None:
                return None

            # Resolve version
            resolved_version = self.resolve_version(component_id, version)
            if resolved_version is None:
                return None

            # Get config
            config = self.get_config(component_id, version=resolved_version)
            if config is None:
                return None

            # Get links
            links = self.get_links(component_id, resolved_version)

            # Resolve children recursively
            children = []
            resolved_versions: Dict[str, Optional[int]] = {component_id: resolved_version}

            for link in links:
                child_version = self.resolve_version(
                    link["child_component_id"],
                    link["child_version"],
                )
                resolved_versions[link["child_component_id"]] = child_version

                child_graph = self.load_component_graph(
                    link["child_component_id"],
                    version=child_version,
                    _visited=_visited,
                )

                if child_graph:
                    # Merge nested resolved versions
                    resolved_versions.update(child_graph.get("resolved_versions", {}))

                children.append(
                    {
                        "link": link,
                        "graph": child_graph,
                    }
                )

            return {
                "component": component,
                "config": config,
                "children": children,
                "resolved_versions": resolved_versions,
            }

        except Exception as e:
            log_error(f"Error loading component graph: {str(e)}")
            raise

    # -- Learning methods --
    def get_learning(
        self,
        learning_type: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a learning record.

        Args:
            learning_type: Type of learning ('user_profile', 'session_context', etc.)
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            workflow_id: Filter by workflow ID.
            session_id: Filter by session ID.
            namespace: Filter by namespace ('user', 'global', or custom).
            entity_id: Filter by entity ID (for entity-specific learnings).
            entity_type: Filter by entity type ('person', 'company', etc.).

        Returns:
            Dict with 'content' key containing the learning data, or None.
        """
        try:
            table = self._get_table(table_type="learnings")
            if table is None:
                return None

            with self.Session() as sess:
                stmt = select(table).where(table.c.learning_type == learning_type)

                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
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

                result = sess.execute(stmt).fetchone()
                if result is None:
                    return None

                row = dict(result._mapping)
                return {"content": row.get("content")}

        except Exception as e:
            log_debug(f"Error retrieving learning: {e}")
            return None

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
        """Insert or update a learning record.

        Args:
            id: Unique identifier for the learning.
            learning_type: Type of learning ('user_profile', 'session_context', etc.)
            content: The learning content as a dict.
            user_id: Associated user ID.
            agent_id: Associated agent ID.
            team_id: Associated team ID.
            session_id: Associated session ID.
            namespace: Namespace for scoping ('user', 'global', or custom).
            entity_id: Associated entity ID (for entity-specific learnings).
            entity_type: Entity type ('person', 'company', etc.).
            metadata: Optional metadata.
        """
        try:
            table = self._get_table(table_type="learnings", create_table_if_not_found=True)
            if table is None:
                return

            current_time = int(time.time())

            with self.Session() as sess, sess.begin():
                stmt = sqlite.insert(table).values(
                    learning_id=id,
                    learning_type=learning_type,
                    namespace=namespace,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    session_id=session_id,
                    entity_id=entity_id,
                    entity_type=entity_type,
                    content=content,
                    metadata=metadata,
                    created_at=current_time,
                    updated_at=current_time,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["learning_id"],
                    set_=dict(
                        content=content,
                        metadata=metadata,
                        updated_at=current_time,
                    ),
                )
                sess.execute(stmt)

            log_debug(f"Upserted learning: {id}")

        except Exception as e:
            log_debug(f"Error upserting learning: {e}")

    def delete_learning(self, id: str) -> bool:
        """Delete a learning record.

        Args:
            id: The learning ID to delete.

        Returns:
            True if deleted, False otherwise.
        """
        try:
            table = self._get_table(table_type="learnings")
            if table is None:
                return False

            with self.Session() as sess, sess.begin():
                stmt = table.delete().where(table.c.learning_id == id)
                result = sess.execute(stmt)
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
            raise e

    def delete_user_learnings(self, user_id: str, learning_type: Optional[str] = None) -> int:
        try:
            table = self._get_table(table_type="learnings")
            if table is None:
                return 0

            with self.Session() as sess, sess.begin():
                stmt = table.delete().where(table.c.user_id == user_id)
                if learning_type is not None:
                    stmt = stmt.where(table.c.learning_type == learning_type)
                result = sess.execute(stmt)
                return result.rowcount or 0

        except Exception as e:
            log_error(f"Error deleting user learnings: {e}")
            raise e

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
        """Get multiple learning records.

        Args:
            learning_type: Filter by learning type.
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            workflow_id: Filter by workflow ID.
            session_id: Filter by session ID.
            namespace: Filter by namespace ('user', 'global', or custom).
            entity_id: Filter by entity ID (for entity-specific learnings).
            entity_type: Filter by entity type ('person', 'company', etc.).
            limit: Maximum number of records to return.

        Returns:
            List of learning records.
        """
        try:
            table = self._get_table(table_type="learnings")
            if table is None:
                return []

            with self.Session() as sess:
                stmt = select(table)

                if learning_type is not None:
                    stmt = stmt.where(table.c.learning_type == learning_type)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
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

                stmt = stmt.order_by(table.c.updated_at.desc())

                if limit is not None:
                    stmt = stmt.limit(limit)

                results = sess.execute(stmt).fetchall()
                return [dict(row._mapping) for row in results]

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
        """Search learning records by text query. See BaseDb.search_learnings.

        The query matches the content column case-insensitively in both its
        space and underscore forms. Errors are raised, never swallowed.
        """
        try:
            table = self._get_table(table_type="learnings")
            if table is None:
                return []

            patterns = learning_search_patterns(query)
            if not patterns:
                return []

            with self.Session() as sess:
                stmt = select(table)

                if learning_type is not None:
                    stmt = stmt.where(table.c.learning_type == learning_type)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
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

                stmt = stmt.where(or_(*[table.c.content.ilike(pattern, escape="\\") for pattern in patterns]))

                stmt = stmt.order_by(table.c.updated_at.desc().nulls_last())
                if limit is not None:
                    stmt = stmt.limit(limit)

                results = sess.execute(stmt).fetchall()
                return [dict(row._mapping) for row in results]

        except Exception as e:
            log_error(f"Error searching learnings: {e}")
            raise e

    def get_learning_by_id(self, id: str) -> Optional[Dict[str, Any]]:
        try:
            table = self._get_table(table_type="learnings")
            if table is None:
                return None
            with self.Session() as sess:
                result = sess.execute(select(table).where(table.c.learning_id == id)).fetchone()
                return dict(result._mapping) if result else None
        except Exception as e:
            log_error(f"Error getting learning by id: {e}")
            raise e

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
                    if include_global:
                        stmt = stmt.where((table.c.user_id == user_id) | (table.c.user_id.is_(None)))
                    else:
                        stmt = stmt.where(table.c.user_id == user_id)
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

                count_stmt = select(func.count()).select_from(stmt.subquery())
                total_count = sess.execute(count_stmt).scalar() or 0

                stmt = apply_sorting(stmt, table, sort_by or "updated_at", sort_order or "desc")
                stmt = stmt.limit(limit).offset((page - 1) * limit)
                results = sess.execute(stmt).fetchall()
                return [dict(row._mapping) for row in results], int(total_count)

        except Exception as e:
            log_error(f"Error listing learnings: {e}")
            raise e

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
                stmt = select(
                    table.c.user_id,
                    last_updated_col.label("last_learning_updated_at"),
                )
                if learning_type is not None:
                    stmt = stmt.where(table.c.learning_type == learning_type)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                else:
                    stmt = stmt.where(table.c.user_id.is_not(None))
                stmt = stmt.group_by(table.c.user_id)

                sort_columns = {
                    "user_id": table.c.user_id,
                    "last_learning_updated_at": last_updated_col,
                }
                sort_col = sort_columns.get(sort_by or "last_learning_updated_at", last_updated_col)
                stmt = stmt.order_by(sort_col.asc() if sort_order == "asc" else sort_col.desc())

                count_stmt = select(func.count()).select_from(stmt.subquery())
                total_count = sess.execute(count_stmt).scalar() or 0

                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset((page - 1) * limit)

                results = sess.execute(stmt).fetchall()
                return [
                    {
                        "user_id": row.user_id,
                        "last_learning_updated_at": row.last_learning_updated_at,
                    }
                    for row in results
                ], int(total_count)

        except Exception as e:
            log_error(f"Error getting learning user stats: {e}")
            raise e

    # -- Schedule methods --
    # ``claim_due_schedule`` / ``release_schedule`` take no user_id: the poller has to fire
    # schedules across all users.
    def get_schedule(self, schedule_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        try:
            table = self._get_table(table_type="schedules")
            if table is None:
                return None
            with self.Session() as sess:
                stmt = select(table).where(table.c.id == schedule_id)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                result = sess.execute(stmt).fetchone()
                return dict(result._mapping) if result else None
        except Exception as e:
            log_debug(f"Error getting schedule: {e}")
            return None

    def get_schedule_by_name(self, name: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        try:
            table = self._get_table(table_type="schedules")
            if table is None:
                return None
            with self.Session() as sess:
                stmt = select(table).where(table.c.name == name)
                # Names are unique per owner: ``None`` addresses the unowned bucket,
                # never another owner's schedule of the same name.
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                else:
                    stmt = stmt.where(table.c.user_id.is_(None))
                result = sess.execute(stmt).fetchone()
                return dict(result._mapping) if result else None
        except Exception as e:
            log_debug(f"Error getting schedule by name: {e}")
            return None

    def get_schedules(
        self,
        enabled: Optional[bool] = None,
        limit: int = 100,
        page: int = 1,
        user_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        try:
            table = self._get_table(table_type="schedules")
            if table is None:
                return [], 0
            with self.Session() as sess:
                # Build base query with filters
                base_query = select(table)
                if enabled is not None:
                    base_query = base_query.where(table.c.enabled == enabled)
                if user_id is not None:
                    base_query = base_query.where(table.c.user_id == user_id)

                # Get total count
                count_stmt = select(func.count()).select_from(base_query.alias())
                total_count = sess.execute(count_stmt).scalar() or 0

                # Calculate offset from page
                offset = (page - 1) * limit

                # Get paginated results
                stmt = base_query.order_by(table.c.created_at.desc()).limit(limit).offset(offset)
                results = sess.execute(stmt).fetchall()
                return [dict(row._mapping) for row in results], total_count
        except Exception as e:
            log_debug(f"Error listing schedules: {e}")
            return [], 0

    def create_schedule(self, schedule_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            table = self._get_table(table_type="schedules", create_table_if_not_found=True)
            if table is None:
                raise RuntimeError("Failed to get or create schedules table")
            with self.Session() as sess, sess.begin():
                sess.execute(table.insert().values(**schedule_data))
            return schedule_data
        except Exception as e:
            log_error(f"Error creating schedule: {str(e)}")
            raise

    def update_schedule(
        self, schedule_id: str, user_id: Optional[str] = None, **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        from agno.db.schemas.scheduler import validate_schedule_update

        validate_schedule_update(kwargs)
        try:
            table = self._get_table(table_type="schedules")
            if table is None:
                return None
            if kwargs.get("enabled") is True:
                # A system-set disabled_reason describes why the row was off;
                # turning it on retires the explanation.
                kwargs.setdefault("disabled_reason", None)
            kwargs["updated_at"] = int(time.time())
            with self.Session() as sess, sess.begin():
                stmt = table.update().where(table.c.id == schedule_id)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                sess.execute(stmt.values(**kwargs))
            return self.get_schedule(schedule_id, user_id=user_id)
        except Exception as e:
            # Let a unique-violation (rename onto a name taken in the same owner bucket)
            # propagate so the router maps it to 409
            from agno.db.utils import is_unique_violation

            if is_unique_violation(e):
                raise
            log_debug(f"Error updating schedule: {e}")
            return None

    def delete_schedule(self, schedule_id: str, user_id: Optional[str] = None) -> bool:
        try:
            table = self._get_table(table_type="schedules")
            if table is None:
                return False
            runs_table = self._get_table(table_type="schedule_runs")
            with self.Session() as sess, sess.begin():
                if runs_table is not None:
                    # Mirror the owner guard on the cascade so another user's runs are kept
                    runs_delete = runs_table.delete().where(runs_table.c.schedule_id == schedule_id)
                    if user_id is not None:
                        runs_delete = runs_delete.where(runs_table.c.user_id == user_id)
                    sess.execute(runs_delete)
                delete_stmt = table.delete().where(table.c.id == schedule_id)
                if user_id is not None:
                    delete_stmt = delete_stmt.where(table.c.user_id == user_id)
                result = sess.execute(delete_stmt)
                return result.rowcount > 0
        except Exception as e:
            log_debug(f"Error deleting schedule: {e}")
            return False

    def disable_schedules_for_target(
        self,
        target_type: str,
        target_id: str,
        reason: Optional[str] = None,
    ) -> int:
        """Disable every enabled schedule aimed at one component; returns the count.

        Matches provenance-tagged rows (target_type/target_id) AND generic rows
        whose endpoint is that component's run endpoint - a schedule that can
        only 404 against an archived target is not a schedule. A system reason
        lands in disabled_reason so the owner's next read explains the flip;
        enable clears it. Crosses owners deliberately: archiving the target is
        a system action.

        delete_component runs this same cascade inside the transaction that
        removes the target, so archiving through the catalog needs no second
        call; this stays public for targets that have no catalog row.
        """
        try:
            table = self._get_table(table_type="schedules")
            if table is None:
                return 0
            with self.Session() as sess, sess.begin():
                return self._disable_schedules_for_target_in_session(sess, table, target_type, target_id, reason)
        except Exception as e:
            log_error(f"Error disabling schedules for target: {e}")
            raise

    def _disable_schedules_for_target_in_session(
        self,
        sess,
        table,
        target_type: str,
        target_id: str,
        reason: Optional[str] = None,
    ) -> int:
        """The cascade write, run on a session the caller already holds.

        The table is passed in because the caller may hold an open transaction
        on this scoped session; _get_table would try to begin a second one.
        """
        from agno.db.schemas.scheduler import build_run_endpoint

        endpoint = build_run_endpoint(target_type, target_id)
        # RUN_ENDPOINT_RE accepts an optional trailing slash, so a stored
        # "/agents/x/runs/" is a valid run endpoint that plain equality would
        # miss - matching both spellings keeps the cascade from leaking rows.
        #
        # The match stays TYPED. Keying on the id alone would look tempting
        # (the id is unique inside the catalog) but a schedule's target need
        # not be in the catalog at all: a code-defined component of another
        # type can hold the same id, and disabling its schedules from an
        # unrelated tenant's archive is not a cascade, it is collateral. The
        # type is kept honest at the other end instead - upsert_component
        # refuses to rewrite it.
        endpoints = [endpoint, endpoint + "/"]
        result = sess.execute(
            table.update()
            .where(
                or_(
                    and_(table.c.target_type == target_type, table.c.target_id == target_id),
                    table.c.endpoint.in_(endpoints),
                ),
                table.c.enabled.is_(True),
            )
            .values(enabled=False, disabled_reason=reason, updated_at=int(time.time()))
        )
        return int(result.rowcount or 0)

    def stamp_schedule_provenance(self, schedule_id: str, **provenance: Any) -> bool:
        """Write provenance columns the generic update_schedule refuses.

        The trusted path for control planes: managed_by, target_type,
        target_id, created_by_*/updated_by_*. Never touches ownership or the
        mutable surface.
        """
        allowed = {
            "managed_by",
            "target_type",
            "target_id",
            "created_by_run_id",
            "created_by_session_id",
            "updated_by_run_id",
            "updated_by_session_id",
        }
        rejected = sorted(set(provenance) - allowed)
        if rejected:
            raise ValueError(f"stamp_schedule_provenance cannot write {rejected}")
        try:
            table = self._get_table(table_type="schedules")
            if table is None:
                return False
            with self.Session() as sess, sess.begin():
                result = sess.execute(
                    table.update().where(table.c.id == schedule_id).values(updated_at=int(time.time()), **provenance)
                )
            return result.rowcount > 0
        except Exception as e:
            log_error(f"Error stamping schedule provenance: {e}")
            raise

    def claim_due_schedule(self, worker_id: str, lock_grace_seconds: int = 300) -> Optional[Dict[str, Any]]:
        try:
            table = self._get_table(table_type="schedules")
            if table is None:
                return None
            now = int(time.time())
            stale_lock_threshold = now - lock_grace_seconds
            with self.Session() as sess, sess.begin():
                # Find a due, enabled schedule that is either unlocked or has a stale lock
                stmt = (
                    select(table)
                    .where(
                        table.c.enabled == True,  # noqa: E712
                        table.c.next_run_at <= now,
                        or_(
                            table.c.locked_by.is_(None),
                            table.c.locked_at <= stale_lock_threshold,
                        ),
                    )
                    .order_by(table.c.next_run_at.asc())
                    .limit(1)
                )
                row = sess.execute(stmt).fetchone()
                if row is None:
                    return None
                schedule = dict(row._mapping)
                # Claim it with EVERY predicate the select used, not just the
                # lock half: the select runs outside the write transaction, so
                # a disable (the archive cascade among them) or a reschedule
                # committing in the gap must make the claim a no-op rather than
                # arm a run against a target that is gone.
                result = sess.execute(
                    table.update()
                    .where(
                        table.c.id == schedule["id"],
                        table.c.enabled == True,  # noqa: E712
                        table.c.next_run_at <= now,
                        or_(
                            table.c.locked_by.is_(None),
                            table.c.locked_at <= stale_lock_threshold,
                        ),
                    )
                    .values(locked_by=worker_id, locked_at=now)
                )
                if result.rowcount == 0:
                    return None
                # Return post-claim state: the executor acts on this dict, and
                # the pre-claim snapshot can already be stale.
                claimed = sess.execute(select(table).where(table.c.id == schedule["id"])).fetchone()
                if claimed is None:
                    return None
                return dict(claimed._mapping)
        except Exception as e:
            log_debug(f"Error claiming schedule: {e}")
            return None

    def release_schedule(self, schedule_id: str, next_run_at: Optional[int] = None) -> bool:
        try:
            table = self._get_table(table_type="schedules")
            if table is None:
                return False
            updates: Dict[str, Any] = {"locked_by": None, "locked_at": None, "updated_at": int(time.time())}
            if next_run_at is not None:
                updates["next_run_at"] = next_run_at
            with self.Session() as sess, sess.begin():
                result = sess.execute(table.update().where(table.c.id == schedule_id).values(**updates))
                return result.rowcount > 0
        except Exception as e:
            log_debug(f"Error releasing schedule: {e}")
            return False

    def create_schedule_run(self, run_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            table = self._get_table(table_type="schedule_runs", create_table_if_not_found=True)
            if table is None:
                raise RuntimeError("Failed to get or create schedule_runs table")
            with self.Session() as sess, sess.begin():
                sess.execute(table.insert().values(**run_data))
            return run_data
        except Exception as e:
            log_error(f"Error creating schedule run: {str(e)}")
            raise

    def update_schedule_run(self, schedule_run_id: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
        try:
            table = self._get_table(table_type="schedule_runs")
            if table is None:
                return None
            with self.Session() as sess, sess.begin():
                sess.execute(table.update().where(table.c.id == schedule_run_id).values(**kwargs))
            return self.get_schedule_run(schedule_run_id)
        except Exception as e:
            log_debug(f"Error updating schedule run: {e}")
            return None

    def get_schedule_run(self, run_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        try:
            table = self._get_table(table_type="schedule_runs")
            if table is None:
                return None
            with self.Session() as sess:
                stmt = select(table).where(table.c.id == run_id)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                result = sess.execute(stmt).fetchone()
                return dict(result._mapping) if result else None
        except Exception as e:
            log_debug(f"Error getting schedule run: {e}")
            return None

    def get_schedule_runs(
        self,
        schedule_id: str,
        limit: int = 20,
        page: int = 1,
        user_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        try:
            table = self._get_table(table_type="schedule_runs")
            if table is None:
                return [], 0
            with self.Session() as sess:
                # Get total count
                base_filter = table.c.schedule_id == schedule_id
                if user_id is not None:
                    base_filter = and_(base_filter, table.c.user_id == user_id)
                count_stmt = select(func.count()).select_from(table).where(base_filter)
                total_count = sess.execute(count_stmt).scalar() or 0

                # Calculate offset from page
                offset = (page - 1) * limit

                # Get paginated results
                stmt = select(table).where(base_filter).order_by(table.c.created_at.desc()).limit(limit).offset(offset)
                results = sess.execute(stmt).fetchall()
                return [dict(row._mapping) for row in results], total_count
        except Exception as e:
            log_debug(f"Error getting schedule runs: {e}")
            return [], 0

    # -- Approval methods --

    def create_approval(self, approval_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            table = self._get_table(table_type="approvals", create_table_if_not_found=True)
            if table is None:
                raise RuntimeError("Failed to get or create approvals table")
            data = {**approval_data}
            now = int(time.time())
            data.setdefault("created_at", now)
            data.setdefault("updated_at", now)
            with self.Session() as sess, sess.begin():
                sess.execute(table.insert().values(**data))
            return data
        except Exception as e:
            log_error(f"Error creating approval: {str(e)}")
            raise

    def get_approval(self, approval_id: str) -> Optional[Dict[str, Any]]:
        try:
            table = self._get_table(table_type="approvals")
            if table is None:
                return None
            with self.Session() as sess:
                result = sess.execute(select(table).where(table.c.id == approval_id)).fetchone()
                return dict(result._mapping) if result else None
        except Exception as e:
            log_debug(f"Error getting approval: {e}")
            return None

    def get_approvals(
        self,
        status: Optional[str] = None,
        source_type: Optional[str] = None,
        approval_type: Optional[str] = None,
        pause_type: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        user_id: Optional[str] = None,
        schedule_id: Optional[str] = None,
        run_id: Optional[str] = None,
        limit: int = 100,
        page: int = 1,
    ) -> Tuple[List[Dict[str, Any]], int]:
        try:
            table = self._get_table(table_type="approvals")
            if table is None:
                return [], 0
            with self.Session() as sess:
                stmt = select(table)
                count_stmt = select(func.count()).select_from(table)
                if status is not None:
                    stmt = stmt.where(table.c.status == status)
                    count_stmt = count_stmt.where(table.c.status == status)
                if source_type is not None:
                    stmt = stmt.where(table.c.source_type == source_type)
                    count_stmt = count_stmt.where(table.c.source_type == source_type)
                if approval_type is not None:
                    stmt = stmt.where(table.c.approval_type == approval_type)
                    count_stmt = count_stmt.where(table.c.approval_type == approval_type)
                if pause_type is not None:
                    stmt = stmt.where(table.c.pause_type == pause_type)
                    count_stmt = count_stmt.where(table.c.pause_type == pause_type)
                if agent_id is not None:
                    stmt = stmt.where(table.c.agent_id == agent_id)
                    count_stmt = count_stmt.where(table.c.agent_id == agent_id)
                if team_id is not None:
                    stmt = stmt.where(table.c.team_id == team_id)
                    count_stmt = count_stmt.where(table.c.team_id == team_id)
                if workflow_id is not None:
                    stmt = stmt.where(table.c.workflow_id == workflow_id)
                    count_stmt = count_stmt.where(table.c.workflow_id == workflow_id)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                    count_stmt = count_stmt.where(table.c.user_id == user_id)
                if schedule_id is not None:
                    stmt = stmt.where(table.c.schedule_id == schedule_id)
                    count_stmt = count_stmt.where(table.c.schedule_id == schedule_id)
                if run_id is not None:
                    stmt = stmt.where(table.c.run_id == run_id)
                    count_stmt = count_stmt.where(table.c.run_id == run_id)
                total = sess.execute(count_stmt).scalar() or 0

                # Calculate offset from page
                offset = (page - 1) * limit

                stmt = stmt.order_by(table.c.created_at.desc()).limit(limit).offset(offset)
                results = sess.execute(stmt).fetchall()
                return [dict(row._mapping) for row in results], total
        except Exception as e:
            log_debug(f"Error listing approvals: {e}")
            return [], 0

    def update_approval(
        self, approval_id: str, expected_status: Optional[str] = None, **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        try:
            table = self._get_table(table_type="approvals")
            if table is None:
                return None
            kwargs["updated_at"] = int(time.time())
            with self.Session() as sess, sess.begin():
                stmt = table.update().where(table.c.id == approval_id)
                if expected_status is not None:
                    stmt = stmt.where(table.c.status == expected_status)
                result = sess.execute(stmt.values(**kwargs))
                if result.rowcount == 0:
                    return None
            return self.get_approval(approval_id)
        except Exception as e:
            log_debug(f"Error updating approval: {e}")
            return None

    def delete_approval(self, approval_id: str) -> bool:
        try:
            table = self._get_table(table_type="approvals")
            if table is None:
                return False
            with self.Session() as sess, sess.begin():
                result = sess.execute(table.delete().where(table.c.id == approval_id))
                return result.rowcount > 0
        except Exception as e:
            log_debug(f"Error deleting approval: {e}")
            return False

    def get_pending_approval_count(self, user_id: Optional[str] = None) -> int:
        try:
            table = self._get_table(table_type="approvals")
            if table is None:
                return 0
            with self.Session() as sess:
                stmt = select(func.count()).select_from(table).where(table.c.status == "pending")
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                return sess.execute(stmt).scalar() or 0
        except Exception as e:
            log_debug(f"Error counting approvals: {e}")
            return 0

    def update_approval_run_status(self, run_id: str, run_status: RunStatus) -> int:
        """Update run_status on all approvals for a given run_id.

        Args:
            run_id: The run ID to match.
            run_status: The new run status.

        Returns:
            Number of approvals updated.
        """
        try:
            table = self._get_table(table_type="approvals")
            if table is None:
                return 0
            with self.Session() as sess, sess.begin():
                stmt = (
                    table.update()
                    .where(table.c.run_id == run_id)
                    .values(run_status=run_status.value, updated_at=int(time.time()))
                )
                result = sess.execute(stmt)
                return result.rowcount
        except Exception as e:
            log_debug(f"Error updating approval run_status: {e}")
            return 0

    # --- Built-in MCP OAuth server store ---
    # Thin delegations to agno.db.mcp_oauth_store (shared with PostgresDb); each fetches the
    # table via the normal schema-aware _get_table path, so the store is created on first
    # use like every other agno table.

    def get_mcp_oauth_client(self, client_id: str) -> Optional[str]:
        table = self._get_table(table_type=MCP_OAUTH_CLIENTS, create_table_if_not_found=True)
        return mcp_oauth_store.get_client(self.db_engine, table, client_id)

    def create_mcp_oauth_client(
        self, *, client_id: str, client_metadata: str, now: int, unconsumed_ttl: int, max_clients: int
    ) -> bool:
        table = self._get_table(table_type=MCP_OAUTH_CLIENTS, create_table_if_not_found=True)
        return mcp_oauth_store.create_client(
            self.db_engine,
            table,
            client_id=client_id,
            client_metadata=client_metadata,
            now=now,
            unconsumed_ttl=unconsumed_ttl,
            max_clients=max_clients,
        )

    def mark_mcp_oauth_client_consumed(self, client_id: str, now: int) -> None:
        table = self._get_table(table_type=MCP_OAUTH_CLIENTS, create_table_if_not_found=True)
        mcp_oauth_store.mark_client_consumed(self.db_engine, table, client_id, now)

    def store_mcp_oauth_transaction(
        self, *, txn_id: str, client_id: str, params: str, expires_at: int, now: int, max_pending: int
    ) -> None:
        table = self._get_table(table_type=MCP_OAUTH_TRANSACTIONS, create_table_if_not_found=True)
        mcp_oauth_store.store_transaction(
            self.db_engine,
            table,
            txn_id=txn_id,
            client_id=client_id,
            params=params,
            expires_at=expires_at,
            now=now,
            max_pending=max_pending,
        )

    def get_mcp_oauth_transaction(self, txn_id: str) -> Optional[tuple]:
        table = self._get_table(table_type=MCP_OAUTH_TRANSACTIONS, create_table_if_not_found=True)
        return mcp_oauth_store.get_transaction(self.db_engine, table, txn_id)

    def consume_mcp_oauth_transaction(self, txn_id: str, now: int) -> Optional[tuple]:
        table = self._get_table(table_type=MCP_OAUTH_TRANSACTIONS, create_table_if_not_found=True)
        return mcp_oauth_store.consume_transaction(self.db_engine, table, txn_id, now)

    def store_mcp_oauth_code(self, *, code_hash: str, payload: str, expires_at: int, now: int) -> None:
        table = self._get_table(table_type=MCP_OAUTH_CODES, create_table_if_not_found=True)
        mcp_oauth_store.store_code(
            self.db_engine, table, code_hash=code_hash, payload=payload, expires_at=expires_at, now=now
        )

    def get_mcp_oauth_code(self, code_hash: str) -> Optional[tuple]:
        table = self._get_table(table_type=MCP_OAUTH_CODES, create_table_if_not_found=True)
        return mcp_oauth_store.get_code(self.db_engine, table, code_hash)

    def delete_mcp_oauth_code(self, code_hash: str) -> bool:
        table = self._get_table(table_type=MCP_OAUTH_CODES, create_table_if_not_found=True)
        return mcp_oauth_store.delete_code(self.db_engine, table, code_hash)

    def store_mcp_oauth_refresh(
        self, *, token_hash: str, client_id: str, scopes: str, expires_at: int, now: int, family_id: str
    ) -> None:
        table = self._get_table(table_type=MCP_OAUTH_REFRESH_TOKENS, create_table_if_not_found=True)
        mcp_oauth_store.store_refresh(
            self.db_engine,
            table,
            token_hash=token_hash,
            client_id=client_id,
            scopes=scopes,
            expires_at=expires_at,
            now=now,
            family_id=family_id,
        )

    def get_mcp_oauth_refresh(self, token_hash: str) -> Optional[tuple]:
        table = self._get_table(table_type=MCP_OAUTH_REFRESH_TOKENS, create_table_if_not_found=True)
        return mcp_oauth_store.get_refresh(self.db_engine, table, token_hash)

    def delete_mcp_oauth_refresh(self, token_hash: str) -> bool:
        table = self._get_table(table_type=MCP_OAUTH_REFRESH_TOKENS, create_table_if_not_found=True)
        return mcp_oauth_store.delete_refresh(self.db_engine, table, token_hash)

    def delete_mcp_oauth_refresh_family(self, family_id: str) -> int:
        table = self._get_table(table_type=MCP_OAUTH_REFRESH_TOKENS, create_table_if_not_found=True)
        return mcp_oauth_store.delete_refresh_family(self.db_engine, table, family_id)

    def get_mcp_oauth_keys(self) -> List[tuple]:
        table = self._get_table(table_type=MCP_OAUTH_KEYS, create_table_if_not_found=True)
        return mcp_oauth_store.get_keys(self.db_engine, table)

    def insert_mcp_oauth_key(self, *, kid: str, secret: str, created_at: int) -> bool:
        table = self._get_table(table_type=MCP_OAUTH_KEYS, create_table_if_not_found=True)
        return mcp_oauth_store.insert_key(self.db_engine, table, kid=kid, secret=secret, created_at=created_at)

    # --- Auth Tokens ---

    def get_auth_token(self, provider: str, user_id: Optional[str], service: str) -> Optional[Dict[str, Any]]:
        try:
            table = self._get_table(table_type="auth_tokens")
            if table is None:
                return None
            # Use empty string for NULL user_id to satisfy unique constraint on (provider, user_id, service)
            effective_user_id = user_id if user_id is not None else ""
            with self.Session() as sess:
                result = sess.execute(
                    select(table).where(
                        table.c.provider == provider,
                        table.c.user_id == effective_user_id,
                        table.c.service == service,
                    )
                ).fetchone()
                if not result:
                    return None
                return dict(result._mapping)
        except Exception as e:
            log_debug(f"Error getting auth token: {e}")
            return None

    def upsert_auth_token(self, token: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            table = self._get_table(table_type="auth_tokens", create_table_if_not_found=True)
            if table is None:
                raise RuntimeError("Failed to get or create auth_tokens table")
            data = {**token}
            data["id"] = str(uuid4())
            data["user_id"] = data.get("user_id") or ""
            now = int(time.time())
            data.setdefault("created_at", now)
            data["updated_at"] = now
            with self.Session() as sess, sess.begin():
                # SQLite upsert via INSERT OR REPLACE
                stmt = sqlite.insert(table).values(**data)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["provider", "user_id", "service"],
                    set_={
                        "token_data": stmt.excluded.token_data,
                        "granted_scopes": stmt.excluded.granted_scopes,
                        "updated_at": stmt.excluded.updated_at,
                    },
                )
                sess.execute(stmt)
            return data
        except Exception as e:
            log_debug(f"Error upserting auth token: {e}")
            return None

    def delete_auth_token(self, provider: str, user_id: Optional[str], service: str) -> bool:
        try:
            table = self._get_table(table_type="auth_tokens")
            if table is None:
                return False
            effective_user_id = user_id if user_id is not None else ""
            with self.Session() as sess, sess.begin():
                result = sess.execute(
                    table.delete().where(
                        table.c.provider == provider,
                        table.c.user_id == effective_user_id,
                        table.c.service == service,
                    )
                )
                return result.rowcount > 0
        except Exception as e:
            log_debug(f"Error deleting auth token: {e}")
            return False

    # -- Service Accounts methods --

    def create_service_account(self, account_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            table = self._get_table(table_type="service_accounts", create_table_if_not_found=True)
            if table is None:
                raise RuntimeError("Failed to get or create service accounts table")
            with self.Session() as sess, sess.begin():
                sess.execute(table.insert().values(**account_data))
            return account_data
        except Exception as e:
            log_error(f"Error creating service account: {str(e)}")
            raise

    def get_service_account(self, service_account_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        try:
            table = self._get_table(table_type="service_accounts")
            if table is None:
                return None
            with self.Session() as sess:
                stmt = select(table).where(table.c.id == service_account_id)
                if user_id is not None:
                    stmt = stmt.where(or_(table.c.user_id == user_id, table.c.user_id.is_(None)))
                result = sess.execute(stmt).fetchone()
                return dict(result._mapping) if result else None
        except Exception as e:
            log_debug(f"Error getting service account: {e}")
            return None

    def get_service_account_by_token_hash(self, token_hash: str) -> Optional[Dict[str, Any]]:
        """Get a service account by its token hash.

        Re-raises on DB error so callers can distinguish "unknown token" (None) from "db unavailable" (exception).
        """
        table = self._get_table(table_type="service_accounts")
        if table is None:
            # _get_table swallows connectivity errors and returns None, which is
            # indistinguishable from "table not created yet". Probe the connection so
            # a real outage propagates (fail closed) instead of reading as an unknown
            # token; a genuinely absent table returns None.
            with self.Session() as sess:
                sess.execute(text("SELECT 1"))
            return None
        try:
            with self.Session() as sess:
                result = sess.execute(select(table).where(table.c.token_hash == token_hash)).fetchone()
                return dict(result._mapping) if result else None
        except Exception as e:
            log_error(f"Error getting service account by token hash: {e}")
            raise

    def get_service_account_by_name(self, name: str, include_revoked: bool = False) -> Optional[Dict[str, Any]]:
        try:
            table = self._get_table(table_type="service_accounts")
            if table is None:
                return None
            with self.Session() as sess:
                stmt = select(table).where(table.c.name == name)
                if not include_revoked:
                    stmt = stmt.where(table.c.revoked_at.is_(None))
                stmt = stmt.order_by(table.c.created_at.desc())
                result = sess.execute(stmt).fetchone()
                return dict(result._mapping) if result else None
        except Exception as e:
            log_debug(f"Error getting service account by name: {e}")
            return None

    def get_service_accounts(
        self,
        include_revoked: bool = True,
        limit: int = 20,
        page: int = 1,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        user_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        try:
            table = self._get_table(table_type="service_accounts")
            if table is None:
                return [], 0
            with self.Session() as sess:
                # Build base query with filters
                base_query = select(table)
                if not include_revoked:
                    base_query = base_query.where(table.c.revoked_at.is_(None))
                if user_id is not None:
                    base_query = base_query.where(or_(table.c.user_id == user_id, table.c.user_id.is_(None)))

                # Get total count
                count_stmt = select(func.count()).select_from(base_query.alias())
                total_count = sess.execute(count_stmt).scalar() or 0

                # Calculate offset from page
                offset = (page - 1) * limit

                # Apply sorting
                sort_column = table.c[resolve_service_account_sort_column(sort_by)]
                order_by = sort_column.asc() if sort_order == "asc" else sort_column.desc()

                # Get paginated results
                stmt = base_query.order_by(order_by).limit(limit).offset(offset)
                results = sess.execute(stmt).fetchall()
                return [dict(row._mapping) for row in results], total_count
        except Exception as e:
            log_debug(f"Error listing service accounts: {e}")
            return [], 0

    def update_service_account(
        self, service_account_id: str, return_record: bool = True, **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        validate_service_account_update(kwargs)
        try:
            table = self._get_table(table_type="service_accounts")
            if table is None:
                return None
            with self.Session() as sess, sess.begin():
                sess.execute(table.update().where(table.c.id == service_account_id).values(**kwargs))
            if not return_record:
                return None
            return self.get_service_account(service_account_id)
        except Exception as e:
            log_debug(f"Error updating service account: {e}")
            return None

    def delete_service_account(self, service_account_id: str) -> bool:
        try:
            table = self._get_table(table_type="service_accounts")
            if table is None:
                return False
            with self.Session() as sess, sess.begin():
                result = sess.execute(table.delete().where(table.c.id == service_account_id))
                return result.rowcount > 0
        except Exception as e:
            log_debug(f"Error deleting service account: {e}")
            return False
