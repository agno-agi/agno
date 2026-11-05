import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional, Sequence, Set, Tuple, Union
from uuid import uuid4

from packaging import version as packaging_version

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace

from agno.db.base import BaseDb, SessionType
from agno.db.migrations.manager import MigrationManager
from agno.db.mysql.schemas import get_table_schema_definition
from agno.db.mysql.utils import (
    METRICS_IN_LIST_LIMIT,
    METRICS_STALE_KEYS_LIMIT,
    apply_sorting,
    build_component_metrics_legacy_runs_query,
    build_component_metrics_run,
    build_component_metrics_runs_query,
    build_component_metrics_totals_queries,
    build_metrics_by_owner_queries,
    bulk_upsert_aggregate_metrics_rows,
    bulk_upsert_component_metrics,
    create_schema,
    is_lock_not_available,
    is_table_available,
    is_valid_table,
    reopen_metrics_day,
    reopen_metrics_days_from,
    reopen_metrics_month,
    set_json_column_types,
    upsert_aggregate_metrics_row,
)
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.db.utils import (
    AGGREGATE_METRICS_COUNT_COLUMNS,
    HISTORY_SKIP_STATUSES,
    METRICS_BATCH_SIZE,
    METRICS_LOCK_SECONDS,
    METRICS_REFRESH_ID,
    METRICS_STOPPED_ERROR,
    METRICS_TOKEN_FIELDS,
    SessionRunObjectCache,
    add_metrics_month_totals,
    aggregate_metrics_rows_to_write,
    build_aggregate_metrics_month_rows,
    build_aggregate_metrics_rows,
    build_component_metrics_totals,
    build_metrics_by_owner,
    build_metrics_from_aggregate_metrics,
    build_single_run_row,
    calculate_date_component_metrics,
    component_metrics_rows_to_write,
    database_error_message,
    deserialize_run,
    deserialize_session,
    deserialize_sessions,
    filter_context_runs,
    get_months_to_calculate_metrics_for,
    json_serializer,
    list_metrics_totals_models,
    merge_metrics_totals,
    merge_runs_table_with_legacy_blob,
    metrics_calculation_enabled,
    metrics_day_completed,
    metrics_day_to_reopen,
    metrics_days_since_last_calculation,
    metrics_full_months,
    metrics_month_end,
    metrics_nested_run_ids,
    metrics_refresh_status,
    metrics_remote_member_team_session_ids,
    metrics_versions,
    resolve_metrics_fields,
    run_index_lock_name,
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
    from sqlalchemy import (
        JSON,
        TEXT,
        ForeignKey,
        Index,
        UniqueConstraint,
        and_,
        case,
        cast,
        func,
        null,
        or_,
        tuple_,
        union,
        update,
    )
    from sqlalchemy.dialects import mysql
    from sqlalchemy.engine import Engine, create_engine
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.orm import scoped_session, sessionmaker
    from sqlalchemy.schema import Column, MetaData, Table
    from sqlalchemy.sql.expression import select, text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


class MySQLDb(BaseDb):
    def __init__(
        self,
        id: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        db_schema: Optional[str] = None,
        db_url: Optional[str] = None,
        session_table: Optional[str] = None,
        runs_table: Optional[str] = None,
        memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
        component_metrics_table: Optional[str] = None,
        aggregate_metrics_table: Optional[str] = None,
        metrics_refreshes_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
        traces_table: Optional[str] = None,
        spans_table: Optional[str] = None,
        versions_table: Optional[str] = None,
        create_schema: bool = True,
    ):
        """
        Interface for interacting with a MySQL database.

        The following order is used to determine the database connection:
            1. Use the db_engine if provided
            2. Use the db_url
            3. Raise an error if neither is provided

        Args:
            id (Optional[str]): ID of the database.
            db_url (Optional[str]): The database URL to connect to.
            db_engine (Optional[Engine]): The SQLAlchemy database engine to use.
            db_schema (Optional[str]): The database schema to use.
            session_table (Optional[str]): Name of the table to store Agent, Team and Workflow sessions.
            runs_table (Optional[str]): Name of the table to store the runs of each session.
            memory_table (Optional[str]): Name of the table to store memories.
            metrics_table (Optional[str]): Name of the table to store metrics.
            component_metrics_table (Optional[str]): Name of the table to store the metrics of each agent, team and
                workflow.
            aggregate_metrics_table (Optional[str]): Name of the table to store the metrics of each user.
            metrics_refreshes_table (Optional[str]): Name of the table to store the metrics refreshes.
            eval_table (Optional[str]): Name of the table to store evaluation runs data.
            knowledge_table (Optional[str]): Name of the table to store knowledge content.
            traces_table (Optional[str]): Name of the table to store run traces.
            spans_table (Optional[str]): Name of the table to store span events.
            versions_table (Optional[str]): Name of the table to store schema versions.
            create_schema (bool): Whether to automatically create the database schema if it doesn't exist.
                Set to False if schema is managed externally (e.g., via migrations). Defaults to True.

        Raises:
            ValueError: If neither db_url nor db_engine is provided.
            ValueError: If none of the tables are provided.
        """
        if id is None:
            base_seed = db_url or str(db_engine.url)  # type: ignore
            schema_suffix = db_schema if db_schema is not None else "ai"
            seed = f"{base_seed}#{schema_suffix}"
            id = generate_id(seed)

        super().__init__(
            id=id,
            session_table=session_table,
            runs_table=runs_table,
            memory_table=memory_table,
            metrics_table=metrics_table,
            component_metrics_table=component_metrics_table,
            aggregate_metrics_table=aggregate_metrics_table,
            metrics_refreshes_table=metrics_refreshes_table,
            eval_table=eval_table,
            knowledge_table=knowledge_table,
            traces_table=traces_table,
            spans_table=spans_table,
            versions_table=versions_table,
        )
        if metrics_table is not None:
            log_warning("metrics_table is deprecated; use component_metrics_table and aggregate_metrics_table.")

        _engine: Optional[Engine] = db_engine
        if _engine is None and db_url is not None:
            _engine = create_engine(db_url, json_serializer=json_serializer)
        if _engine is None:
            raise ValueError("One of db_url or db_engine must be provided")

        self.db_url: Optional[str] = db_url
        self.db_engine: Engine = _engine
        self.db_schema: str = db_schema if db_schema is not None else "ai"
        self.metadata: MetaData = MetaData(schema=self.db_schema)
        self.create_schema: bool = create_schema

        # Initialize database session
        self.Session: scoped_session = scoped_session(sessionmaker(bind=self.db_engine))

        # Deserialized history-run objects, keyed per run by the raw row text;
        # see SessionRunObjectCache for the invalidation and immutability
        # contract. Per adapter instance, so it can never serve runs across
        # databases.
        self._run_object_cache = SessionRunObjectCache()
        # Zero means never refreshed; get_metrics uses this to refresh lazily, at most once per minute.
        # stop_metrics_refresh_on_read sets it to infinity, so reads never calculate
        self._metrics_refreshed_at: float = 0.0
        # The days whose metrics a write could not reopen, retried by the next write
        self._metrics_days_not_reopened: Set[date] = set()

    def close(self) -> None:
        """Close database connections and dispose of the connection pool.

        Should be called during application shutdown to properly release
        all database connections.
        """
        if self.db_engine is not None:
            self.db_engine.dispose()

    # -- DB methods --
    def table_exists(self, table_name: str) -> bool:
        """Check if a table with the given name exists in the MySQL database.

        Args:
            table_name: Name of the table to check

        Returns:
            bool: True if the table exists in the database, False otherwise
        """
        with self.Session() as sess:
            return is_table_available(session=sess, table_name=table_name, db_schema=self.db_schema)

    def _create_table(self, table_name: str, table_type: str) -> Table:
        """
        Create a table with the appropriate schema based on the table type.

        Args:
            table_name (str): Name of the table to create
            table_type (str): Type of table (used to get schema definition)

        Returns:
            Table: SQLAlchemy Table object
        """
        try:
            # Pass traces_table_name and db_schema for spans table foreign key resolution
            table_schema = get_table_schema_definition(
                table_type,
                traces_table_name=self.trace_table_name,
                db_schema=self.db_schema,
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
            unique_constraints: List[str] = []
            schema_unique_constraints = table_schema.pop("_unique_constraints", [])
            schema_composite_indexes = table_schema.pop("_composite_indexes", [])

            # Get the columns, indexes, and unique constraints from the table schema
            for col_name, col_config in table_schema.items():
                column_args = [col_name, col_config["type"]()]
                column_kwargs = {}
                if col_config.get("primary_key", False):
                    column_kwargs["primary_key"] = True
                if "nullable" in col_config:
                    column_kwargs["nullable"] = col_config["nullable"]
                if col_config.get("index", False):
                    indexes.append(col_name)
                if col_config.get("unique", False):
                    column_kwargs["unique"] = True
                    unique_constraints.append(col_name)

                # Handle foreign key constraint
                if "foreign_key" in col_config:
                    fk_kwargs: Dict[str, Any] = {}
                    if "ondelete" in col_config:
                        fk_kwargs["ondelete"] = col_config["ondelete"]
                    column_args.append(ForeignKey(col_config["foreign_key"], **fk_kwargs))

                columns.append(Column(*column_args, **column_kwargs))  # type: ignore

            # Create the table object
            table = Table(table_name, self.metadata, *columns, schema=self.db_schema)

            # Add multi-column unique constraints with table-specific names
            for constraint in schema_unique_constraints:
                constraint_name = f"{table_name}_{constraint['name']}"
                constraint_columns = constraint["columns"]
                table.append_constraint(UniqueConstraint(*constraint_columns, name=constraint_name))

            # Add indexes to the table definition
            for idx_col in indexes:
                idx_name = f"idx_{table_name}_{idx_col}"
                table.append_constraint(Index(idx_name, idx_col))

            # Add multi-column (composite) indexes with table-specific names
            for composite in schema_composite_indexes:
                composite_name = f"{table_name}_{composite['name']}"
                table.append_constraint(Index(composite_name, *composite["columns"]))

            if self.create_schema:
                with self.Session() as sess, sess.begin():
                    create_schema(session=sess, db_schema=self.db_schema)

            # Create table
            table_created = False
            if not self.table_exists(table_name):
                table.create(self.db_engine, checkfirst=True)
                log_debug(f"Successfully created table '{table_name}'")
                table_created = True
            else:
                log_debug(f"Table {self.db_schema}.{table_name} already exists, skipping creation")

            # Create indexes
            for idx in table.indexes:
                try:
                    # Check if index already exists
                    with self.Session() as sess:
                        exists_query = text(
                            "SELECT 1 FROM information_schema.statistics WHERE table_schema = :schema "
                            "AND table_name = :table_name AND index_name = :index_name"
                        )
                        exists = (
                            sess.execute(
                                exists_query,
                                {"schema": self.db_schema, "table_name": table_name, "index_name": idx.name},
                            ).scalar()
                            is not None
                        )
                        if exists:
                            continue

                    idx.create(self.db_engine)

                    log_debug(f"Created index: {idx.name} for table {self.db_schema}.{table_name}")
                except Exception as e:
                    log_error(f"Error creating index {idx.name}: {str(e)}")

            # Store the schema version for the created table
            if table_name != self.versions_table_name and table_created:
                latest_schema_version = MigrationManager(self).latest_schema_version
                self.upsert_schema_version(table_name=table_name, version=latest_schema_version.public)
                log_info(
                    f"Successfully stored version {latest_schema_version.public} in database for table {table_name}"
                )

            return table

        except Exception as e:
            log_error(f"Could not create table {self.db_schema}.{table_name}: {str(e)}")
            raise

    def _create_all_tables(self):
        """Create all tables for the database."""
        tables_to_create = [
            (self.session_table_name, "sessions"),
            (self.runs_table_name, "runs"),
            (self.memory_table_name, "memories"),
            (self.metrics_table_name, "metrics"),
            (self.component_metrics_table_name, "component_metrics"),
            (self.aggregate_metrics_table_name, "aggregate_metrics"),
            (self.metrics_refreshes_table_name, "metrics_refreshes"),
            (self.eval_table_name, "evals"),
            (self.knowledge_table_name, "knowledge"),
            (self.trace_table_name, "traces"),
            (self.span_table_name, "spans"),
            (self.versions_table_name, "versions"),
        ]

        for table_name, table_type in tables_to_create:
            # Re-verify against the live database (one existence check each), so
            # this call still recreates tables dropped externally - including
            # tables registered only as an FK side effect of another reflection
            if not self.table_exists(table_name):
                self._invalidate_table_cache(table_name)
            self._get_or_create_table(table_name=table_name, table_type=table_type, create_table_if_not_found=True)

    def _get_table(self, table_type: str, create_table_if_not_found: Optional[bool] = False) -> Optional[Table]:
        if table_type == "sessions":
            self.session_table = self._get_or_create_table(
                table_name=self.session_table_name,
                table_type="sessions",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.session_table

        if table_type == "runs":
            self.runs_table = self._get_or_create_table(
                table_name=self.runs_table_name,
                table_type="runs",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.runs_table

        if table_type == "memories":
            self.memory_table = self._get_or_create_table(
                table_name=self.memory_table_name,
                table_type="memories",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.memory_table

        if table_type == "metrics":
            self.metrics_table = self._get_or_create_table(
                table_name=self.metrics_table_name,
                table_type="metrics",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.metrics_table

        if table_type == "component_metrics":
            self.component_metrics_table = self._get_or_create_table(
                table_name=self.component_metrics_table_name,
                table_type="component_metrics",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.component_metrics_table

        if table_type == "aggregate_metrics":
            self.aggregate_metrics_table = self._get_or_create_table(
                table_name=self.aggregate_metrics_table_name,
                table_type="aggregate_metrics",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.aggregate_metrics_table

        if table_type == "metrics_refreshes":
            self.metrics_refreshes_table = self._get_or_create_table(
                table_name=self.metrics_refreshes_table_name,
                table_type="metrics_refreshes",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.metrics_refreshes_table

        if table_type == "evals":
            self.eval_table = self._get_or_create_table(
                table_name=self.eval_table_name,
                table_type="evals",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.eval_table

        if table_type == "knowledge":
            self.knowledge_table = self._get_or_create_table(
                table_name=self.knowledge_table_name,
                table_type="knowledge",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.knowledge_table

        if table_type == "versions":
            self.versions_table = self._get_or_create_table(
                table_name=self.versions_table_name,
                table_type="versions",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.versions_table

        if table_type == "traces":
            self.traces_table = self._get_or_create_table(
                table_name=self.trace_table_name,
                table_type="traces",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.traces_table

        if table_type == "spans":
            # Ensure traces table exists first (spans has FK to traces)
            if create_table_if_not_found:
                self._get_table(table_type="traces", create_table_if_not_found=True)

            self.spans_table = self._get_or_create_table(
                table_name=self.span_table_name,
                table_type="spans",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.spans_table

        raise ValueError(f"Unknown table type: {table_type}")

    def _resolve_table(
        self, table_name: str, table_type: str, create_table_if_not_found: Optional[bool] = False
    ) -> Optional[Table]:
        """
        Check if the table exists and is valid, else create it.

        Args:
            table_name (str): Name of the table to get or create
            table_type (str): Type of table (used to get schema definition)

        Returns:
            Table: SQLAlchemy Table object representing the schema.
        """
        with self.Session() as sess, sess.begin():
            table_is_available = is_table_available(session=sess, table_name=table_name, db_schema=self.db_schema)

        if not table_is_available:
            if not create_table_if_not_found:
                return None

            created_table = self._create_table(table_name=table_name, table_type=table_type)
            self._store_resolved_table(table_type, table_name, created_table)
            return created_table

        if not is_valid_table(
            db_engine=self.db_engine,
            table_name=table_name,
            table_type=table_type,
            db_schema=self.db_schema,
        ):
            raise table_schema_mismatch_error(f"{self.db_schema}.{table_name}", table_type=table_type)

        try:
            table = Table(table_name, self.metadata, schema=self.db_schema, autoload_with=self.db_engine)
            # MariaDB loads a JSON column as text, which dicts are written to
            if self.db_engine.dialect.is_mariadb:  # type: ignore[attr-defined]
                set_json_column_types(table, table_type)
            self._store_resolved_table(table_type, table_name, table)
            return table

        except Exception as e:
            log_error(f"Error loading existing table {self.db_schema}.{table_name}: {str(e)}")
            raise

    def get_latest_schema_version(self, table_name: str) -> str:
        """Get the latest version of the database schema."""
        table = self._get_table(table_type="versions", create_table_if_not_found=True)
        with self.Session() as sess:
            # Latest version for the given table
            stmt = select(table).where(table.c.table_name == table_name).order_by(table.c.version.desc()).limit(1)  # type: ignore
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
            stmt = mysql.insert(table).values(  # type: ignore
                table_name=table_name,
                version=version,
                created_at=current_datetime,  # Store as ISO format string
                updated_at=current_datetime,
            )
            # Update version if table_name already exists
            stmt = stmt.on_duplicate_key_update(
                version=version,
                created_at=current_datetime,
                updated_at=current_datetime,
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
            True if the column was dropped, False if it did not exist.
        """
        with self.Session() as sess, sess.begin():
            column_exists = (
                sess.execute(
                    text(
                        "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
                        "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table AND COLUMN_NAME = 'runs'"
                    ),
                    {"schema": self.db_schema, "table": self.session_table_name},
                ).scalar()
                is not None
            )
            if not column_exists:
                log_info(f"{self.session_table_name}.runs column does not exist, nothing to clean up")
                return False

            if not force:
                pending = (
                    sess.execute(
                        text(
                            f"SELECT COUNT(*) FROM `{self.db_schema}`.`{self.session_table_name}` WHERE runs IS NOT NULL"
                        )
                    ).scalar()
                    or 0
                )
                if pending > 0:
                    raise RuntimeError(
                        f"Refusing to drop {self.session_table_name}.runs: {pending} session(s) still have "
                        "non-null `runs` content. Run MigrationManager(db).up() first, or pass force=True."
                    )

            log_info(f"Dropping legacy runs column from {self.session_table_name}")
            sess.execute(text(f"ALTER TABLE `{self.db_schema}`.`{self.session_table_name}` DROP COLUMN `runs`"))

        self._invalidate_table_cache(self.session_table_name)
        return True

    # -- Run methods --
    def _get_session_run_rows(self, sess, runs_table: Table, session_id: str) -> List[Tuple[str, str]]:
        """(run_id, raw run_data text) for the whole session, in insertion order.

        The raw text feeds the run-object cache, which parses and rebuilds a
        run only when its text changed since the last read. The cast keeps the
        JSON column's result processor out of the way -- the whole point is to
        not parse unchanged rows.
        """
        stmt = (
            select(runs_table.c.run_id, cast(runs_table.c.run_data, TEXT))
            .where(runs_table.c.session_id == session_id)
            .order_by(
                runs_table.c.run_index.asc(),
                runs_table.c.created_at.asc(),
                runs_table.c.run_id.asc(),
            )
        )
        return [
            (run_id, run_data if isinstance(run_data, str) else json.dumps(run_data))
            for run_id, run_data in sess.execute(stmt).fetchall()
        ]

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

            backfill_lock: Optional[str] = None
            with self.Session() as sess:
                try:
                    with sess.begin():
                        # Read committed on MariaDB, as on PostgreSQL: MariaDB fails a write to a row changed since
                        # the transaction's first read, as a day another write reopened meanwhile is. MySQL refuses
                        # a write read committed when it logs statements
                        if self.db_engine.dialect.is_mariadb:  # type: ignore[attr-defined]
                            sess.connection(execution_options={"isolation_level": "READ COMMITTED"})
                        # A new run always lands after the session's existing rows. Callers
                        # pass the run's position in the in-memory ``session.runs`` list, and
                        # after runs were deleted from the front of that list the position
                        # collides with, or sorts before, rows that still exist. ON DUPLICATE
                        # KEY preserves the existing index, so this only affects a genuine
                        # insert. GET_LOCK serializes same-session inserts so two concurrent
                        # max-reads cannot land duplicate indexes; it is connection-scoped and
                        # survives COMMIT, so it is released in the finally below.
                        backfill_lock = run_index_lock_name(session_id)
                        acquired = sess.execute(text("SELECT GET_LOCK(:name, 5)"), {"name": backfill_lock}).scalar()
                        if not acquired:
                            log_warning(
                                f"run_index backfill lock timed out for session {session_id}; proceeding unserialized"
                            )
                        current_max = sess.execute(
                            select(func.max(runs_table.c.run_index)).where(runs_table.c.session_id == session_id)
                        ).scalar()
                        next_index = (current_max + 1) if current_max is not None else 0
                        provided_index = row.get("run_index")
                        row["run_index"] = next_index if provided_index is None else max(provided_index, next_index)

                        stmt = mysql.insert(runs_table).values(**row)  # type: ignore
                        stmt = stmt.on_duplicate_key_update(
                            status=stmt.inserted.status,
                            run_data=stmt.inserted.run_data,
                            user_id=stmt.inserted.user_id,
                            parent_run_id=stmt.inserted.parent_run_id,
                            updated_at=stmt.inserted.updated_at,
                            # Preserve a non-null run_index; only fill it in for a legacy row
                            # that was stored as NULL (COALESCE keeps the existing value if set).
                            run_index=func.coalesce(runs_table.c.run_index, stmt.inserted.run_index),
                        )
                        sess.execute(stmt)
                        # The stored created_at, which a resumed run keeps
                        created_at = sess.execute(
                            select(runs_table.c.created_at).where(runs_table.c.run_id == row["run_id"])
                        ).scalar_one()
                        self._reopen_metrics_days(sess, [created_at])
                finally:
                    if backfill_lock is not None:
                        try:
                            sess.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": backfill_lock})
                        except Exception:
                            pass  # a dead connection frees its named locks on close

        except Exception as e:
            log_error(f"Exception upserting run to runs table: {str(e)}")
            raise e

    def get_run(
        self, run_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[RunOutput, TeamRunOutput, WorkflowRunOutput, Dict[str, Any]]]:
        """Read a single run from the runs table."""
        try:
            table = self._get_table(table_type="runs")
            if table is None:
                return None

            with self.Session() as sess:
                result = sess.execute(select(table).where(table.c.run_id == run_id)).fetchone()
                if result is None:
                    return None
                run_row = dict(result._mapping)

            if not deserialize:
                return run_row
            return deserialize_run(run_row.get("run_type"), run_row["run_data"])

        except Exception as e:
            log_error(f"Exception reading from runs table: {str(e)}")
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
        """Get all runs matching the given filters."""
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
                run_rows = [dict(record._mapping) for record in records]

            if not deserialize:
                return run_rows, total_count
            return [deserialize_run(row.get("run_type"), row["run_data"]) for row in run_rows]

        except Exception as e:
            log_error(f"Exception reading from runs table: {str(e)}")
            raise e

    def _scrub_run_ids_from_legacy_blob(self, run_ids: List[str], sess: Any, sessions_table: Any) -> bool:
        """Remove ``run_ids`` from every session row's legacy ``runs`` JSON column.

        Partial-migration state: the v3 migration copied runs into the runs table
        but kept the legacy blob as a backup, and ``merge_runs_table_with_legacy_blob``
        still reads it. Runs inside the caller's transaction so the row delete and
        the scrub commit together or not at all; a fully migrated DB (no ``runs``
        column) is a no-op. ``sessions_table`` is resolved by the caller before
        the transaction opens, because ``_get_table`` uses the same scoped session.

        Returns True if any legacy blob held one of ``run_ids``.
        """
        if not run_ids or sessions_table is None or "runs" not in sessions_table.c:
            return False
        wanted = set(run_ids)
        scrubbed = False
        rows = sess.execute(
            select(sessions_table.c.session_id, sessions_table.c.runs).where(sessions_table.c.runs.isnot(None))
        ).fetchall()
        for sid, runs_raw in rows:
            if isinstance(runs_raw, str):
                try:
                    runs_list = json.loads(runs_raw)
                except (json.JSONDecodeError, TypeError):
                    continue
            else:
                runs_list = runs_raw
            if not isinstance(runs_list, list):
                continue
            kept = [r for r in runs_list if not (isinstance(r, dict) and r.get("run_id") in wanted)]
            if len(kept) == len(runs_list):
                continue
            sess.execute(
                sessions_table.update().where(sessions_table.c.session_id == sid).values(runs=json.dumps(kept))
            )
            scrubbed = True
        return scrubbed

    def delete_run(self, run_id: str) -> bool:
        """Delete a single run from the runs table.

        Also scrubs it from the legacy ``runs`` blob in the same transaction, so a
        partially migrated session cannot resurrect it on the next read.

        Args:
            run_id (str): The ID of the run to delete.

        Returns:
            bool: True if the run was removed from the runs table or a legacy blob, False otherwise.
        """
        try:
            table = self._get_table(table_type="runs")
            sessions_table = self._get_table(table_type="sessions")
            with self.Session() as sess, sess.begin():
                deleted = False
                if table is not None:
                    result = sess.execute(table.delete().where(table.c.run_id == run_id))
                    deleted = result.rowcount > 0
                scrubbed = self._scrub_run_ids_from_legacy_blob([run_id], sess, sessions_table)
            return deleted or scrubbed
        except Exception as e:
            log_error(f"Error deleting run: {str(e)}")
            raise e

    def delete_runs(self, run_ids: List[str]) -> None:
        """Delete all given runs from the runs table.

        Also scrubs them from the legacy ``runs`` blob in the same transaction, so a
        partially migrated session cannot resurrect them on the next read.

        Args:
            run_ids (List[str]): The IDs of the runs to delete.
        """
        try:
            table = self._get_table(table_type="runs")
            sessions_table = self._get_table(table_type="sessions")
            with self.Session() as sess, sess.begin():
                if table is not None:
                    result = sess.execute(table.delete().where(table.c.run_id.in_(run_ids)))
                    log_debug(f"Successfully deleted {result.rowcount} runs")
                self._scrub_run_ids_from_legacy_blob(list(run_ids), sess, sessions_table)
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

        Returns:
            bool: True if the session was deleted, False otherwise.

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
                    log_debug(f"No session found to delete with session_id: {session_id} in table {table.name}")
                    return False

                if runs_table is not None:
                    sess.execute(runs_table.delete().where(runs_table.c.session_id == session_id))

                log_debug(f"Successfully deleted session with session_id: {session_id} in table {table.name}")
                # A deleted session's deserialized history must not stay resident.
                self._run_object_cache.drop_session(session_id)
                return True

        except Exception as e:
            log_error(f"Error deleting session: {str(e)}")
            return False

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
                delete_stmt = table.delete().where(table.c.session_id.in_(session_ids))
                if user_id is not None:
                    delete_stmt = delete_stmt.where(table.c.user_id == user_id)
                result = sess.execute(delete_stmt)

                if runs_table is not None:
                    runs_delete_stmt = runs_table.delete().where(runs_table.c.session_id.in_(session_ids))
                    if user_id is not None:
                        runs_delete_stmt = runs_delete_stmt.where(runs_table.c.user_id == user_id)
                    sess.execute(runs_delete_stmt)

            for deleted_id in session_ids:
                self._run_object_cache.drop_session(deleted_id)

            log_debug(f"Successfully deleted {result.rowcount} sessions")

        except Exception as e:
            log_error(f"Error deleting sessions: {str(e)}")

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
            session_type (Optional[SessionType]): Type of session to get. Defaults to None.
            user_id (Optional[str]): User ID to filter by. Defaults to None.
            deserialize (Optional[bool]): Whether to deserialize the session. Defaults to True.

        Returns:
            Union[Session, Dict[str, Any], None]:
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

            with self.Session() as sess:
                stmt = select(table).where(table.c.session_id == session_id)

                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                result = sess.execute(stmt).fetchone()
                if result is None:
                    return None

                session = dict(result._mapping)

                # Attach the runs stored in the runs table, merged with any runs still
                # sitting in the legacy `runs` column (so partially-migrated sessions
                # don't silently lose history).
                run_rows: Optional[List[Tuple[str, str]]] = None
                legacy_runs = session.get("runs")
                if runs_table is not None and runs_limit is not None and not legacy_runs:
                    # Fully migrated: push "most recent N" down to the DB (indexed).
                    session["runs"] = self._get_session_runs_data(
                        sess=sess, runs_table=runs_table, session_id=session_id, limit=runs_limit
                    )
                elif (
                    runs_table is not None
                    and not legacy_runs
                    and deserialize
                    and session.get("session_type") == SessionType.AGENT.value
                    and (session_type is None or session_type == SessionType.AGENT)
                ):
                    # Fully-migrated agent session on the per-turn path: fetch
                    # the rows raw and serve run objects from the cache instead
                    # of rebuilding every run on every read.
                    run_rows = self._get_session_run_rows(sess=sess, runs_table=runs_table, session_id=session_id)
                    session["runs"] = None
                elif runs_table is not None:
                    # Full load + merge. Also the un-migrated fallback: the legacy blob
                    # holds the whole history in one column, so "last N" can't be pushed
                    # to SQL — load all, merge, then filter+slice to match the migrated path.
                    runs_data = self._get_session_runs_data(sess=sess, runs_table=runs_table, session_id=session_id)
                    merged = merge_runs_table_with_legacy_blob(runs_data, legacy_runs)
                    if runs_limit is not None:
                        merged = filter_context_runs(merged)[-runs_limit:]
                    session["runs"] = merged
                elif runs_limit is not None:
                    # No runs table yet (fully un-migrated): filter+slice the legacy blob.
                    merged = merge_runs_table_with_legacy_blob([], legacy_runs)
                    session["runs"] = filter_context_runs(merged)[-runs_limit:]

            if not deserialize:
                return session

            if run_rows is not None:
                session_obj = deserialize_session(session_type, session)
                session_obj.runs = self._run_object_cache.runs_from_rows(session_id, run_rows)  # type: ignore[union-attr]
                return session_obj
            return deserialize_session(session_type, session)

        except Exception as e:
            log_error(f"Exception reading from session table: {str(e)}")
            return None

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
        filter_expr: Optional[Dict[str, Any]] = None,
    ) -> Union[List[Session], Tuple[List[Dict[str, Any]], int]]:
        """
        Get all sessions in the given table. Can filter by user_id and entity_id.

        Args:
            session_type (Optional[SessionType]): The type of sessions to get.
            user_id (Optional[str]): The ID of the user to filter by.
            component_id (Optional[str]): The ID of the agent / workflow to filter by.
            start_timestamp (Optional[int]): The start timestamp to filter by.
            end_timestamp (Optional[int]): The end timestamp to filter by.
            session_name (Optional[str]): The name of the session to filter by.
            limit (Optional[int]): The maximum number of sessions to return. Defaults to None.
            page (Optional[int]): The page number to return. Defaults to None.
            sort_by (Optional[str]): The field to sort by. Defaults to None.
            sort_order (Optional[str]): The sort order. Defaults to None.
            deserialize (Optional[bool]): Whether to deserialize the sessions. Defaults to True.

        Returns:
            Union[List[Session], Tuple[List[Dict], int]]:
                - When deserialize=True: List of Session objects
                - When deserialize=False: Tuple of (session dictionaries, total count)

        Raises:
            Exception: If an error occurs during retrieval.
        """
        from agno.db.session_filters import normalize_session_filter, session_filter_to_sqlalchemy

        filter_expr = normalize_session_filter(filter_expr)
        validate_pagination(limit, page)
        try:
            table = self._get_table(table_type="sessions")
            if table is None:
                return [] if deserialize else ([], 0)
            runs_table = self._get_table(table_type="runs")

            with self.Session() as sess, sess.begin():
                stmt = select(table)

                if filter_expr is not None:
                    # Binary collation keeps string comparisons case-sensitive, matching other SQL backends.
                    stmt = stmt.where(session_filter_to_sqlalchemy(filter_expr, table, collation="utf8mb4_bin"))

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
                    # MySQL JSON extraction syntax
                    stmt = stmt.where(
                        func.coalesce(
                            func.json_unquote(func.json_extract(table.c.session_data, "$.session_name")), ""
                        ).ilike(f"%{session_name}%")
                    )
                if session_type is not None:
                    session_type_value = session_type.value if isinstance(session_type, SessionType) else session_type
                    stmt = stmt.where(table.c.session_type == session_type_value)

                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = sess.execute(count_stmt).scalar() or 0

                # Sorting
                stmt = apply_sorting(stmt, table, sort_by, sort_order)

                # Paginating
                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset((page - 1) * limit)

                result = sess.execute(stmt).fetchall()
                if not result:
                    # An empty page still reports the total, so callers can paginate past the end.
                    return [] if deserialize else ([], total_count)

                session_dicts = [dict(row._mapping) for row in result]

                if runs_table is not None:
                    runs_by_session = self._get_sessions_runs_data(
                        sess=sess, runs_table=runs_table, session_ids=[s["session_id"] for s in session_dicts]
                    )
                    for s in session_dicts:
                        runs_data = runs_by_session.get(s["session_id"], [])
                        s["runs"] = merge_runs_table_with_legacy_blob(runs_data, s.get("runs"))

                if not deserialize:
                    return session_dicts, total_count

                return deserialize_sessions(session_type, session_dicts)

        except Exception as e:
            log_error(f"Exception getting sessions: {str(e)}")
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
            session_type (SessionType): The type of session to rename.
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
            table = self._get_table(table_type="sessions")
            if table is None:
                return None
            runs_table = self._get_table(table_type="runs")

            with self.Session() as sess, sess.begin():
                # MySQL JSON_SET syntax
                stmt = (
                    update(table)
                    .where(table.c.session_id == session_id)
                    .values(session_data=func.json_set(table.c.session_data, "$.session_name", session_name))
                )
                if session_type is not None:
                    stmt = stmt.where(table.c.session_type == session_type.value)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                sess.execute(stmt)

                # Fetch the updated row
                select_stmt = select(table).where(table.c.session_id == session_id)
                if session_type is not None:
                    select_stmt = select_stmt.where(table.c.session_type == session_type.value)
                if user_id is not None:
                    select_stmt = select_stmt.where(table.c.user_id == user_id)
                result = sess.execute(select_stmt)
                row = result.fetchone()
                if not row:
                    return None

                session = dict(row._mapping)
                if runs_table is not None:
                    runs_data = self._get_session_runs_data(sess=sess, runs_table=runs_table, session_id=session_id)
                    session["runs"] = merge_runs_table_with_legacy_blob(runs_data, session.get("runs"))

            if not deserialize:
                return session

            return deserialize_session(session_type, session)

        except Exception as e:
            log_error(f"Exception renaming session: {str(e)}")
            return None

    def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """
        Insert or update a session in the database.

        Args:
            session (Session): The session data to upsert.
            deserialize (Optional[bool]): Whether to deserialize the session. Defaults to True.

        Returns:
            Optional[Union[Session, Dict[str, Any]]]:
                - When deserialize=True: Session object
                - When deserialize=False: Session dictionary

        Raises:
            Exception: If an error occurs during upsert.
        """
        try:
            table = self._get_table(table_type="sessions", create_table_if_not_found=True)
            if table is None:
                return None

            session_dict = session.to_dict(include_runs=False)

            if isinstance(session, AgentSession):
                values = dict(
                    session_type=SessionType.AGENT.value,
                    agent_id=session_dict.get("agent_id"),
                    user_id=session_dict.get("user_id"),
                    agent_data=session_dict.get("agent_data"),
                    session_data=session_dict.get("session_data"),
                    summary=session_dict.get("summary"),
                    metadata=session_dict.get("metadata"),
                )
            elif isinstance(session, TeamSession):
                values = dict(
                    session_type=SessionType.TEAM.value,
                    team_id=session_dict.get("team_id"),
                    user_id=session_dict.get("user_id"),
                    team_data=session_dict.get("team_data"),
                    session_data=session_dict.get("session_data"),
                    summary=session_dict.get("summary"),
                    metadata=session_dict.get("metadata"),
                )
            elif isinstance(session, WorkflowSession):
                values = dict(
                    session_type=SessionType.WORKFLOW.value,
                    workflow_id=session_dict.get("workflow_id"),
                    user_id=session_dict.get("user_id"),
                    workflow_data=session_dict.get("workflow_data"),
                    session_data=session_dict.get("session_data"),
                    summary=session_dict.get("summary"),
                    metadata=session_dict.get("metadata"),
                )
            else:
                raise ValueError(f"Invalid session type: {session.session_type}")

            update_values = {k: v for k, v in values.items() if k != "session_type"}
            update_values["updated_at"] = int(time.time())
            # Legacy `runs` column intentionally preserved as a frozen backup; only
            # cleanup_legacy_runs_column() reclaims it (see upsert_session docstring).

            with self.Session() as sess, sess.begin():
                # Read committed on MariaDB, as on PostgreSQL: MariaDB fails a write to a row changed since the
                # transaction's first read, as a day another write reopened meanwhile is. MySQL refuses a write read
                # committed when it logs statements
                if self.db_engine.dialect.is_mariadb:  # type: ignore[attr-defined]
                    sess.connection(execution_options={"isolation_level": "READ COMMITTED"})
                existing_row = sess.execute(
                    select(table.c.user_id)
                    .where(table.c.session_id == session_dict.get("session_id"))
                    .with_for_update()
                ).fetchone()
                if existing_row is not None:
                    existing_uid = existing_row[0]
                    if existing_uid is not None and existing_uid != session_dict.get("user_id"):
                        return None

                reopen_session_ids = self._get_metrics_reopen_session_ids(
                    sess,
                    table,
                    [
                        {
                            "session_id": session_dict.get("session_id"),
                            "created_at": session_dict.get("created_at"),
                            **values,
                        }
                    ],
                )
                stmt = mysql.insert(table).values(
                    session_id=session_dict.get("session_id"),
                    created_at=session_dict.get("created_at"),
                    updated_at=session_dict.get("created_at"),
                    **values,
                )
                stmt = stmt.on_duplicate_key_update(**update_values)
                sess.execute(stmt)

                # Fetch the row
                select_stmt = select(table).where(table.c.session_id == session_dict.get("session_id"))
                row = sess.execute(select_stmt).fetchone()
                if not row:
                    return None
                session_dict = dict(row._mapping)
                if session_dict["session_id"] in reopen_session_ids:
                    self._reopen_metrics_days(sess, [session_dict["created_at"]])

            session_dict["runs"] = [run if isinstance(run, dict) else run.to_dict() for run in session.runs or []]
            if not deserialize:
                return session_dict
            return deserialize_session(None, session_dict)

        except Exception as e:
            log_error(f"Exception upserting into sessions table: {str(e)}")
            return None

    def upsert_sessions(
        self, sessions: List[Session], deserialize: Optional[bool] = True, preserve_updated_at: bool = False
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

            # Process each session type in bulk
            with self.Session() as sess, sess.begin():
                # Read committed on MariaDB, as on PostgreSQL: MariaDB fails a write to a row changed since the
                # transaction's first read, as a day another write reopened meanwhile is. MySQL refuses a write read
                # committed when it logs statements
                if self.db_engine.dialect.is_mariadb:  # type: ignore[attr-defined]
                    sess.connection(execution_options={"isolation_level": "READ COMMITTED"})
                # Bulk upsert agent sessions
                if agent_sessions:
                    agent_data = []
                    for session in agent_sessions:
                        session_dict = session.to_dict(include_runs=False)
                        # Use preserved updated_at if flag is set and value exists, otherwise use current time
                        updated_at = session_dict.get("updated_at") if preserve_updated_at else int(time.time())
                        agent_data.append(
                            {
                                "session_id": session_dict.get("session_id"),
                                "session_type": SessionType.AGENT.value,
                                "agent_id": session_dict.get("agent_id"),
                                "user_id": session_dict.get("user_id"),
                                "agent_data": session_dict.get("agent_data"),
                                "session_data": session_dict.get("session_data"),
                                "summary": session_dict.get("summary"),
                                "metadata": session_dict.get("metadata"),
                                "created_at": session_dict.get("created_at"),
                                "updated_at": updated_at,
                            }
                        )

                    if agent_data:
                        stmt = mysql.insert(table)
                        stmt = stmt.on_duplicate_key_update(
                            agent_id=stmt.inserted.agent_id,
                            user_id=stmt.inserted.user_id,
                            agent_data=stmt.inserted.agent_data,
                            session_data=stmt.inserted.session_data,
                            summary=stmt.inserted.summary,
                            metadata=stmt.inserted.metadata,
                            updated_at=stmt.inserted.updated_at,
                        )
                        reopen_session_ids = self._get_metrics_reopen_session_ids(sess, table, agent_data)
                        sess.execute(stmt, agent_data)

                        # Fetch the results for agent sessions
                        agent_ids = [session.session_id for session in agent_sessions]
                        select_stmt = select(table).where(table.c.session_id.in_(agent_ids))
                        result = sess.execute(select_stmt).fetchall()
                        # The stored created_at, which a session keeps
                        self._reopen_metrics_days(
                            sess,
                            [
                                row._mapping["created_at"]
                                for row in result
                                if row._mapping["session_id"] in reopen_session_ids
                            ],
                        )

                        for row in result:
                            session_dict = _attach_runs(dict(row._mapping))
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
                        session_dict = session.to_dict(include_runs=False)
                        # Use preserved updated_at if flag is set and value exists, otherwise use current time
                        updated_at = session_dict.get("updated_at") if preserve_updated_at else int(time.time())
                        team_data.append(
                            {
                                "session_id": session_dict.get("session_id"),
                                "session_type": SessionType.TEAM.value,
                                "team_id": session_dict.get("team_id"),
                                "user_id": session_dict.get("user_id"),
                                "team_data": session_dict.get("team_data"),
                                "session_data": session_dict.get("session_data"),
                                "summary": session_dict.get("summary"),
                                "metadata": session_dict.get("metadata"),
                                "created_at": session_dict.get("created_at"),
                                "updated_at": updated_at,
                            }
                        )

                    if team_data:
                        stmt = mysql.insert(table)
                        stmt = stmt.on_duplicate_key_update(
                            team_id=stmt.inserted.team_id,
                            user_id=stmt.inserted.user_id,
                            team_data=stmt.inserted.team_data,
                            session_data=stmt.inserted.session_data,
                            summary=stmt.inserted.summary,
                            metadata=stmt.inserted.metadata,
                            updated_at=stmt.inserted.updated_at,
                        )
                        reopen_session_ids = self._get_metrics_reopen_session_ids(sess, table, team_data)
                        sess.execute(stmt, team_data)

                        # Fetch the results for team sessions
                        team_ids = [session.session_id for session in team_sessions]
                        select_stmt = select(table).where(table.c.session_id.in_(team_ids))
                        result = sess.execute(select_stmt).fetchall()
                        # The stored created_at, which a session keeps
                        self._reopen_metrics_days(
                            sess,
                            [
                                row._mapping["created_at"]
                                for row in result
                                if row._mapping["session_id"] in reopen_session_ids
                            ],
                        )

                        for row in result:
                            session_dict = _attach_runs(dict(row._mapping))
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
                        session_dict = session.to_dict(include_runs=False)
                        # Use preserved updated_at if flag is set and value exists, otherwise use current time
                        updated_at = session_dict.get("updated_at") if preserve_updated_at else int(time.time())
                        workflow_data.append(
                            {
                                "session_id": session_dict.get("session_id"),
                                "session_type": SessionType.WORKFLOW.value,
                                "workflow_id": session_dict.get("workflow_id"),
                                "user_id": session_dict.get("user_id"),
                                "workflow_data": session_dict.get("workflow_data"),
                                "session_data": session_dict.get("session_data"),
                                "summary": session_dict.get("summary"),
                                "metadata": session_dict.get("metadata"),
                                "created_at": session_dict.get("created_at"),
                                "updated_at": updated_at,
                            }
                        )

                    if workflow_data:
                        stmt = mysql.insert(table)
                        stmt = stmt.on_duplicate_key_update(
                            workflow_id=stmt.inserted.workflow_id,
                            user_id=stmt.inserted.user_id,
                            workflow_data=stmt.inserted.workflow_data,
                            session_data=stmt.inserted.session_data,
                            summary=stmt.inserted.summary,
                            metadata=stmt.inserted.metadata,
                            updated_at=stmt.inserted.updated_at,
                        )
                        reopen_session_ids = self._get_metrics_reopen_session_ids(sess, table, workflow_data)
                        sess.execute(stmt, workflow_data)

                        # Fetch the results for workflow sessions
                        workflow_ids = [session.session_id for session in workflow_sessions]
                        select_stmt = select(table).where(table.c.session_id.in_(workflow_ids))
                        result = sess.execute(select_stmt).fetchall()
                        # The stored created_at, which a session keeps
                        self._reopen_metrics_days(
                            sess,
                            [
                                row._mapping["created_at"]
                                for row in result
                                if row._mapping["session_id"] in reopen_session_ids
                            ],
                        )

                        for row in result:
                            session_dict = _attach_runs(dict(row._mapping))
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

    def get_all_memory_topics(self, user_id: Optional[str] = None) -> List[str]:
        """Get all memory topics from the database.

        Args:
            user_id (Optional[str]): Optional user ID to filter topics.

        Returns:
            List[str]: List of memory topics.
        """
        try:
            table = self._get_table(table_type="memories")
            if table is None:
                return []

            with self.Session() as sess, sess.begin():
                # MySQL approach: extract JSON array elements differently
                stmt = select(table.c.topics)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                result = sess.execute(stmt).fetchall()

                topics_set = set()
                for row in result:
                    if row[0]:
                        # Parse JSON array and add topics to set
                        import json

                        try:
                            topics = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                            if isinstance(topics, list):
                                topics_set.update(topics)
                        except Exception:
                            pass

                return list(topics_set)

        except Exception as e:
            log_error(f"Exception reading from memory table: {str(e)}")
            raise e

    def get_user_memory(
        self, memory_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[UserMemory]:
        """Get a memory from the database.

        Args:
            memory_id (str): The ID of the memory to get.
            deserialize (Optional[bool]): Whether to deserialize the memory. Defaults to True.
            user_id (Optional[str]): The user ID to filter by. Defaults to None.

        Returns:
            Union[UserMemory, Dict[str, Any], None]:
                - When deserialize=True: UserMemory object
                - When deserialize=False: UserMemory dictionary

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
                if not result:
                    return None

                memory_raw = result._mapping
                if not deserialize:
                    return memory_raw
            return UserMemory.from_dict(memory_raw)

        except Exception as e:
            log_error(f"Exception reading from memory table: {str(e)}")
            return None

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
        """Get all memories from the database as MemoryRow objects.

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
            deserialize (Optional[bool]): Whether to deserialize the memories. Defaults to True.


        Returns:
            Union[List[UserMemory], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of UserMemory objects
                - When deserialize=False: Tuple of (memory dictionaries, total count)

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
                    # MySQL JSON contains syntax
                    topic_conditions = []
                    for topic in topics:
                        topic_conditions.append(func.json_contains(table.c.topics, f'"{topic}"'))
                    stmt = stmt.where(and_(*topic_conditions))
                if search_content is not None:
                    stmt = stmt.where(cast(table.c.memory, TEXT).ilike(f"%{search_content}%"))

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
            log_error(f"Exception reading from memory table: {str(e)}")
            raise e

    def clear_memories(self) -> None:
        """Clear all user memories from the database."""
        try:
            table = self._get_table(table_type="memories")
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                sess.execute(table.delete())
        except Exception as e:
            log_error(f"Exception clearing user memories: {str(e)}")

    def get_user_memory_stats(
        self, limit: Optional[int] = None, page: Optional[int] = None, user_id: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get user memories stats.

        Args:
            limit (Optional[int]): The maximum number of user stats to return.
            page (Optional[int]): The page number.

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
                total_count = sess.execute(count_stmt).scalar()

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
            log_error(f"Exception getting user memory stats: {str(e)}")
            return [], 0

    def upsert_user_memory(
        self, memory: UserMemory, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Upsert a user memory in the database.

        Args:
            memory (UserMemory): The user memory to upsert.
            deserialize (Optional[bool]): Whether to deserialize the memory. Defaults to True.

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

            with self.Session() as sess, sess.begin():
                if memory.memory_id is None:
                    memory.memory_id = str(uuid4())

                current_time = int(time.time())

                stmt = mysql.insert(table).values(
                    memory_id=memory.memory_id,
                    memory=memory.memory,
                    input=memory.input,
                    user_id=memory.user_id,
                    agent_id=memory.agent_id,
                    team_id=memory.team_id,
                    topics=memory.topics,
                    feedback=memory.feedback,
                    created_at=memory.created_at,
                    updated_at=memory.created_at,
                )
                stmt = stmt.on_duplicate_key_update(
                    memory=memory.memory,
                    topics=memory.topics,
                    input=memory.input,
                    agent_id=memory.agent_id,
                    team_id=memory.team_id,
                    feedback=memory.feedback,
                    updated_at=current_time,
                    # Preserve created_at on update - don't overwrite existing value
                    created_at=table.c.created_at,
                )
                sess.execute(stmt)

                # Fetch the row
                select_stmt = select(table).where(table.c.memory_id == memory.memory_id)
                result = sess.execute(select_stmt)
                row = result.fetchone()
                if not row:
                    return None

            memory_raw = row._mapping
            if not memory_raw or not deserialize:
                return memory_raw

            return UserMemory.from_dict(memory_raw)

        except Exception as e:
            log_error(f"Exception upserting user memory: {str(e)}")
            return None

    def upsert_memories(
        self, memories: List[UserMemory], deserialize: Optional[bool] = True, preserve_updated_at: bool = False
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
                        "memory_id": memory.memory_id,
                        "memory": memory.memory,
                        "input": memory.input,
                        "user_id": memory.user_id,
                        "agent_id": memory.agent_id,
                        "team_id": memory.team_id,
                        "topics": memory.topics,
                        "feedback": memory.feedback,
                        "created_at": memory.created_at,
                        "updated_at": updated_at,
                    }
                )

            results: List[Union[UserMemory, Dict[str, Any]]] = []

            with self.Session() as sess, sess.begin():
                # Bulk upsert memories using MySQL ON DUPLICATE KEY UPDATE
                stmt = mysql.insert(table)
                stmt = stmt.on_duplicate_key_update(
                    memory=stmt.inserted.memory,
                    topics=stmt.inserted.topics,
                    input=stmt.inserted.input,
                    agent_id=stmt.inserted.agent_id,
                    team_id=stmt.inserted.team_id,
                    feedback=stmt.inserted.feedback,
                    updated_at=stmt.inserted.updated_at,
                    # Preserve created_at on update
                    created_at=table.c.created_at,
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

    # -- Metrics methods --
    def _reopen_metrics_days(self, sess: Any, created_ats: Sequence[Optional[int]]) -> None:
        """Reopen the metrics of each day a write changed, in the write's transaction, so the next calculation
        rebuilds it. A day it could not reopen is retried by the next write.

        Args:
            sess (Any): The session of the write.
            created_ats (Sequence[Optional[int]]): The stored created_at of each run or session the write changed.
        """
        # Sorted, so two writers reopening the same days lock them in the same order
        days = sorted(
            {day for created_at in created_ats if (day := metrics_day_to_reopen(created_at)) is not None}
            | self._metrics_days_not_reopened
        )
        if not days:
            return
        try:
            with sess.begin_nested():
                # Looked up only when a day reopens, the table loaded on the write's own connection: a lookup
                # through another session would not run in the write's transaction. None when no day was calculated yet
                aggregate_metrics_table = self._get_cached_table("aggregate_metrics", self.aggregate_metrics_table_name)
                if aggregate_metrics_table is None:
                    if not is_table_available(
                        session=sess, table_name=self.aggregate_metrics_table_name, db_schema=self.db_schema
                    ):
                        self._metrics_days_not_reopened.clear()
                        return
                    if not is_valid_table(
                        db_engine=self.db_engine,
                        table_name=self.aggregate_metrics_table_name,
                        table_type="aggregate_metrics",
                        db_schema=self.db_schema,
                    ):
                        raise table_schema_mismatch_error(
                            f"{self.db_schema}.{self.aggregate_metrics_table_name}", table_type="aggregate_metrics"
                        )
                    with self._resolve_lock:
                        aggregate_metrics_table = Table(
                            self.aggregate_metrics_table_name,
                            self.metadata,
                            schema=self.db_schema,
                            autoload_with=sess.connection(),
                        )
                        # MariaDB loads a JSON column as text, which dicts are written to
                        if self.db_engine.dialect.is_mariadb:  # type: ignore[attr-defined]
                            set_json_column_types(aggregate_metrics_table, "aggregate_metrics")
                        self._store_resolved_table(
                            "aggregate_metrics", self.aggregate_metrics_table_name, aggregate_metrics_table
                        )
                for day in days:
                    reopen_metrics_day(session=sess, table=aggregate_metrics_table, day=day)
            self._metrics_days_not_reopened.difference_update(days)
        except Exception as e:
            self._metrics_days_not_reopened.update(days)
            cause = getattr(e, "orig", e)
            # 1305: the savepoint is gone, as a deadlock rolled back the whole transaction and the write with it
            if cause.args[:1] == (1305,):
                raise
            log_warning(
                f"Could not reopen the metrics of {', '.join(str(day) for day in days)}: {database_error_message(e)}"
            )

    def _get_metrics_reopen_session_ids(
        self, sess: Any, table: Table, session_records: List[Dict[str, Any]]
    ) -> Set[str]:
        """Get the id of each session the given rows add, move to another owner or component, or give other
        compaction metrics."""
        written_session_ids = [record["session_id"] for record in session_records]
        stored_sessions: Dict[str, Any] = {}
        for start in range(0, len(written_session_ids), METRICS_IN_LIST_LIMIT):
            stored_stmt = select(
                table.c.session_id,
                table.c.user_id,
                table.c.agent_id,
                table.c.team_id,
                table.c.workflow_id,
                table.c.created_at,
                func.json_extract(table.c.session_data, "$.compaction_metrics", type_=JSON).label("compaction_metrics"),
            ).where(table.c.session_id.in_(written_session_ids[start : start + METRICS_IN_LIST_LIMIT]))
            stored_sessions.update((row.session_id, row) for row in sess.execute(stored_stmt).fetchall())
        session_ids: Set[str] = set()
        for record in session_records:
            stored_session = stored_sessions.get(record["session_id"])
            if (
                stored_session is None
                or any(
                    record[column] != getattr(stored_session, column)
                    for column in ["user_id", "agent_id", "team_id", "workflow_id"]
                    if column in record
                )
                or (
                    "session_data" in record
                    and (record["session_data"] if isinstance(record["session_data"], dict) else {}).get(
                        "compaction_metrics"
                    )
                    != stored_session.compaction_metrics
                )
            ):
                session_ids.add(record["session_id"])
        return session_ids

    def _get_metrics_table(self, table_type: str, table_name: str) -> Optional[Table]:
        """Get a metrics table, creating it on first use."""
        try:
            return self._get_table(table_type=table_type, create_table_if_not_found=True)
        except Exception as exc:
            # Another replica may have completed the first-time DDL meanwhile.
            cause = getattr(exc, "orig", exc)
            # 1050: the table already exists
            if cause.args[:1] != (1050,) or not self.table_exists(table_name):
                raise
            self._invalidate_table_cache(table_name)
            return self._get_table(table_type=table_type)

    def _get_metrics_refresh_row(self, refreshes_table: Table) -> Tuple[Optional[Dict[str, Any]], int]:
        """Get the row of the metrics refreshes table, and the locked_at at or before which its lock is stale, by the
        database's clock."""
        stale_lock_threshold = func.unix_timestamp() - METRICS_LOCK_SECONDS
        with self.Session() as sess:
            row = (
                sess.execute(
                    select(refreshes_table, stale_lock_threshold.label("stale_lock_threshold")).where(
                        refreshes_table.c.id == METRICS_REFRESH_ID
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                # Before the first refresh there is no lock to judge stale
                return None, 0
        refresh_row = dict(row)
        return refresh_row, refresh_row.pop("stale_lock_threshold")

    def _claim_metrics_refresh(self, refreshes_table: Table, worker_id: str) -> Optional[Dict[str, Any]]:
        """Claim the row of the metrics refreshes table, so one process calculates metrics at a time.

        Args:
            refreshes_table (Table): The metrics refreshes table.
            worker_id (str): The id of this calculation, which heartbeats and releases the claim.

        Returns:
            Optional[Dict[str, Any]]: The claimed row, with when the last calculation finished and its fingerprint.
                None when another process holds it.
        """
        now = func.unix_timestamp()
        claimed = refreshes_table.c.locked_by == worker_id
        try:
            with self.Session() as sess, sess.begin():
                # The holder's calculation keeps the row locked while it writes a day, so this returns instead of
                # waiting for it. Set back after the claim: MySQL has no lock wait of one transaction only
                lock_wait_timeout = sess.execute(text("SELECT @@SESSION.innodb_lock_wait_timeout")).scalar()
                sess.execute(text("SET SESSION innodb_lock_wait_timeout = 1"))
                try:
                    # One statement, so two processes never both find the row free
                    stmt = mysql.insert(refreshes_table).values(
                        id=METRICS_REFRESH_ID, locked_by=worker_id, locked_at=now, started_at=now, status="running"
                    )
                    # The columns are set in order, each seeing the ones before: the row is taken over first, and the
                    # rest moves only when it was
                    stmt = stmt.on_duplicate_key_update(
                        [
                            (
                                "locked_by",
                                case(
                                    # A stale lock is taken over: the process that held it stopped
                                    (
                                        or_(
                                            refreshes_table.c.locked_by.is_(None),
                                            refreshes_table.c.locked_at <= now - METRICS_LOCK_SECONDS,
                                        ),
                                        worker_id,
                                    ),
                                    else_=refreshes_table.c.locked_by,
                                ),
                            ),
                            ("locked_at", case((claimed, now), else_=refreshes_table.c.locked_at)),
                            ("started_at", case((claimed, now), else_=refreshes_table.c.started_at)),
                            ("status", case((claimed, "running"), else_=refreshes_table.c.status)),
                            ("error", case((claimed, None), else_=refreshes_table.c.error)),
                        ]
                    )
                    sess.execute(stmt)
                    # The row stays locked until the transaction ends, so it still holds what the claim wrote
                    result = sess.execute(select(refreshes_table).where(refreshes_table.c.id == METRICS_REFRESH_ID))
                    row = result.mappings().one()
                    return dict(row) if row["locked_by"] == worker_id else None
                finally:
                    sess.execute(
                        text("SET SESSION innodb_lock_wait_timeout = :seconds"), {"seconds": lock_wait_timeout}
                    )
        except DBAPIError as exc:
            if not is_lock_not_available(exc):
                raise
            return None

    def _mark_metrics_refresh_rebuild(self, refreshes_table: Table) -> bool:
        """Write a mark no fingerprint equals on the row of the metrics refreshes table, so the next calculation
        rebuilds yesterday and today. False when a calculation kept the row locked through every try."""
        for _ in range(3):
            try:
                with self.Session() as sess, sess.begin():
                    # A calculation keeps the row locked while it writes a day, and lets it go between days. Set back
                    # after the mark: MySQL has no lock wait of one transaction only
                    lock_wait_timeout = sess.execute(text("SELECT @@SESSION.innodb_lock_wait_timeout")).scalar()
                    sess.execute(text("SET SESSION innodb_lock_wait_timeout = 1"))
                    try:
                        sess.execute(
                            update(refreshes_table)
                            .where(refreshes_table.c.id == METRICS_REFRESH_ID)
                            .values(fingerprint=["rebuild", uuid4().hex])
                        )
                    finally:
                        sess.execute(
                            text("SET SESSION innodb_lock_wait_timeout = :seconds"), {"seconds": lock_wait_timeout}
                        )
                return True
            except DBAPIError as exc:
                if not is_lock_not_available(exc):
                    raise
        return False

    def _heartbeat_metrics_refresh(self, sess: Any, refreshes_table: Table, worker_id: str) -> bool:
        """Refresh locked_at for this worker's metrics refresh. False when another process took it over."""
        result = sess.execute(
            update(refreshes_table)
            .where(refreshes_table.c.id == METRICS_REFRESH_ID, refreshes_table.c.locked_by == worker_id)
            .values(locked_at=func.unix_timestamp())
        )
        return result.rowcount > 0

    def _release_metrics_refresh(
        self,
        refreshes_table: Table,
        worker_id: Optional[str],
        error: Optional[str] = None,
        fingerprint: Optional[List[Any]] = None,
        stopped: bool = False,
        claimed_fingerprint: Optional[List[Any]] = None,
    ) -> None:
        """Release the row of the metrics refreshes table: completed, with the fingerprint, without an error, failed
        with one, and as the last completed refresh left it when the calculation stopped.

        Args:
            refreshes_table (Table): The metrics refreshes table.
            worker_id (Optional[str]): The id of the calculation that claimed the row. None writes the row only while
                no process holds it, and creates it before any refresh.
            error (Optional[str]): The error the calculation failed with. None when it completed.
            fingerprint (Optional[List[Any]]): The fingerprint of yesterday and today, stored once it completed.
            stopped (bool): Whether the calculation stopped before it finished.
            claimed_fingerprint (Optional[List[Any]]): The fingerprint of the claimed row. A rebuild that marked
                another one since keeps its mark.
        """
        values: Dict[str, Any] = {"locked_by": None, "locked_at": None}
        if stopped:
            # The days it did not reach stay open for the next calculation; a first one that stopped has none to show
            values.update(
                status=case((refreshes_table.c.finished_at.is_not(None), "completed"), else_="failed"),
                error=case((refreshes_table.c.finished_at.is_not(None), None), else_=METRICS_STOPPED_ERROR),
            )
        elif error is None:
            values.update(status="completed", error=None, finished_at=func.unix_timestamp())
        else:
            values.update(status="failed", error=error)
        try:
            with self.Session() as sess, sess.begin():
                if not stopped and error is None:
                    # A rebuild that marked the fingerprint after the claim keeps its mark, so the next calculation
                    # rebuilds yesterday and today. Compared here: MySQL never finds a JSON column equal to a string, and
                    # MariaDB compares it as text, so the same fingerprint written with other spacing differs
                    # No fingerprint is stored as NULL, which a claim of NULL compares equal to
                    stored_fingerprint = sess.execute(
                        select(refreshes_table.c.fingerprint)
                        .where(refreshes_table.c.id == METRICS_REFRESH_ID)
                        .with_for_update()
                    ).scalar()
                    if stored_fingerprint == claimed_fingerprint:
                        values["fingerprint"] = null() if fingerprint is None else fingerprint
                if worker_id is None:
                    # Before any refresh there is no row to update. Each column keeps its value while a process holds
                    # the row: MySQL has no condition on the update of a duplicate key
                    sess.execute(
                        mysql.insert(refreshes_table)
                        .values(id=METRICS_REFRESH_ID, started_at=func.unix_timestamp(), status="failed", error=error)
                        .on_duplicate_key_update(
                            [
                                (
                                    name,
                                    case(
                                        (refreshes_table.c.locked_by.is_(None), value),
                                        else_=refreshes_table.c[name],
                                    ),
                                )
                                for name, value in values.items()
                            ]
                        )
                    )
                else:
                    sess.execute(
                        update(refreshes_table)
                        .where(refreshes_table.c.id == METRICS_REFRESH_ID, refreshes_table.c.locked_by == worker_id)
                        .values(**values)
                    )
        except Exception as e:
            log_debug(f"Error releasing metrics refresh: {e}")

    def _get_metrics_fingerprint(
        self, sess: Any, sessions_table: Table, runs_table: Optional[Table], yesterday: date
    ) -> Optional[List[Any]]:
        """Get the count and update times of the sessions and runs of yesterday and today. None while one of them was
        updated in the current second, which a second update in that same second would leave unchanged."""
        start_timestamp = int(datetime.combine(yesterday, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())
        current_time = int(time.time())
        fingerprint: List[Any] = [yesterday.isoformat()]
        for source_table in [sessions_table, runs_table]:
            if source_table is None:
                continue
            count, total_updated_at, latest_updated_at = sess.execute(
                select(func.count(), func.sum(source_table.c.updated_at), func.max(source_table.c.updated_at)).where(
                    source_table.c.created_at >= start_timestamp
                )
            ).one()
            if latest_updated_at is not None and latest_updated_at >= current_time:
                return None
            fingerprint.extend([count, int(total_updated_at or 0)])
        return fingerprint

    def _get_metrics_dates_to_calculate(
        self,
        aggregate_metrics_table: Table,
        sessions_table: Table,
        runs_table: Optional[Table],
        refresh_row: Dict[str, Any],
        rebuild_from: Optional[date] = None,
    ) -> Tuple[List[date], Optional[List[Any]]]:
        """Get the days whose metrics a calculation rebuilds, and the fingerprint of yesterday and today.

        Args:
            aggregate_metrics_table (Table): The aggregate metrics table.
            sessions_table (Table): The sessions table.
            runs_table (Optional[Table]): The runs table.
            refresh_row (Dict[str, Any]): The row of the metrics refreshes table, from _claim_metrics_refresh.
            rebuild_from (Optional[date]): The first day of a rebuild.

        Returns:
            Tuple[List[date], Optional[List[Any]]]: The days, oldest first, and the fingerprint to keep on the row of
                the metrics refreshes table.
        """
        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)
        dates_to_process: Set[date] = set()
        with self.Session() as sess:
            fingerprint = self._get_metrics_fingerprint(sess, sessions_table, runs_table, yesterday)
            first_calculation = refresh_row["finished_at"] is None
            # Yesterday and today, when their sessions or runs changed since the last calculation
            if first_calculation or fingerprint is None or fingerprint != refresh_row["fingerprint"]:
                dates_to_process.update([yesterday, today])

            # Every earlier day still open: not yet completed, or reopened by a write since
            dates_to_process.update(
                sess.execute(
                    select(aggregate_metrics_table.c.date).where(
                        aggregate_metrics_table.c.aggregation_period == "daily",
                        aggregate_metrics_table.c.user_id == "",
                        aggregate_metrics_table.c.completed.is_(False),
                        aggregate_metrics_table.c.date < yesterday,
                    )
                )
                .scalars()
                .all()
            )
            # Every earlier day from the day before the last calculation finished, whose writes reopened nothing while
            # it was yesterday or today
            if not first_calculation:
                dates_to_process.update(metrics_days_since_last_calculation(refresh_row["finished_at"], yesterday))

            # Until a first calculation has finished, every day with a session or a run not yet completed; with
            # rebuild_from, every day with one from that date on. Only days with data, so one session dated long ago
            # never builds every empty day since
            if first_calculation or rebuild_from is not None:
                day_stmts = [
                    select(func.floor(source_table.c.created_at / 86400).label("day")).distinct()
                    for source_table in [sessions_table, runs_table]
                    if source_table is not None
                ]
                completed_days: Set[date] = set()
                if first_calculation:
                    completed_days = set(
                        sess.execute(
                            select(aggregate_metrics_table.c.date).where(
                                aggregate_metrics_table.c.aggregation_period == "daily",
                                aggregate_metrics_table.c.user_id == "",
                                aggregate_metrics_table.c.completed.is_(True),
                            )
                        )
                        .scalars()
                        .all()
                    )
                for (day,) in sess.execute(union(*day_stmts)).fetchall():
                    data_date = date(1970, 1, 1) + timedelta(days=int(day))
                    # A rebuild takes every day with data from its first day, completed or not
                    rebuilt = rebuild_from is not None and data_date >= rebuild_from
                    if data_date <= today and (rebuilt or (first_calculation and data_date not in completed_days)):
                        dates_to_process.add(data_date)

        return sorted(dates_to_process), fingerprint

    def _get_open_metrics_months(self, aggregate_metrics_table: Table) -> List[date]:
        """Get the first day of every month before the current one whose month row is still open: not completed yet,
        or reopened by a day a calculation rebuilt before it stopped."""
        current_month = datetime.now(timezone.utc).date().replace(day=1)
        with self.Session() as sess:
            return list(
                sess.execute(
                    select(aggregate_metrics_table.c.date).where(
                        aggregate_metrics_table.c.aggregation_period == "monthly",
                        aggregate_metrics_table.c.user_id == "",
                        aggregate_metrics_table.c.completed.is_(False),
                        aggregate_metrics_table.c.date < current_month,
                    )
                )
                .scalars()
                .all()
            )

    def _get_metrics_parent_runs(self, sess: Any, runs_table: Table, parent_run_ids: List[str]) -> List[Dict[str, Any]]:
        """Get the stored runs that started the given runs, and the runs that started those, up to the whole run."""
        parent_runs: List[Dict[str, Any]] = []
        seen_run_ids: Set[str] = set()
        while parent_run_ids:
            seen_run_ids.update(parent_run_ids)
            for start in range(0, len(parent_run_ids), METRICS_IN_LIST_LIMIT):
                parents_stmt = select(
                    runs_table.c.run_id,
                    runs_table.c.run_type,
                    runs_table.c.agent_id,
                    runs_table.c.team_id,
                    runs_table.c.workflow_id,
                    runs_table.c.parent_run_id,
                ).where(runs_table.c.run_id.in_(parent_run_ids[start : start + METRICS_IN_LIST_LIMIT]))
                parent_runs.extend(dict(record._mapping) for record in sess.execute(parents_stmt).fetchall())
            parent_run_ids = sorted(
                {run["parent_run_id"] for run in parent_runs if run.get("parent_run_id")} - seen_run_ids
            )
        return parent_runs

    def _write_aggregate_metrics_rows(
        self,
        sess: Any,
        aggregate_metrics_table: Table,
        aggregate_metrics_rows: List[Dict[str, Any]],
        rows_changed: bool,
        read_version: Optional[int],
    ) -> None:
        """Write a period's rows of the aggregate metrics table, from build_aggregate_metrics_rows, in its transaction:
        the user rows, then the everyone row, which is completed only while it still has the version read before the
        period's rows."""
        period, period_date = aggregate_metrics_rows[0]["aggregation_period"], aggregate_metrics_rows[0]["date"]
        stored_rows = (
            sess.execute(
                select(aggregate_metrics_table).where(
                    aggregate_metrics_table.c.aggregation_period == period,
                    aggregate_metrics_table.c.date == period_date,
                )
            )
            .mappings()
            .all()
        )
        everyone_row, changed_rows, stale_user_ids = aggregate_metrics_rows_to_write(
            aggregate_metrics_rows, [dict(row) for row in stored_rows], rows_changed
        )
        for start in range(0, len(stale_user_ids), METRICS_IN_LIST_LIMIT):
            sess.execute(
                aggregate_metrics_table.delete().where(
                    aggregate_metrics_table.c.aggregation_period == period,
                    aggregate_metrics_table.c.date == period_date,
                    aggregate_metrics_table.c.user_id.in_(stale_user_ids[start : start + METRICS_IN_LIST_LIMIT]),
                )
            )
        bulk_upsert_aggregate_metrics_rows(
            session=sess, table=aggregate_metrics_table, aggregate_metrics_rows=changed_rows
        )
        if everyone_row is not None:
            upsert_aggregate_metrics_row(
                session=sess,
                table=aggregate_metrics_table,
                aggregate_metrics_row=everyone_row,
                read_version=read_version,
            )

    def _calculate_date_metrics(
        self,
        table: Table,
        aggregate_metrics_table: Table,
        sessions_table: Table,
        runs_table: Optional[Table],
        date_to_process: date,
        legacy_run_rows: List[Any],
        legacy_run_rows_by_id: Dict[str, Any],
        refreshes_table: Table,
        worker_id: str,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """Rebuild one day's component and aggregate metrics rows in one transaction. False when nothing was written."""
        start_timestamp = int(
            datetime.combine(date_to_process, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp()
        )
        end_timestamp = int(
            datetime.combine(date_to_process + timedelta(days=1), datetime.min.time())
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
        # Each day is its own transaction, so a day that fails never holds back the rows of the days before it
        with self.Session() as sess, sess.begin():
            # Read committed on MariaDB, as on PostgreSQL: the version compare keeps a day a write reopened meanwhile
            # open, where MariaDB would fail the day's write to a row changed since the transaction's first read.
            # MySQL refuses a write read committed when it logs statements
            if self.db_engine.dialect.is_mariadb:  # type: ignore[attr-defined]
                sess.connection(execution_options={"isolation_level": "READ COMMITTED"})
                # MariaDB cuts a JSON_ARRAYAGG at group_concat_max_len, 1 MB by default, so a run's messages and
                # tool calls are aggregated up to the largest packet the server accepts. Not set back: a higher cap
                # only stops a later aggregate from being cut
                sess.execute(text("SET SESSION group_concat_max_len = @@max_allowed_packet"))
            # Read before the day's runs, so a run written while they are read moves it
            read_version = sess.execute(
                select(aggregate_metrics_table.c.version).where(
                    aggregate_metrics_table.c.aggregation_period == "daily",
                    aggregate_metrics_table.c.date == date_to_process,
                    aggregate_metrics_table.c.user_id == "",
                )
            ).scalar()

            sessions_stmt = select(
                sessions_table.c.session_id,
                sessions_table.c.session_type,
                sessions_table.c.user_id,
                sessions_table.c.agent_id,
                sessions_table.c.team_id,
                sessions_table.c.workflow_id,
                sessions_table.c.metadata,
                func.json_extract(sessions_table.c.session_data, "$.compaction_metrics", type_=JSON).label(
                    "compaction_metrics"
                ),
            ).where(sessions_table.c.created_at >= start_timestamp, sessions_table.c.created_at < end_timestamp)
            result = sess.execute(sessions_stmt).fetchall()
            sessions = [dict(record._mapping) for record in result]

            runs: List[Dict[str, Any]] = []
            stored_run_ids: Set[str] = set()
            if runs_table is not None:
                run_rows = sess.execute(
                    build_component_metrics_runs_query(runs_table, start_timestamp, end_timestamp)
                ).fetchall()
                for start in range(0, len(run_rows), METRICS_BATCH_SIZE):
                    # Checked between batches too, so a stop never waits for the whole of a large day
                    if should_stop is not None and should_stop():
                        return False
                    runs.extend(
                        build_component_metrics_run(record) for record in run_rows[start : start + METRICS_BATCH_SIZE]
                    )
            # A legacy run migrated to the runs table since the legacy runs were read is among the day's runs, and
            # is counted from there
            day_run_ids = {run["run_id"] for run in runs}
            # Read whole, as stored
            runs.extend(dict(record._mapping) for record in legacy_run_rows if record.run_id not in day_run_ids)
            nested_run_ids = metrics_nested_run_ids(runs)

            # A run started by a run of another day, such as a member run after midnight, names that run's
            # agent, team or workflow as its parent, read from the legacy runs of the rebuild or the runs table
            day_run_ids = {run["run_id"] for run in runs if run.get("run_id")}
            parent_run_ids = sorted({run["parent_run_id"] for run in runs if run.get("parent_run_id")} - day_run_ids)
            parent_runs = [
                dict(legacy_run_rows_by_id[run_id]._mapping)
                for run_id in parent_run_ids
                if run_id in legacy_run_rows_by_id
            ]
            parent_run_ids = [run_id for run_id in parent_run_ids if run_id not in legacy_run_rows_by_id]
            # A nested run also stored as a legacy run of its own is counted from that run, whatever day it is on
            stored_run_ids.update(run_id for run_id in nested_run_ids if run_id in legacy_run_rows_by_id)

            if runs_table is not None:
                # A nested run also stored as a run of its own is counted from that row, whatever day it is on
                run_ids = sorted(nested_run_ids)
                for start in range(0, len(run_ids), METRICS_IN_LIST_LIMIT):
                    stored_stmt = select(runs_table.c.run_id).where(
                        runs_table.c.run_id.in_(run_ids[start : start + METRICS_IN_LIST_LIMIT])
                    )
                    stored_run_ids.update(record.run_id for record in sess.execute(stored_stmt).fetchall())

                # A remote member's run after midnight is named by its team's run of the day before
                team_session_ids = sorted(metrics_remote_member_team_session_ids(runs))
                for start in range(0, len(team_session_ids), METRICS_IN_LIST_LIMIT):
                    team_runs_stmt = build_component_metrics_runs_query(
                        runs_table, start_timestamp - 86400, start_timestamp
                    ).where(runs_table.c.session_id.in_(team_session_ids[start : start + METRICS_IN_LIST_LIMIT]))
                    team_runs = [
                        build_component_metrics_run(record) for record in sess.execute(team_runs_stmt).fetchall()
                    ]
                    parent_runs.extend(team_runs)
                    parent_run_ids.extend(run["parent_run_id"] for run in team_runs if run.get("parent_run_id"))

                parent_runs.extend(self._get_metrics_parent_runs(sess, runs_table, parent_run_ids))

            records = calculate_date_component_metrics(date_to_process, sessions, runs, stored_run_ids, parent_runs)
            result = sess.execute(
                select(table).where(table.c.aggregation_period == "daily", table.c.date == date_to_process)
            ).fetchall()
            stored_rows = [dict(record._mapping) for record in result]

            # Checked in the transaction of the rows, so a process whose lock went stale never overwrites the rows of
            # the process that took the refresh over
            if not self._heartbeat_metrics_refresh(sess, refreshes_table, worker_id):
                return False
            changed_rows, stale_keys = component_metrics_rows_to_write(records, stored_rows)
            for start in range(0, len(stale_keys), METRICS_STALE_KEYS_LIMIT):
                sess.execute(
                    table.delete().where(
                        table.c.aggregation_period == "daily",
                        table.c.date == date_to_process,
                        tuple_(
                            table.c.user_id,
                            table.c.component_type,
                            table.c.component_id,
                            table.c.parent_component_id,
                            table.c.root_component_id,
                        ).in_(stale_keys[start : start + METRICS_STALE_KEYS_LIMIT]),
                    )
                )
            bulk_upsert_component_metrics(session=sess, table=table, component_metrics_records=changed_rows)

            # Written last, in the day's transaction, so its version never moves without the rows it tells of
            self._write_aggregate_metrics_rows(
                sess,
                aggregate_metrics_table,
                build_aggregate_metrics_rows(records, "daily", date_to_process, metrics_day_completed(date_to_process)),
                rows_changed=bool(changed_rows or stale_keys),
                read_version=read_version,
            )
            if changed_rows or stale_keys:
                # Reopened with the day, so a calculation that stops before its months leaves the month for the next
                reopen_metrics_month(
                    session=sess, table=aggregate_metrics_table, month_start=date_to_process.replace(day=1)
                )
            return True

    def _calculate_month_metrics(
        self, table: Table, aggregate_metrics_table: Table, month_start: date, refreshes_table: Table, worker_id: str
    ) -> bool:
        """Rebuild the month rows of the aggregate metrics table from the component metrics rows of the month's days, in
        one transaction. False when another process took the refresh over, and nothing was written."""
        with self.Session() as sess, sess.begin():
            # Read committed on MariaDB, as the days are
            if self.db_engine.dialect.is_mariadb:  # type: ignore[attr-defined]
                sess.connection(execution_options={"isolation_level": "READ COMMITTED"})
            read_version = sess.execute(
                select(aggregate_metrics_table.c.version).where(
                    aggregate_metrics_table.c.aggregation_period == "monthly",
                    aggregate_metrics_table.c.date == month_start,
                    aggregate_metrics_table.c.user_id == "",
                )
            ).scalar()
            # Server-side cursor, so a month of many rows is added up a batch at a time instead of held whole
            result = sess.execute(
                select(table).where(
                    table.c.aggregation_period == "daily",
                    table.c.date >= month_start,
                    table.c.date <= metrics_month_end(month_start),
                ),
                execution_options={"stream_results": True},
            )
            per_owner: Dict[Tuple[str, str, str, str, str], Dict[str, Any]] = {}
            while True:
                batch = result.fetchmany(METRICS_BATCH_SIZE)
                if not batch:
                    break
                add_metrics_month_totals(per_owner, [dict(record._mapping) for record in batch])

            # Checked in the transaction of the rows, so a process whose lock went stale never overwrites the rows of
            # the process that took the refresh over
            if not self._heartbeat_metrics_refresh(sess, refreshes_table, worker_id):
                return False
            # Added up per owner and component over the month, so a user of several days is one user of the month
            self._write_aggregate_metrics_rows(
                sess,
                aggregate_metrics_table,
                build_aggregate_metrics_month_rows(month_start, per_owner),
                rows_changed=False,
                read_version=read_version,
            )
            return True

    def calculate_metrics(self, rebuild_from: Optional[date] = None) -> Optional[list[dict]]:
        """Calculate metrics for every day that changed since the last calculation.

        One process calculates at a time, whichever process or replica it runs in: the others return at once,
        having read nothing.

        Args:
            rebuild_from (Optional[date]): Also rebuild every day from this date to today, as after a release that
                changed how metrics are counted.

        Returns:
            Optional[list[dict]]: The metrics of the days calculated, or of today when nothing changed, as get_metrics
                returns them. None when another process is calculating them.

        Raises:
            Exception: If an error occurs during metrics calculation.
        """
        try:
            calculated_dates = self.calculate_metrics_dates(rebuild_from=rebuild_from)
            if calculated_dates is None:
                return None
            if not calculated_dates:
                # A refresh that changed no day answers with today's metrics
                calculated_dates = [datetime.now(timezone.utc).date()]
            metrics, _ = self._get_metrics_rows(calculated_dates[0], calculated_dates[-1], None)
            return [metric for metric in metrics if metric["date"] in calculated_dates]

        except Exception as e:
            log_error(f"Exception refreshing metrics: {str(e)}")
            raise e

    def calculate_metrics_dates(
        self, should_stop: Optional[Callable[[], bool]] = None, rebuild_from: Optional[date] = None
    ) -> Optional[List[date]]:
        """Calculate metrics for every day that changed since the last calculation, as calculate_metrics does,
        without reading back the metrics of those days.

        Args:
            should_stop (Optional[Callable[[], bool]]): Checked before each day and month, and between a day's
                batches. Once it returns True, the calculation releases the refresh and stops; the next one continues
                from the first day still open.
            rebuild_from (Optional[date]): Also rebuild every day from this date to today.

        Returns:
            Optional[List[date]]: The days calculated, oldest first. None when another process is calculating them.

        Raises:
            Exception: If an error occurs during metrics calculation.
        """
        table = self._get_metrics_table("component_metrics", self.component_metrics_table_name)
        aggregate_metrics_table = self._get_metrics_table("aggregate_metrics", self.aggregate_metrics_table_name)
        refreshes_table = self._get_metrics_table("metrics_refreshes", self.metrics_refreshes_table_name)
        sessions_table = self._get_table(table_type="sessions")
        if table is None or aggregate_metrics_table is None or refreshes_table is None or sessions_table is None:
            log_info("No session data found. Won't calculate metrics.")
            return []
        runs_table = self._get_table(table_type="runs")

        if rebuild_from is not None:
            # Reopened as a write reopens a day, before the claim, so a calculation another process is running
            # leaves them to the next one
            try:
                # A transaction of its own, without locking the refresh row, so it never waits on a day's calculation
                with self.Session() as sess, sess.begin():
                    # Read committed on MariaDB, as the days are
                    if self.db_engine.dialect.is_mariadb:  # type: ignore[attr-defined]
                        sess.connection(execution_options={"isolation_level": "READ COMMITTED"})
                    reopen_metrics_days_from(session=sess, table=aggregate_metrics_table, starting_date=rebuild_from)
                # Yesterday and today are picked by the fingerprint, so it is marked for the next one too
                if not self._mark_metrics_refresh_rebuild(refreshes_table):
                    return None
            except Exception as e:
                # Failed before the claim, so the refresh status shows it
                self._release_metrics_refresh(
                    refreshes_table,
                    None,
                    error=database_error_message(e),
                )
                raise

        worker_id = str(uuid4())
        # Claimed before anything is read, so a process that finds another calculating reads nothing
        refresh_row = self._claim_metrics_refresh(refreshes_table, worker_id)
        if refresh_row is None:
            return None

        try:
            dates_to_process, fingerprint = self._get_metrics_dates_to_calculate(
                aggregate_metrics_table, sessions_table, runs_table, refresh_row, rebuild_from
            )

            legacy_run_rows_by_day: Dict[date, List[Any]] = {}
            legacy_run_rows_by_id: Dict[str, Any] = {}
            # Read once for every day until the v3.0.0 migration is stamped: no index finds one day's legacy runs
            if dates_to_process and packaging_version.parse(
                self.get_latest_schema_version(self.session_table_name)
            ) < packaging_version.parse("3.0.0"):
                start_timestamp = int(
                    datetime.combine(dates_to_process[0], datetime.min.time()).replace(tzinfo=timezone.utc).timestamp()
                )
                end_timestamp = int(
                    datetime.combine(dates_to_process[-1] + timedelta(days=1), datetime.min.time())
                    .replace(tzinfo=timezone.utc)
                    .timestamp()
                )
                legacy_runs_query = build_component_metrics_legacy_runs_query(
                    sessions_table, runs_table, start_timestamp, end_timestamp
                )
                if legacy_runs_query is not None:
                    with self.Session() as sess, sess.begin():
                        legacy_runs_result = sess.execute(legacy_runs_query, execution_options={"stream_results": True})
                        while True:
                            batch = legacy_runs_result.fetchmany(METRICS_BATCH_SIZE)
                            if not batch:
                                break
                            for record in batch:
                                legacy_run_day = datetime.fromtimestamp(record.created_at, tz=timezone.utc).date()
                                legacy_run_rows_by_day.setdefault(legacy_run_day, []).append(record)
                                legacy_run_rows_by_id[record.run_id] = record
                        if not self._heartbeat_metrics_refresh(sess, refreshes_table, worker_id):
                            return None
                    # A legacy run is dated on its own day, which may hold no session or run of the tables
                    today = datetime.now(timezone.utc).date()
                    dates_to_process = sorted(
                        set(dates_to_process)
                        | {
                            day
                            for day in legacy_run_rows_by_day
                            if day <= today
                            and (
                                refresh_row["finished_at"] is None or (rebuild_from is not None and day >= rebuild_from)
                            )
                        }
                    )

            calculated_dates: List[date] = []
            for date_to_process in dates_to_process:
                if should_stop is not None and should_stop():
                    self._release_metrics_refresh(refreshes_table, worker_id, stopped=True)
                    return None
                if not self._calculate_date_metrics(
                    table,
                    aggregate_metrics_table,
                    sessions_table,
                    runs_table,
                    date_to_process,
                    legacy_run_rows_by_day.get(date_to_process, []),
                    legacy_run_rows_by_id,
                    refreshes_table,
                    worker_id,
                    should_stop,
                ):
                    if should_stop is not None and should_stop():
                        self._release_metrics_refresh(refreshes_table, worker_id, stopped=True)
                    return None
                calculated_dates.append(date_to_process)

            # A month row is read only once completed, so a month is built only once its last day can be completed
            month_starts = sorted(
                month_start
                for month_start in set(get_months_to_calculate_metrics_for(calculated_dates))
                | set(self._get_open_metrics_months(aggregate_metrics_table))
                if metrics_day_completed(metrics_month_end(month_start))
            )
            for month_start in month_starts:
                if should_stop is not None and should_stop():
                    self._release_metrics_refresh(refreshes_table, worker_id, stopped=True)
                    return None
                if not self._calculate_month_metrics(
                    table, aggregate_metrics_table, month_start, refreshes_table, worker_id
                ):
                    return None

        except Exception as e:
            self._release_metrics_refresh(refreshes_table, worker_id, error=database_error_message(e))
            raise

        self._release_metrics_refresh(
            refreshes_table, worker_id, fingerprint=fingerprint, claimed_fingerprint=refresh_row["fingerprint"]
        )

        if not calculated_dates:
            log_info("Metrics already calculated for all relevant dates.")
            return []

        log_debug("Updated metrics calculations")
        return calculated_dates

    def stop_metrics_refresh_on_read(self) -> None:
        """Stop calculating metrics before a read, for a database whose metrics are calculated in the background."""
        self._metrics_refreshed_at = float("inf")

    def _get_metrics_by_owner(
        self, starting_date: Optional[date], ending_date: Optional[date], user_id: Optional[str]
    ) -> Tuple[List[dict], Optional[int]]:
        """Get the metrics of each user and day from the component metrics, in the shape of the metrics table."""
        table = self._get_table(table_type="component_metrics")
        if table is None:
            return [], None

        queries = build_metrics_by_owner_queries(table, starting_date, ending_date, user_id)
        with self.Session() as sess, sess.begin():
            rows_by_query = {name: sess.execute(query).fetchall() for name, query in queries.items()}
            if not rows_by_query["totals"]:
                return [], None

            # Get the latest updated_at, scoped to the same user filter
            latest_stmt = select(func.max(table.c.updated_at))
            if user_id is not None:
                latest_stmt = latest_stmt.where(table.c.user_id == user_id)
            latest_updated_at = sess.execute(latest_stmt).scalar()

        return build_metrics_by_owner(rows_by_query["totals"], rows_by_query["model_metrics"]), latest_updated_at

    def _get_aggregate_metrics_rows(
        self, starting_date: Optional[date], ending_date: Optional[date], user_id: Optional[str]
    ) -> Tuple[List[dict], Optional[int]]:
        """Get the day rows of the aggregate metrics table in the shape of the metrics table: the everyone rows for
        ``""``, one user's rows for a name, and every user's rows for ``None``."""
        aggregate_metrics_table = self._get_table(table_type="aggregate_metrics")
        if aggregate_metrics_table is None:
            return [], None

        filters = [aggregate_metrics_table.c.aggregation_period == "daily"]
        if starting_date:
            filters.append(aggregate_metrics_table.c.date >= starting_date)
        if ending_date:
            filters.append(aggregate_metrics_table.c.date <= ending_date)
        filters.append(
            aggregate_metrics_table.c.user_id != "" if user_id is None else aggregate_metrics_table.c.user_id == user_id
        )
        # A day without sessions or runs keeps an everyone row of zeros, where agno_metrics kept no row. A day whose
        # only run is a regenerated one has its tokens but no count
        filters.append(
            or_(
                *[
                    aggregate_metrics_table.c[column] > 0
                    for column in AGGREGATE_METRICS_COUNT_COLUMNS
                    if column != "users_count"
                ],
                aggregate_metrics_table.c.total_tokens > 0,
            )
        )
        # Only what build_metrics_from_aggregate_metrics reads, so the maps of timings are never decoded
        columns = [
            aggregate_metrics_table.c[column]
            for column in [
                "date",
                "user_id",
                *AGGREGATE_METRICS_COUNT_COLUMNS,
                *[field for field in METRICS_TOKEN_FIELDS if field in aggregate_metrics_table.c],
                "token_details",
                "model_metrics",
                "created_at",
                "updated_at",
            ]
        ]
        with self.Session() as sess:
            rows = (
                sess.execute(
                    select(*columns)
                    .where(*filters)
                    .order_by(aggregate_metrics_table.c.date, aggregate_metrics_table.c.user_id)
                )
                .mappings()
                .all()
            )
            if not rows:
                return [], None

            # Get the latest updated_at, scoped to the same user filter
            latest_updated_at = sess.execute(
                select(func.max(aggregate_metrics_table.c.updated_at)).where(
                    aggregate_metrics_table.c.aggregation_period == "daily",
                    aggregate_metrics_table.c.user_id != ""
                    if user_id is None
                    else aggregate_metrics_table.c.user_id == user_id,
                )
            ).scalar()
        return build_metrics_from_aggregate_metrics(rows), latest_updated_at

    def _get_metrics_rows(
        self, starting_date: Optional[date], ending_date: Optional[date], user_id: Optional[str]
    ) -> Tuple[List[dict], Optional[int]]:
        """Get the metrics of each user and day, as get_metrics returns them once the first calculate_metrics has
        finished: a user's from that user's rows, the runs with no user from their component metrics rows."""
        if user_id == "":
            return self._get_metrics_by_owner(starting_date, ending_date, user_id)
        metrics, latest_updated_at = self._get_aggregate_metrics_rows(starting_date, ending_date, user_id)
        if user_id is not None:
            return metrics, latest_updated_at

        unowned_metrics, unowned_updated_at = self._get_metrics_by_owner(starting_date, ending_date, "")
        latest_updated_at = max(
            (updated_at for updated_at in [latest_updated_at, unowned_updated_at] if updated_at is not None),
            default=None,
        )
        return sorted(metrics + unowned_metrics, key=lambda x: (x["date"], x["user_id"] or "")), latest_updated_at

    def _metrics_calculated(self, refreshes_table: Optional[Table]) -> bool:
        """Whether the first calculate_metrics has finished, so reads take the metrics tables over agno_metrics."""
        refresh_row = self._get_metrics_refresh_row(refreshes_table)[0] if refreshes_table is not None else None
        return refresh_row is not None and refresh_row["finished_at"] is not None

    def _refresh_metrics_before_read(self) -> None:
        """Calculate metrics before a read, at most once per minute per process, once a first calculate_metrics has
        finished and unless metrics calculation is turned off. Another process calculating them holds the metrics
        refresh, so the read goes on at once."""
        if time.time() - self._metrics_refreshed_at < 60:
            return
        # Stamp first so failed runs are throttled too instead of retried on every read
        self._metrics_refreshed_at = time.time()
        try:
            # A first build reads every run, so a read never waits for one: until it has finished, reads serve the
            # deprecated metrics table
            if not metrics_calculation_enabled() or not self._metrics_calculated(
                self._get_table(table_type="metrics_refreshes")
            ):
                return
            self.calculate_metrics_dates()
        except Exception as e:
            log_warning(f"Could not refresh metrics before reading them: {str(e)}")

    def get_metrics(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[List[dict], Optional[int]]:
        """Get all metrics matching the given date range.

        Metrics are read from the aggregate metrics and component metrics once the first calculate_metrics has finished,
        and from the deprecated metrics table until then. They are refreshed first, at most once per minute per
        process, unless stop_metrics_refresh_on_read was called.

        Args:
            starting_date (Optional[date]): The starting date to filter metrics by.
            ending_date (Optional[date]): The ending date to filter metrics by.
            user_id (Optional[str]): If set, only return metrics owned by this user.

        Returns:
            Tuple[List[dict], Optional[int]]: A tuple containing the metrics and the timestamp of the latest update.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            self._refresh_metrics_before_read()
            if self._metrics_calculated(self._get_table(table_type="metrics_refreshes")):
                return self._get_metrics_rows(starting_date, ending_date, user_id)

            table = self._get_table(table_type="metrics")
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

                # Get the latest updated_at
                latest_stmt = select(func.max(table.c.updated_at))
                if user_id is not None:
                    latest_stmt = latest_stmt.where(table.c.user_id == user_id)
                latest_updated_at = sess.execute(latest_stmt).scalar()

            # Map the sentinel empty-string user_id back to None
            rows: List[dict] = []
            for row in result:
                row_dict = dict(row._mapping)
                if row_dict.get("user_id") == "":
                    row_dict["user_id"] = None
                rows.append(row_dict)
            return rows, latest_updated_at

        except Exception as e:
            log_error(f"Exception getting metrics: {str(e)}")
            raise e

    def get_metrics_by_date(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
    ) -> Tuple[List[dict], Optional[int]]:
        """Get the metrics of every user, one row per day, matching the given date range.

        Read from the everyone rows of the aggregate metrics once the first calculate_metrics has finished, and from the
        deprecated metrics table until then. They are refreshed first, as get_metrics does.

        Args:
            starting_date (Optional[date]): The starting date to filter metrics by.
            ending_date (Optional[date]): The ending date to filter metrics by.

        Returns:
            Tuple[List[dict], Optional[int]]: A tuple containing the metrics and the timestamp of the latest update.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            self._refresh_metrics_before_read()
            if self._metrics_calculated(self._get_table(table_type="metrics_refreshes")):
                return self._get_aggregate_metrics_rows(starting_date, ending_date, "")
            return super().get_metrics_by_date(starting_date, ending_date)

        except Exception as e:
            log_error(f"Exception getting metrics: {str(e)}")
            raise e

    def get_metrics_refresh_status(self) -> Optional[Dict[str, Any]]:
        """Get the status of the most recent calculate_metrics, from the metrics refreshes table.

        Returns:
            Optional[Dict[str, Any]]: The status ('running', 'completed' or 'failed'), when it started and finished,
                and its error. None before the first calculation.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            refreshes_table = self._get_table(table_type="metrics_refreshes")
            if refreshes_table is None:
                return None
            return metrics_refresh_status(*self._get_metrics_refresh_row(refreshes_table))

        except Exception as e:
            log_error(f"Exception getting metrics refresh status: {str(e)}")
            raise e

    def _get_component_metrics_totals_by_date(
        self,
        starting_date: date,
        ending_date: date,
        user_id: Optional[str],
        fields: List[str],
        use_month_rows: bool = False,
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        """Total the component metrics of the given date range, every day from one period.

        Args:
            starting_date (date): The first day to total.
            ending_date (date): The last day to total.
            user_id (Optional[str]): Total only this owner's rows. ``None`` totals every owner, ``""`` the runs with
                no user.
            fields (List[str]): The columns to total.
            use_month_rows (bool): Total a calendar month inside the date range from its month aggregate metrics row, as
                one date.

        Returns:
            Tuple[List[Dict[str, Any]], Optional[int]]: The totals of each date, and when they were last updated.
        """
        aggregate_metrics_table = self._get_table(table_type="aggregate_metrics")
        # Every owner is read from the everyone rows and a user from the user's rows; the runs with no user have no
        # aggregate metrics row of their own, so they are read from their component rows
        table = self._get_table(table_type="component_metrics") if user_id == "" else aggregate_metrics_table
        if aggregate_metrics_table is None or table is None:
            return [], None

        # The component metrics table keeps day rows only, so the runs with no user are read day by day
        full_months = metrics_full_months(starting_date, ending_date) if use_month_rows and user_id != "" else []
        month_starts: Sequence[date] = []
        rows_by_query = {}
        with self.Session() as sess, sess.begin():
            # One snapshot for every query of the read, so a rebuild committing between them is never half seen
            sess.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            if full_months:
                # Only a completed month's row stands for its days; an open one, reopened by a day rebuilt since
                # or not yet built, is read from its days
                month_starts = (
                    sess.execute(
                        select(aggregate_metrics_table.c.date).where(
                            aggregate_metrics_table.c.aggregation_period == "monthly",
                            aggregate_metrics_table.c.user_id == "",
                            aggregate_metrics_table.c.completed.is_(True),
                            # The full months follow each other, so a range finds them however long the window is
                            aggregate_metrics_table.c.date.between(full_months[0], full_months[-1]),
                        )
                    )
                    .scalars()
                    .all()
                )
            queries = build_component_metrics_totals_queries(
                table, starting_date, ending_date, user_id or "", fields, month_starts=month_starts
            )
            for name, query in queries.items():
                rows_by_query[name] = sess.execute(query).fetchall()
        return build_component_metrics_totals(fields, rows_by_query)

    def get_component_metrics(
        self,
        starting_date: date,
        ending_date: date,
        user_id: Optional[str] = None,
        fields: Optional[List[str]] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        """Get the component metrics totals of each day in the given date range.

        For every owner, each day is read from its everyone row; for one owner, from its rows. A read never calculates
        them: calculate_metrics does.

        Args:
            starting_date (date): The first day to total.
            ending_date (date): The last day to total.
            user_id (Optional[str]): Total only this owner's rows. ``None`` totals every owner, ``""`` the runs with
                no user.
            fields (Optional[List[str]]): The columns to total. ``None`` totals all.

        Returns:
            Tuple[List[Dict[str, Any]], Optional[int]]: The totals of each day, and when they were last updated.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            fields = resolve_metrics_fields(fields)
            metrics, latest_updated_at = self._get_component_metrics_totals_by_date(
                starting_date, ending_date, user_id, fields
            )
            return [list_metrics_totals_models(day_totals) for day_totals in metrics], latest_updated_at

        except Exception as e:
            log_error(f"Exception getting component metrics: {str(e)}")
            raise e

    def get_metrics_totals(
        self,
        starting_date: date,
        ending_date: date,
        user_id: Optional[str] = None,
        fields: Optional[List[str]] = None,
    ) -> Tuple[Dict[str, Any], Optional[int]]:
        """Get the component metrics totals of the whole given date range.

        A calendar month inside the date range that has month rows is read from them, and every other day as
        get_component_metrics reads it.

        Args:
            starting_date (date): The first day to total.
            ending_date (date): The last day to total.
            user_id (Optional[str]): Total only this owner's rows. ``None`` totals every owner, ``""`` the runs with
                no user.
            fields (Optional[List[str]]): The columns to total. ``None`` totals all.

        Returns:
            Tuple[Dict[str, Any], Optional[int]]: The totals of the date range, and when they were last updated.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            fields = resolve_metrics_fields(fields)
            totals, latest_updated_at = self._get_component_metrics_totals_by_date(
                starting_date, ending_date, user_id, fields, use_month_rows=True
            )
            return list_metrics_totals_models(merge_metrics_totals(totals, fields)), latest_updated_at

        except Exception as e:
            log_error(f"Exception getting metrics totals: {str(e)}")
            raise e

    def get_metrics_versions(self, starting_date: date, ending_date: date) -> Optional[Dict[str, int]]:
        """Get the version of every everyone row of a day or a month of the aggregate metrics in the given date range.

        Metrics are refreshed first, as get_metrics refreshes them.

        Args:
            starting_date (date): The first day of the date range.
            ending_date (date): The last day of the date range.

        Returns:
            Optional[Dict[str, int]]: The version of each everyone row, keyed by its aggregation period and date. The
                same again only while no calculation wrote a row of the date range. ``None`` until the first
                calculate_metrics has finished, or without an aggregate metrics table: a read would find no rows to
                total.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            self._refresh_metrics_before_read()
            table = self._get_table(table_type="aggregate_metrics")
            if table is None or not self._metrics_calculated(self._get_table(table_type="metrics_refreshes")):
                return None

            with self.Session() as sess, sess.begin():
                rows = sess.execute(
                    select(table.c.aggregation_period, table.c.date, table.c.version).where(
                        table.c.user_id == "",
                        table.c.date.between(starting_date, ending_date),
                    )
                ).fetchall()
            return metrics_versions(rows)

        except Exception as e:
            log_error(f"Exception getting metrics versions: {str(e)}")
            raise e

    # -- Knowledge methods --

    def delete_knowledge_content(self, id: str, user_id: Optional[str] = None):
        """Delete a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to delete.
            user_id (Optional[str]): If set, only delete the row if owned by this user.

        Raises:
            Exception: If an error occurs during deletion.
        """
        table = self._get_table(table_type="knowledge")
        if table is None:
            return None

        try:
            with self.Session() as sess, sess.begin():
                stmt = table.delete().where(table.c.id == id)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                sess.execute(stmt)

        except Exception as e:
            log_error(f"Exception deleting knowledge content: {str(e)}")

    def get_knowledge_content(self, id: str, user_id: Optional[str] = None) -> Optional[KnowledgeRow]:
        """Get a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to get.
            user_id (Optional[str]): If set, only return the row if owned by this user or shared (NULL owner).

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
            log_error(f"Exception getting knowledge content: {str(e)}")
            return None

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
            user_id (Optional[str]): If set, only return rows owned by this user or shared (NULL owner).

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

                # Apply owner scoping: this user's rows plus shared rows (NULL owner)
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
                if not result:
                    return [], 0

                return [KnowledgeRow.model_validate(record._mapping) for record in result], total_count

        except Exception as e:
            log_error(f"Exception getting knowledge contents: {str(e)}")
            return [], 0

    def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        """Upsert knowledge content in the database.

        Args:
            knowledge_row (KnowledgeRow): The knowledge row to upsert.

        Returns:
            Optional[KnowledgeRow]: The upserted knowledge row, or None if the operation fails.

        Raises:
            Exception: If an error occurs during upsert.
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

                # Get the actual table columns to avoid "unconsumed column names" error
                table_columns = set(table.columns.keys())

                # Only include fields that exist in the table and are not None
                insert_data = {}
                update_fields = {}

                # Map of KnowledgeRow fields to table columns
                field_mapping = {
                    "id": "id",
                    "name": "name",
                    "description": "description",
                    "metadata": "metadata",
                    "type": "type",
                    "size": "size",
                    "linked_to": "linked_to",
                    "access_count": "access_count",
                    "status": "status",
                    "status_message": "status_message",
                    "created_at": "created_at",
                    "updated_at": "updated_at",
                    "external_id": "external_id",
                    "user_id": "user_id",
                }

                # Build insert and update data only for fields that exist in the table
                for model_field, table_column in field_mapping.items():
                    if table_column in table_columns:
                        value = getattr(knowledge_row, model_field, None)
                        if value is not None:
                            insert_data[table_column] = value
                            # Don't include ID in update_fields since it's the primary key
                            if table_column != "id":
                                update_fields[table_column] = value

                # Ensure id is always included for the insert
                if "id" in table_columns and knowledge_row.id:
                    insert_data["id"] = knowledge_row.id

                # Handle case where update_fields is empty (all fields are None or don't exist in table)
                if not update_fields:
                    # If we have insert_data, just do an insert without conflict resolution
                    if insert_data:
                        stmt = mysql.insert(table).values(insert_data)
                        sess.execute(stmt)
                    else:
                        # If we have no data at all, this is an error
                        log_error("No valid fields found for knowledge row upsert")
                        return None
                else:
                    # Normal upsert with conflict resolution
                    stmt = mysql.insert(table).values(insert_data).on_duplicate_key_update(**update_fields)
                    sess.execute(stmt)

            return knowledge_row

        except Exception as e:
            log_error(f"Error upserting knowledge row: {str(e)}")
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
                stmt = mysql.insert(table).values(
                    {"created_at": current_time, "updated_at": current_time, **eval_run.model_dump()}
                )
                sess.execute(stmt)

            return eval_run

        except Exception as e:
            log_error(f"Error creating eval run: {str(e)}")
            return None

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
                    log_error(f"No eval run found with ID: {eval_run_id}")
                else:
                    log_debug(f"Deleted eval run with ID: {eval_run_id}")

        except Exception as e:
            log_error(f"Error deleting eval run {eval_run_id}: {str(e)}")

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
                    log_error(f"No eval runs found with IDs: {eval_run_ids}")
                else:
                    log_debug(f"Deleted {result.rowcount} eval runs")

        except Exception as e:
            log_error(f"Error deleting eval runs {eval_run_ids}: {str(e)}")

    def get_eval_run(
        self, eval_run_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Get an eval run from the database.

        Args:
            eval_run_id (str): The ID of the eval run to get.
            deserialize (Optional[bool]): Whether to deserialize the eval run. Defaults to True.
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

                eval_run_raw = result._mapping
                if not deserialize:
                    return eval_run_raw

                return EvalRunRecord.model_validate(eval_run_raw)

        except Exception as e:
            log_error(f"Exception getting eval run {eval_run_id}: {str(e)}")
            return None

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
            deserialize (Optional[bool]): Whether to deserialize the eval runs. Defaults to True.
            create_table_if_not_found (Optional[bool]): Whether to create the table if it doesn't exist.

        Returns:
            Union[List[EvalRunRecord], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of EvalRunRecord objects
                - When deserialize=False: List of dictionaries

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
                if agent_id is not None:
                    stmt = stmt.where(table.c.agent_id == agent_id)
                if team_id is not None:
                    stmt = stmt.where(table.c.team_id == team_id)
                if workflow_id is not None:
                    stmt = stmt.where(table.c.workflow_id == workflow_id)
                if model_id is not None:
                    stmt = stmt.where(table.c.model_id == model_id)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
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

                # Sorting
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

                eval_runs_raw = [row._mapping for row in result]
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
            user_id (Optional[str]): If set, only rename the run if owned by this user.

        Returns:
            Optional[Dict[str, Any]]: The updated eval run, or None if the operation fails.

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
            if not eval_run_raw or not deserialize:
                return eval_run_raw

            return EvalRunRecord.model_validate(eval_run_raw)

        except Exception as e:
            log_error(f"Error upserting eval run name {eval_run_id}: {str(e)}")
            return None

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

    # --- Traces ---
    def _get_traces_base_query(self, table: Table, spans_table: Optional[Table] = None):
        """Build base query for traces with aggregated span counts.

        Args:
            table: The traces table.
            spans_table: The spans table (optional).

        Returns:
            SQLAlchemy select statement with total_spans and error_count calculated dynamically.
        """
        from sqlalchemy import case, literal

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

        is_root_name = or_(name_col.like("%.run%"), name_col.like("%.arun%"))

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

        Uses INSERT ... ON DUPLICATE KEY UPDATE (upsert) to handle concurrent inserts
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
                insert_stmt = mysql.insert(table).values(trace_dict)

                # Build component level expressions for comparing trace priority
                new_level = self._get_trace_component_level_expr(
                    insert_stmt.inserted.workflow_id,
                    insert_stmt.inserted.team_id,
                    insert_stmt.inserted.agent_id,
                    insert_stmt.inserted.name,
                )
                existing_level = self._get_trace_component_level_expr(
                    table.c.workflow_id,
                    table.c.team_id,
                    table.c.agent_id,
                    table.c.name,
                )

                # Build the ON DUPLICATE KEY UPDATE clause
                # Use LEAST for start_time, GREATEST for end_time to capture full trace duration
                # MySQL stores timestamps as ISO strings, so string comparison works for ISO format
                # Duration is calculated using TIMESTAMPDIFF in microseconds then converted to ms
                upsert_stmt = insert_stmt.on_duplicate_key_update(
                    end_time=func.greatest(table.c.end_time, insert_stmt.inserted.end_time),
                    start_time=func.least(table.c.start_time, insert_stmt.inserted.start_time),
                    # Calculate duration in milliseconds using TIMESTAMPDIFF
                    # TIMESTAMPDIFF(MICROSECOND, start, end) / 1000 gives milliseconds
                    duration_ms=func.timestampdiff(
                        text("MICROSECOND"),
                        func.least(table.c.start_time, insert_stmt.inserted.start_time),
                        func.greatest(table.c.end_time, insert_stmt.inserted.end_time),
                    )
                    / 1000,
                    status=insert_stmt.inserted.status,
                    # Update name only if new trace is from a higher-level component
                    # Priority: workflow (3) > team (2) > agent (1) > child spans (0)
                    name=case(
                        (new_level > existing_level, insert_stmt.inserted.name),
                        else_=table.c.name,
                    ),
                    # Preserve existing non-null context values: COALESCE returns
                    # the first non-null arg, so put the existing column first.
                    # Otherwise a later upsert from a child span (e.g. a post-hook
                    # agent's run with a different session_id) would overwrite
                    # the trace's already-correct context.
                    run_id=func.coalesce(table.c.run_id, insert_stmt.inserted.run_id),
                    session_id=func.coalesce(table.c.session_id, insert_stmt.inserted.session_id),
                    user_id=func.coalesce(table.c.user_id, insert_stmt.inserted.user_id),
                    agent_id=func.coalesce(table.c.agent_id, insert_stmt.inserted.agent_id),
                    team_id=func.coalesce(table.c.team_id, insert_stmt.inserted.team_id),
                    workflow_id=func.coalesce(table.c.workflow_id, insert_stmt.inserted.workflow_id),
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
        """Get a single trace by trace_id or other filters.

        Args:
            trace_id: The unique trace identifier.
            run_id: Filter by run ID (returns first match).

        Returns:
            Optional[Trace]: The trace if found, None otherwise.

        Note:
            If multiple filters are provided, trace_id takes precedence.
            For other filters, the most recent trace is returned.
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

        Returns:
            tuple[List[Trace], int]: Tuple of (list of matching traces, total count).
        """
        try:
            from agno.tracing.schemas import Trace

            log_debug(
                f"get_traces called with filters: run_id={run_id}, session_id={session_id}, user_id={user_id}, agent_id={agent_id}, page={page}, limit={limit}"
            )

            table = self._get_table(table_type="traces")
            if table is None:
                log_debug("Traces table not found")
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
        group_by: Literal["session", "agent", "team", "workflow", "endpoint"] = "session",
    ) -> tuple[List[Dict[str, Any]], int]:
        """Get trace statistics grouped by session.

        Args:
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            workflow_id: Filter by workflow ID.
            start_time: Filter sessions with traces created after this datetime.
            end_time: Filter sessions with traces created before this datetime.
            limit: Maximum number of sessions to return per page.
            page: Page number (1-indexed).
            group_by: Only the default "session" grouping is supported by this backend.

        Returns:
            tuple[List[Dict], int]: Tuple of (list of session stats dicts, total count).
                Each dict contains: session_id, user_id, agent_id, team_id, total_traces,
                workflow_id, first_trace_at, last_trace_at.
        """
        if group_by != "session":
            raise NotImplementedError(
                f"get_trace_stats with group_by={group_by!r} is not supported by {self.__class__.__name__}. "
                "Only the default 'session' grouping is available."
            )

        try:
            table = self._get_table(table_type="traces")
            if table is None:
                log_debug("Traces table not found")
                return [], 0

            with self.Session() as sess:
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

                # Get total count of sessions
                count_stmt = select(func.count()).select_from(base_stmt.alias())
                total_count = sess.execute(count_stmt).scalar() or 0

                # Apply pagination and ordering
                offset = (page - 1) * limit if page and limit else 0
                paginated_stmt = base_stmt.order_by(func.max(table.c.created_at).desc()).limit(limit).offset(offset)

                results = sess.execute(paginated_stmt).fetchall()

                # Convert to list of dicts with datetime objects
                stats_list = []
                for row in results:
                    # Convert ISO strings to datetime objects
                    first_trace_at_str = row.first_trace_at
                    last_trace_at_str = row.last_trace_at

                    # Parse ISO format strings to datetime objects
                    first_trace_at = datetime.fromisoformat(first_trace_at_str.replace("Z", "+00:00"))
                    last_trace_at = datetime.fromisoformat(last_trace_at_str.replace("Z", "+00:00"))

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

                return stats_list, total_count

        except Exception as e:
            log_error(f"Error getting trace stats: {str(e)}")
            return [], 0

    # --- Spans ---
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
                stmt = mysql.insert(table).values(span.to_dict())
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
                    stmt = mysql.insert(table).values(span.to_dict())
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
                stmt = select(table).where(table.c.span_id == span_id)
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
        limit: Optional[int] = 1000,
    ) -> List:
        """Get spans matching the provided filters.

        Args:
            trace_id: Filter by trace ID.
            parent_span_id: Filter by parent span ID.
            limit: Maximum number of spans to return.

        Returns:
            List[Span]: List of matching spans.
        """
        try:
            from agno.tracing.schemas import Span

            table = self._get_table(table_type="spans")
            if table is None:
                return []

            with self.Session() as sess:
                stmt = select(table)

                # Apply filters
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

    # -- Learning methods (stubs) --
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
        raise NotImplementedError("Learning methods not yet implemented for MySQLDb")

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
        raise NotImplementedError("Learning methods not yet implemented for MySQLDb")

    def delete_learning(self, id: str) -> bool:
        raise NotImplementedError("Learning methods not yet implemented for MySQLDb")

    def get_learnings(
        self,
        learning_type: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError("Learning methods not yet implemented for MySQLDb")
