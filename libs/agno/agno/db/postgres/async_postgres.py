import time
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Sequence, Tuple, Union, cast
from uuid import uuid4

if TYPE_CHECKING:
    from agno.run.status_persist import RunPersistOutcome
    from agno.tracing.schemas import Span, Trace

from agno.db.base import AsyncBaseDb, SessionType
from agno.db.migrations.manager import MigrationManager
from agno.db.postgres.schemas import get_table_schema_definition
from agno.db.postgres.utils import (
    abulk_upsert_metrics,
    acreate_schema,
    ais_table_available,
    ais_valid_table,
    apply_sorting,
    calculate_date_metrics,
    fetch_all_sessions_data,
    get_dates_to_calculate_metrics_for,
)
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.db.schemas.service_accounts import (
    resolve_service_account_sort_column,
    validate_service_account_update,
)
from agno.db.utils import (
    HISTORY_SKIP_STATUSES,
    SessionRunObjectCache,
    build_single_run_row,
    deserialize_run,
    deserialize_session,
    deserialize_sessions,
    filter_context_runs,
    json_serializer,
    learning_search_patterns,
    merge_runs_table_with_legacy_blob,
    metrics_starting_date_from_days,
    table_schema_mismatch_error,
    validate_pagination,
)
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.string import sanitize_postgres_string, sanitize_postgres_strings

try:
    from sqlalchemy import (
        BigInteger,
        ForeignKey,
        Index,
        String,
        Table,
        UniqueConstraint,
        and_,
        case,
        distinct,
        func,
        or_,
        update,
    )
    from sqlalchemy import cast as sa_cast
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.dialects.postgresql import TIMESTAMP
    from sqlalchemy.exc import ProgrammingError
    from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
    from sqlalchemy.schema import Column, MetaData
    from sqlalchemy.sql.expression import select, text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


def _db_epoch() -> Any:
    """Postgres transaction time as an integer epoch, for LEASE math.

    Lease decisions must be anchored to ONE clock. With app-side time a
    replica whose clock runs fast sees healthy leases as expired and sweeps
    live runs - and now that the sweep steals the lock, the victim's own
    completion is fenced out and its run is reported failed despite having
    finished. NOW() is transaction-start time, identical for every replica
    talking to the same database, so claim/heartbeat/sweep all agree.

    Not applied to enqueue's available_at (computed by the accepting replica
    before any transaction exists) or to queue_stats' age arithmetic; both
    only shift scheduling/reporting by the skew, never ownership.
    """
    return sa_cast(func.floor(func.extract("epoch", func.now())), BigInteger)


class AsyncPostgresDb(AsyncBaseDb):
    def __init__(
        self,
        id: Optional[str] = None,
        db_url: Optional[str] = None,
        db_engine: Optional[AsyncEngine] = None,
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
        learnings_table: Optional[str] = None,
        schedules_table: Optional[str] = None,
        schedule_runs_table: Optional[str] = None,
        job_table: Optional[str] = None,
        approvals_table: Optional[str] = None,
        auth_tokens_table: Optional[str] = None,
        service_accounts_table: Optional[str] = None,
        create_schema: bool = True,
    ):
        """
        Async interface for interacting with a PostgreSQL database.

        The following order is used to determine the database connection:
            1. Use the db_engine if provided
            2. Use the db_url
            3. Raise an error if neither is provided

        Connection Pool Configuration:
            When creating an engine from db_url, the following settings are applied:
            - pool_pre_ping=True: Validates connections before use to handle terminated
              connections (e.g., "terminating connection due to administrator command")
            - pool_recycle=3600: Recycles connections after 1 hour to prevent stale connections

            These settings help handle connection terminations gracefully. If you need
            custom pool settings, provide a pre-configured db_engine instead.

        Args:
            id (Optional[str]): The ID of the database.
            db_url (Optional[str]): The database URL to connect to.
            db_engine (Optional[AsyncEngine]): The SQLAlchemy async database engine to use.
            db_schema (Optional[str]): The database schema to use.
            session_table (Optional[str]): Name of the table to store Agent, Team and Workflow sessions.
            runs_table (Optional[str]): Name of the table to store the runs of each session.
            memory_table (Optional[str]): Name of the table to store memories.
            metrics_table (Optional[str]): Name of the table to store metrics.
            eval_table (Optional[str]): Name of the table to store evaluation runs data.
            knowledge_table (Optional[str]): Name of the table to store knowledge content.
            traces_table (Optional[str]): Name of the table to store run traces.
            spans_table (Optional[str]): Name of the table to store span events.
            versions_table (Optional[str]): Name of the table to store schema versions.
            components_table (Optional[str]): Name of the table to store components.
            learnings_table (Optional[str]): Name of the table to store learnings.
            schedules_table (Optional[str]): Name of the table to store cron schedules.
            schedule_runs_table (Optional[str]): Name of the table to store schedule run history.
            job_table (Optional[str]): Name of the table to store durable background run jobs.
            create_schema (bool): Whether to automatically create the database schema if it doesn't exist.
                Set to False if schema is managed externally (e.g., via migrations). Defaults to True.

        Raises:
            ValueError: If neither db_url nor db_engine is provided.
            ValueError: If none of the tables are provided.
        """
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
            learnings_table=learnings_table,
            schedules_table=schedules_table,
            schedule_runs_table=schedule_runs_table,
            job_table=job_table,
            approvals_table=approvals_table,
            auth_tokens_table=auth_tokens_table,
            service_accounts_table=service_accounts_table,
        )

        _engine: Optional[AsyncEngine] = db_engine
        if _engine is None and db_url is not None:
            _engine = create_async_engine(
                db_url,
                pool_pre_ping=True,
                pool_recycle=3600,
                json_serializer=json_serializer,
            )
        if _engine is None:
            raise ValueError("One of db_url or db_engine must be provided")

        self.db_url: Optional[str] = db_url
        self.db_engine: AsyncEngine = _engine
        self.db_schema: str = db_schema if db_schema is not None else "ai"
        self.metadata: MetaData = MetaData(schema=self.db_schema)
        self.create_schema: bool = create_schema

        # Initialize database session factory
        self.async_session_factory = async_sessionmaker(
            bind=self.db_engine,
            expire_on_commit=False,
        )

        # Deserialized history-run objects, keyed per run by the raw row text;
        # see SessionRunObjectCache for the invalidation and immutability
        # contract. Per adapter instance, so it can never serve runs across
        # databases.
        self._run_object_cache = SessionRunObjectCache()
        # Zero means never refreshed; get_metrics uses this to refresh lazily, at most once per minute
        self._metrics_refreshed_at: float = 0.0

    async def close(self) -> None:
        """Close database connections and dispose of the connection pool.

        Should be called during application shutdown to properly release
        all database connections.
        """
        if self.db_engine is not None:
            await self.db_engine.dispose()

    # -- DB methods --
    async def table_exists(self, table_name: str) -> bool:
        """Check if a table with the given name exists in the Postgres database.

        Args:
            table_name: Name of the table to check

        Returns:
            bool: True if the table exists in the database, False otherwise
        """
        async with self.async_session_factory() as sess:
            return await ais_table_available(session=sess, table_name=table_name, db_schema=self.db_schema)

    async def _create_all_tables(self):
        """Create all tables for the database."""
        tables_to_create = [
            (self.session_table_name, "sessions"),
            (self.runs_table_name, "runs"),
            (self.memory_table_name, "memories"),
            (self.metrics_table_name, "metrics"),
            (self.eval_table_name, "evals"),
            (self.knowledge_table_name, "knowledge"),
            (self.versions_table_name, "versions"),
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
            if not await self.table_exists(table_name):
                self._invalidate_table_cache(table_name)
            await self._get_or_create_table(
                table_name=table_name, table_type=table_type, create_table_if_not_found=True
            )

    async def _create_table(self, table_name: str, table_type: str) -> Table:
        """
        Create a table with the appropriate schema based on the table type.

        Args:
            table_name (str): Name of the table to create
            table_type (str): Type of table (used to get schema definition)

        Returns:
            Table: SQLAlchemy Table object
        """
        try:
            # Pass table names and db_schema for foreign key resolution
            table_schema = get_table_schema_definition(
                table_type,
                traces_table_name=self.trace_table_name,
                db_schema=self.db_schema,
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
                        await self._resolve_table(
                            table_name=ref_name,
                            table_type=ref_type,
                            create_table_if_not_found=True,
                        )

            columns: List[Column] = []
            indexes: List[str] = []
            unique_constraints: List[str] = []
            schema_unique_constraints = table_schema.pop("_unique_constraints", [])
            schema_composite_indexes = table_schema.pop("__composite_indexes__", [])
            schema_partial_unique_indexes = table_schema.pop("_partial_unique_indexes", [])

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
                    fk_kwargs = {}
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

            # Composite indexes
            for idx_config in schema_composite_indexes:
                idx_name = f"idx_{table_name}_{'_'.join(idx_config['columns'])}"
                table.append_constraint(Index(idx_name, *idx_config["columns"]))

            # Partial unique indexes
            for idx_config in schema_partial_unique_indexes:
                idx_columns = idx_config["columns"]
                missing = [c for c in idx_columns if c not in table.c]
                if missing:
                    raise ValueError(f"Partial unique index references missing columns in {table_name}: {missing}")

                idx_name = f"{table_name}_{idx_config['name']}"
                Index(
                    idx_name,
                    *[table.c[c] for c in idx_columns],
                    unique=True,
                    postgresql_where=text(idx_config["where"]),
                )

            if self.create_schema:
                async with self.async_session_factory() as sess, sess.begin():
                    await acreate_schema(session=sess, db_schema=self.db_schema)

            # Create table
            table_created = False
            if not await self.table_exists(table_name):
                async with self.db_engine.begin() as conn:
                    await conn.run_sync(table.create, checkfirst=True)
                log_debug(f"Successfully created table '{table_name}'")
                table_created = True
            else:
                log_debug(f"Table '{self.db_schema}.{table_name}' already exists, skipping creation")

            # Create indexes
            for idx in table.indexes:
                try:
                    # Check if index already exists
                    async with self.async_session_factory() as sess:
                        exists_query = text(
                            "SELECT 1 FROM pg_indexes WHERE schemaname = :schema AND indexname = :index_name"
                        )
                        result = await sess.execute(exists_query, {"schema": self.db_schema, "index_name": idx.name})
                        exists = result.scalar() is not None
                        if exists:
                            continue

                    async with self.db_engine.begin() as conn:
                        await conn.run_sync(idx.create)
                    log_debug(f"Created index: {idx.name} for table {self.db_schema}.{table_name}")

                except Exception as e:
                    log_error(f"Error creating index {idx.name}: {str(e)}")

            # Store the schema version for the created table
            if table_name != self.versions_table_name and table_created:
                # Also store the schema version for the created table
                latest_schema_version = MigrationManager(self).latest_schema_version
                await self.upsert_schema_version(table_name=table_name, version=latest_schema_version.public)
                log_info(
                    f"Successfully stored version {latest_schema_version.public} in database for table {table_name}"
                )

            return table

        except Exception as e:
            log_error(f"Could not create table {self.db_schema}.{table_name}: {str(e)}")
            raise

    async def _get_table(self, table_type: str, create_table_if_not_found: Optional[bool] = False) -> Optional[Table]:
        if table_type == "sessions":
            self.session_table = await self._get_or_create_table(
                table_name=self.session_table_name,
                table_type="sessions",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.session_table

        if table_type == "runs":
            self.runs_table = await self._get_or_create_table(
                table_name=self.runs_table_name,
                table_type="runs",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.runs_table

        if table_type == "memories":
            self.memory_table = await self._get_or_create_table(
                table_name=self.memory_table_name,
                table_type="memories",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.memory_table

        if table_type == "metrics":
            self.metrics_table = await self._get_or_create_table(
                table_name=self.metrics_table_name,
                table_type="metrics",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.metrics_table

        if table_type == "evals":
            self.eval_table = await self._get_or_create_table(
                table_name=self.eval_table_name,
                table_type="evals",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.eval_table

        if table_type == "knowledge":
            self.knowledge_table = await self._get_or_create_table(
                table_name=self.knowledge_table_name,
                table_type="knowledge",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.knowledge_table

        if table_type == "versions":
            self.versions_table = await self._get_or_create_table(
                table_name=self.versions_table_name,
                table_type="versions",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.versions_table

        if table_type == "traces":
            self.traces_table = await self._get_or_create_table(
                table_name=self.trace_table_name,
                table_type="traces",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.traces_table

        if table_type == "spans":
            # Ensure traces table exists first (spans has FK to traces)
            if create_table_if_not_found:
                await self._get_table(table_type="traces", create_table_if_not_found=True)
            self.spans_table = await self._get_or_create_table(
                table_name=self.span_table_name,
                table_type="spans",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.spans_table

        if table_type == "learnings":
            self.learnings_table = await self._get_or_create_table(
                table_name=self.learnings_table_name,
                table_type="learnings",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.learnings_table

        if table_type == "schedules":
            self.schedules_table = await self._get_or_create_table(
                table_name=self.schedules_table_name,
                table_type="schedules",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.schedules_table

        if table_type == "schedule_runs":
            self.schedule_runs_table = await self._get_or_create_table(
                table_name=self.schedule_runs_table_name,
                table_type="schedule_runs",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.schedule_runs_table

        if table_type == "jobs":
            self.job_table = await self._get_or_create_table(
                table_name=self.job_table_name,
                table_type="jobs",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.job_table

        if table_type == "tool_results":
            self.tool_results_table = await self._get_or_create_table(
                table_name=self.tool_results_table_name,
                table_type="tool_results",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.tool_results_table

        if table_type == "approvals":
            self.approvals_table = await self._get_or_create_table(
                table_name=self.approvals_table_name,
                table_type="approvals",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.approvals_table

        if table_type == "auth_tokens":
            self.auth_tokens_table = await self._get_or_create_table(
                table_name=self.auth_tokens_table_name,
                table_type="auth_tokens",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.auth_tokens_table

        if table_type == "service_accounts":
            self.service_accounts_table = await self._get_or_create_table(
                table_name=self.service_accounts_table_name,
                table_type="service_accounts",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.service_accounts_table

        raise ValueError(f"Unknown table type: {table_type}")

    async def _resolve_table(
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

        async with self.async_session_factory() as sess, sess.begin():
            table_is_available = await ais_table_available(
                session=sess, table_name=table_name, db_schema=self.db_schema
            )

        if not table_is_available:
            if not create_table_if_not_found:
                return None
            table = await self._create_table(table_name=table_name, table_type=table_type)
            self._store_resolved_table(table_type, table_name, table)
            return table

        if not await ais_valid_table(
            db_engine=self.db_engine,
            table_name=table_name,
            table_type=table_type,
            db_schema=self.db_schema,
        ):
            raise table_schema_mismatch_error(f"{self.db_schema}.{table_name}", table_type=table_type)

        try:
            async with self.db_engine.connect() as conn:

                def create_table(connection):
                    return Table(table_name, self.metadata, schema=self.db_schema, autoload_with=connection)

                table = await conn.run_sync(create_table)

                self._store_resolved_table(table_type, table_name, table)
                return table

        except Exception as e:
            log_error(f"Error loading existing table {self.db_schema}.{table_name}: {str(e)}")
            raise

    async def get_latest_schema_version(self, table_name: str) -> str:
        """Get the latest version of the database schema."""
        table = await self._get_table(table_type="versions", create_table_if_not_found=True)
        if table is None:
            return "2.0.0"

        async with self.async_session_factory() as sess:
            stmt = select(table)
            # Latest version for the given table
            stmt = stmt.where(table.c.table_name == table_name)
            stmt = stmt.order_by(table.c.version.desc()).limit(1)
            result = await sess.execute(stmt)
            row = result.fetchone()
            if row is None:
                return "2.0.0"

            version_dict = dict(row._mapping)
            return version_dict.get("version") or "2.0.0"

    async def upsert_schema_version(self, table_name: str, version: str) -> None:
        """Upsert the schema version into the database."""
        table = await self._get_table(table_type="versions", create_table_if_not_found=True)
        if table is None:
            return
        current_datetime = datetime.now().isoformat()
        async with self.async_session_factory() as sess, sess.begin():
            stmt = postgresql.insert(table).values(
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
            await sess.execute(stmt)

    async def cleanup_legacy_runs_column(self, force: bool = False) -> bool:
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
        async with self.async_session_factory() as sess, sess.begin():
            column_exists = (
                await sess.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_schema = :schema AND table_name = :table AND column_name = 'runs'"
                    ),
                    {"schema": self.db_schema, "table": self.session_table_name},
                )
            ).scalar() is not None
            if not column_exists:
                log_info(f"{self.session_table_name}.runs column does not exist, nothing to clean up")
                return False

            if not force:
                pending = (
                    await sess.execute(
                        text(
                            f'SELECT COUNT(*) FROM {self.db_schema}."{self.session_table_name}" WHERE runs IS NOT NULL'
                        )
                    )
                ).scalar() or 0
                if pending > 0:
                    raise RuntimeError(
                        f"Refusing to drop {self.session_table_name}.runs: {pending} session(s) still have "
                        "non-null `runs` content. Run MigrationManager(db).up() first, or pass force=True."
                    )

            log_info(f"Dropping legacy runs column from {self.session_table_name}")
            await sess.execute(text(f'ALTER TABLE {self.db_schema}."{self.session_table_name}" DROP COLUMN runs'))

        self._invalidate_table_cache(self.session_table_name)
        return True

    # -- Run methods --
    async def _get_session_run_rows(self, sess, runs_table: Table, session_id: str) -> List[Tuple[str, str]]:
        """(run_id, raw run_data text) for the whole session, in insertion order.

        The raw text feeds the run-object cache, which parses and rebuilds a
        run only when its text changed since the last read. The cast keeps the
        JSON column's result processor out of the way -- the whole point is to
        not parse unchanged rows.
        """
        import json

        from sqlalchemy import Text

        stmt = (
            select(runs_table.c.run_id, runs_table.c.run_data.cast(Text))
            .where(runs_table.c.session_id == session_id)
            .order_by(
                runs_table.c.run_index.asc(),
                runs_table.c.created_at.asc(),
                runs_table.c.run_id.asc(),
            )
        )
        result = await sess.execute(stmt)
        rows = result.fetchall()
        return [(run_id, run_data if isinstance(run_data, str) else json.dumps(run_data)) for run_id, run_data in rows]

    async def _get_session_runs_data(
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
            result = await sess.execute(stmt)
            rows = [row[0] for row in result.fetchall()]
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
        result = await sess.execute(stmt)
        return [row[0] for row in result.fetchall()]

    async def _get_sessions_runs_data(
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
        result = await sess.execute(stmt)
        runs_by_session: Dict[str, List[Dict[str, Any]]] = {}
        for session_id, run_data in result.fetchall():
            runs_by_session.setdefault(session_id, []).append(run_data)
        return runs_by_session

    async def get_run(
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
            table = await self._get_table(table_type="runs")
            if table is None:
                return None

            async with self.async_session_factory() as sess:
                result = await sess.execute(select(table).where(table.c.run_id == run_id))
                row = result.fetchone()
                if row is None:
                    return None

                run_row = dict(row._mapping)

            if not deserialize:
                return run_row

            return deserialize_run(run_row.get("run_type"), run_row["run_data"])

        except Exception as e:
            log_error(f"Exception reading from runs table: {str(e)}")
            return None

    async def upsert_run(
        self,
        run: Union[RunOutput, TeamRunOutput, WorkflowRunOutput, Dict[str, Any]],
        session_id: str,
        user_id: Optional[str] = None,
        run_index: Optional[int] = None,
    ) -> None:
        """Upsert a single run to the runs table (O(1) operation).

        This is optimized for updating existing runs (e.g., status changes in HITL
        or background mode) without re-upserting all runs in the session.

        For new runs, the run_index should be provided or will be read from run_data.
        For updates to existing runs, run_index is preserved from the original insert.

        Args:
            run: The run object or dictionary to upsert.
            session_id: The session ID this run belongs to.
            user_id: Optional user ID to associate with the run.
            run_index: Optional run index for new runs. If not provided for new runs,
                will attempt to read from run_data.

        Raises:
            ValueError: If the run has no run_id.
            Exception: If an error occurs during upsert.
        """
        try:
            runs_table = await self._get_table(table_type="runs", create_table_if_not_found=True)
            if runs_table is None:
                return

            row = build_single_run_row(
                run=run,
                session_id=session_id,
                user_id=user_id,
                run_index=run_index,
            )
            row["run_data"] = sanitize_postgres_strings(row["run_data"])

            async with self.async_session_factory() as sess:
                async with sess.begin():
                    # Backfill a monotonic run_index when the run arrives without one
                    # (e.g. a background/continue save that couldn't resolve its position).
                    # A NULL index has no position and breaks ORDER BY run_index. ON CONFLICT
                    # preserves the existing index, so this only sets it on a genuine insert.
                    if row.get("run_index") is None:
                        # Serialize same-session backfills: under READ COMMITTED two
                        # concurrent max-reads can both see the same MAX and land
                        # duplicate indexes. The advisory lock is transaction-scoped
                        # (released at COMMIT/ROLLBACK) and keyed on session_id, so
                        # only same-session backfilling inserts queue behind it.
                        await sess.execute(
                            text("SELECT pg_advisory_xact_lock(hashtext('agno_run_index'), hashtext(:sid))"),
                            {"sid": session_id},
                        )
                        current_max = (
                            await sess.execute(
                                select(func.max(runs_table.c.run_index)).where(runs_table.c.session_id == session_id)
                            )
                        ).scalar()
                        row["run_index"] = (current_max + 1) if current_max is not None else 0

                    stmt = postgresql.insert(runs_table).values(**row)
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
                    await sess.execute(stmt)

        except Exception as e:
            log_error(f"Exception upserting run to runs table: {str(e)}")
            raise e

    async def get_runs(
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
            table = await self._get_table(table_type="runs")
            if table is None:
                return [] if deserialize else ([], 0)

            async with self.async_session_factory() as sess:
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
                total_count = await sess.scalar(count_stmt) or 0

                if sort_by is not None:
                    stmt = apply_sorting(stmt, table, sort_by, sort_order)
                else:
                    stmt = stmt.order_by(table.c.run_index.asc(), table.c.created_at.asc())

                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset((page - 1) * limit)

                result = await sess.execute(stmt)
                run_rows = [dict(record._mapping) for record in result.fetchall()]

            if not deserialize:
                return run_rows, total_count

            return [deserialize_run(row.get("run_type"), row["run_data"]) for row in run_rows]

        except Exception as e:
            log_error(f"Exception reading from runs table: {str(e)}")
            return [] if deserialize else ([], 0)

    async def _ascrub_run_ids_from_legacy_blob(self, run_ids: List[str]) -> None:
        """Async variant of the legacy-blob scrub. See postgres.py for rationale."""
        if not run_ids:
            return
        try:
            sessions_table = await self._get_table(table_type="sessions")
            if sessions_table is None or "runs" not in sessions_table.c:
                return
            stmt = text(
                f"""
                UPDATE {sessions_table.name}
                SET runs = COALESCE(
                    (SELECT jsonb_agg(elem)
                     FROM jsonb_array_elements(runs) elem
                     WHERE elem->>'run_id' <> ALL(:ids)),
                    '[]'::jsonb
                )
                WHERE runs IS NOT NULL
                  AND jsonb_typeof(runs) = 'array'
                  AND EXISTS (
                      SELECT 1 FROM jsonb_array_elements(runs) elem
                      WHERE elem->>'run_id' = ANY(:ids)
                  )
                """
            )
            async with self.async_session_factory() as sess, sess.begin():
                await sess.execute(stmt, {"ids": list(run_ids)})
        except Exception:
            log_debug("legacy-runs scrub failed; the primary delete still succeeded", exc_info=True)

    async def delete_run(self, run_id: str) -> bool:
        """Delete a single run from the runs table.

        Args:
            run_id (str): The ID of the run to delete.

        Returns:
            bool: True if the run was deleted, False otherwise.
        """
        try:
            table = await self._get_table(table_type="runs")
            if table is None:
                return False

            async with self.async_session_factory() as sess, sess.begin():
                result = await sess.execute(table.delete().where(table.c.run_id == run_id))
                deleted = result.rowcount > 0  # type: ignore

            await self._ascrub_run_ids_from_legacy_blob([run_id])
            return deleted

        except Exception as e:
            log_error(f"Error deleting run: {str(e)}")
            return False

    async def delete_runs(self, run_ids: List[str]) -> None:
        """Delete all given runs from the runs table.

        Args:
            run_ids (List[str]): The IDs of the runs to delete.
        """
        try:
            table = await self._get_table(table_type="runs")
            if table is None:
                return

            async with self.async_session_factory() as sess, sess.begin():
                result = await sess.execute(table.delete().where(table.c.run_id.in_(run_ids)))

            await self._ascrub_run_ids_from_legacy_blob(list(run_ids))
            log_debug(f"Successfully deleted {result.rowcount} runs")  # type: ignore

        except Exception as e:
            log_error(f"Error deleting runs: {str(e)}")

    # -- Session methods --
    async def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
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
            table = await self._get_table(table_type="sessions")
            if table is None:
                return False
            runs_table = await self._get_table(table_type="runs")

            async with self.async_session_factory() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.session_id == session_id)
                if user_id is not None:
                    delete_stmt = delete_stmt.where(table.c.user_id == user_id)
                result = await sess.execute(delete_stmt)

                if result.rowcount == 0:  # type: ignore
                    log_debug(f"No session found to delete with session_id: {session_id} in table {table.name}")
                    return False

                # Also delete the runs belonging to the session
                if runs_table is not None:
                    await sess.execute(runs_table.delete().where(runs_table.c.session_id == session_id))

                log_debug(f"Successfully deleted session with session_id: {session_id} in table {table.name}")

            # Cascade offloaded tool results after the session delete commits.
            await self._cascade_tool_results([session_id])
            # A deleted session's deserialized history must not stay resident.
            self._run_object_cache.drop_session(session_id)
            return True

        except Exception as e:
            log_error(f"Error deleting session: {str(e)}")
            return False

    async def delete_sessions(self, session_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete all given sessions from the database.
        Can handle multiple session types in the same run.

        Args:
            session_ids (List[str]): The IDs of the sessions to delete.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = await self._get_table(table_type="sessions")
            if table is None:
                return
            runs_table = await self._get_table(table_type="runs")

            async with self.async_session_factory() as sess, sess.begin():
                # The ids a user_id-scoped delete is allowed to touch. The
                # cascade below removes stored payloads, which no filter on the
                # sessions table would stop it from doing for another user's
                # session id.
                select_stmt = select(table.c.session_id).where(table.c.session_id.in_(session_ids))
                if user_id is not None:
                    select_stmt = select_stmt.where(table.c.user_id == user_id)
                deletable_ids = [row[0] for row in await sess.execute(select_stmt)]
                # Stored payloads are cascaded only for sessions this delete
                # was allowed to remove. An unscoped delete has no other user
                # to protect, so it also cleans up after a session whose row
                # is already gone.
                cascade_ids = session_ids if user_id is None else deletable_ids

                delete_stmt = table.delete().where(table.c.session_id.in_(deletable_ids))
                result = await sess.execute(delete_stmt)

                # Also delete the runs belonging to the sessions
                if runs_table is not None:
                    runs_delete_stmt = runs_table.delete().where(runs_table.c.session_id.in_(session_ids))
                    if user_id is not None:
                        runs_delete_stmt = runs_delete_stmt.where(runs_table.c.user_id == user_id)
                    await sess.execute(runs_delete_stmt)

            log_debug(f"Successfully deleted {result.rowcount} sessions")  # type: ignore

            # Cascade offloaded tool results after the session delete commits.
            await self._cascade_tool_results(cascade_ids)
            for deleted_id in cascade_ids:
                self._run_object_cache.drop_session(deleted_id)

        except Exception as e:
            log_error(f"Error deleting sessions: {str(e)}")

    async def _cascade_tool_results(self, session_ids: List[str]) -> None:
        """Cascade result offloading on session delete: read the index rows,
        delete their payloads, then the index rows.

        Best-effort and outside the session delete, so a cascade failure can
        never poison or roll back the delete itself. Payloads are removed by
        the exact (namespace, path) of each index row, through the
        filesystems result stores registered on this db, or from the AgentFS
        table at its defaults when no store registered.
        """
        try:
            table = await self._get_table(table_type="tool_results")
            if table is None:
                return
            async with self.async_session_factory() as sess:
                result = await sess.execute(
                    select(table.c.result_id, table.c.namespace, table.c.path).where(
                        table.c.session_id.in_(session_ids)
                    )
                )
                rows = result.fetchall()
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
                            if await FileSystem(backend=fs.backend, namespace=str(namespace)).adelete(str(path)):
                                removed.add((str(namespace), str(path)))
                        except Exception as e:
                            log_warning(f"Tool-result payload delete failed for {namespace}/{path}: {e}")
            async with self.async_session_factory() as sess, sess.begin():
                if await self._adefault_payload_table_exists(sess):
                    for _, namespace, path in rows:
                        if (str(namespace), str(path)) in removed:
                            continue
                        result = await sess.execute(
                            text(f"DELETE FROM {self._default_payload_table()} WHERE namespace = :ns AND path = :p"),
                            {"ns": str(namespace), "p": str(path)},
                        )
                        if getattr(result, "rowcount", 0):
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
                async with self.async_session_factory() as sess, sess.begin():
                    await sess.execute(table.delete().where(table.c.result_id.in_(result_ids[start : start + 500])))
        except Exception as e:
            log_warning(f"Tool-result cascade on session delete failed: {e}")

    @staticmethod
    def _default_payload_table() -> str:
        return '"fs".agno_fs'

    @staticmethod
    async def _adefault_payload_table_exists(sess: Any) -> bool:
        return (await sess.execute(text("SELECT to_regclass('fs.agno_fs')"))).scalar() is not None

    # -- Tool Results (result offloading index) --

    async def upsert_tool_result(self, row: Dict[str, Any]) -> None:
        table = await self._get_table(table_type="tool_results", create_table_if_not_found=True)
        if table is None:
            raise ValueError(f"Could not create table: {self.tool_results_table_name}")
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(table).values(**row)
        update_columns = {key: stmt.excluded[key] for key in row.keys() if key != "result_id"}
        stmt = stmt.on_conflict_do_update(index_elements=["result_id"], set_=update_columns)
        async with self.async_session_factory() as sess, sess.begin():
            await sess.execute(stmt)

    async def get_tool_result(self, result_id: str) -> Optional[Dict[str, Any]]:
        table = await self._get_table(table_type="tool_results")
        if table is None:
            return None
        async with self.async_session_factory() as sess:
            result = await sess.execute(select(table).where(table.c.result_id == result_id))
            row = result.fetchone()
            return dict(row._mapping) if row is not None else None

    async def get_tool_results_for_session(self, session_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        table = await self._get_table(table_type="tool_results")
        if table is None:
            return []
        stmt = (
            select(table).where(table.c.session_id == session_id).order_by(table.c.created_at.desc(), table.c.result_id)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        async with self.async_session_factory() as sess:
            result = await sess.execute(stmt)
            return [dict(row._mapping) for row in result.fetchall()]

    async def delete_tool_results(self, result_ids: List[str]) -> int:
        if not result_ids:
            return 0
        table = await self._get_table(table_type="tool_results")
        if table is None:
            return 0
        async with self.async_session_factory() as sess, sess.begin():
            result = await sess.execute(table.delete().where(table.c.result_id.in_(result_ids)))
        return result.rowcount or 0  # type: ignore

    async def get_expired_tool_results(self, now: int) -> List[Dict[str, Any]]:
        table = await self._get_table(table_type="tool_results")
        if table is None:
            return []
        stmt = select(table).where(table.c.expires_at.is_not(None)).where(table.c.expires_at <= now)
        async with self.async_session_factory() as sess:
            result = await sess.execute(stmt)
            return [dict(row._mapping) for row in result.fetchall()]

    async def get_session(
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
            user_id (Optional[str]): User ID to filter by. Defaults to None.
            session_type (Optional[SessionType]): Type of session to read. Defaults to None.
            deserialize (Optional[bool]): Whether to serialize the session. Defaults to True.
            runs_limit (Optional[int]): If set, attach only the most recent ``runs_limit``
                runs instead of the full history. For a fully-migrated session this is an
                indexed ``ORDER BY run_index DESC LIMIT`` query; for a session that still
                carries a legacy ``runs`` blob it falls back to a full load + merge, then
                slices, so no history is ever lost.

        Returns:
            Union[Session, Dict[str, Any], None]:
                - When deserialize=True: Session object
                - When deserialize=False: Session dictionary

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table = await self._get_table(table_type="sessions")
            if table is None:
                return None
            runs_table = await self._get_table(table_type="runs")

            async with self.async_session_factory() as sess:
                stmt = select(table).where(table.c.session_id == session_id)

                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)

                result = await sess.execute(stmt)
                row = result.fetchone()
                if row is None:
                    return None

                session = dict(row._mapping)

                # Attach the runs stored in the runs table, merged with any runs still
                # sitting in the legacy `runs` column (so partially-migrated sessions
                # don't silently lose history).
                legacy_runs = session.get("runs")
                run_rows: Optional[List[Tuple[str, str]]] = None
                if runs_table is not None and runs_limit is not None and not legacy_runs:
                    # Fully migrated: push "most recent N" down to the DB (indexed).
                    session["runs"] = await self._get_session_runs_data(
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
                    run_rows = await self._get_session_run_rows(sess=sess, runs_table=runs_table, session_id=session_id)
                    session["runs"] = None
                elif runs_table is not None:
                    # Full load + merge. Also the un-migrated fallback: the legacy blob
                    # holds the whole history in one column, so "last N" can't be pushed
                    # to SQL — load all, merge, then filter+slice to match the migrated path.
                    runs_data = await self._get_session_runs_data(
                        sess=sess, runs_table=runs_table, session_id=session_id
                    )
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

    async def get_sessions(
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
            user_id (Optional[str]): The ID of the user to filter by.
            component_id (Optional[str]): The ID of the agent / workflow to filter by.
            start_timestamp (Optional[int]): The start timestamp to filter by.
            end_timestamp (Optional[int]): The end timestamp to filter by.
            session_name (Optional[str]): The name of the session to filter by.
            limit (Optional[int]): The maximum number of sessions to return. Defaults to None.
            page (Optional[int]): The page number to return. Defaults to None.
            sort_by (Optional[str]): The field to sort by. Defaults to None.
            sort_order (Optional[str]): The sort order. Defaults to None.
            deserialize (Optional[bool]): Whether to serialize the sessions. Defaults to True.

        Returns:
            Union[List[Session], Tuple[List[Dict], int]]:
                - When deserialize=True: List of Session objects
                - When deserialize=False: Tuple of (session dictionaries, total count)

        Raises:
            Exception: If an error occurs during retrieval.
        """
        validate_pagination(limit, page)
        try:
            table = await self._get_table(table_type="sessions")
            if table is None:
                return [] if deserialize else ([], 0)
            runs_table = await self._get_table(table_type="runs")

            async with self.async_session_factory() as sess, sess.begin():
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
                    stmt = stmt.where(
                        func.coalesce(table.c.session_data["session_name"].astext, "").ilike(f"%{session_name}%")
                    )
                if session_type is not None:
                    session_type_value = session_type.value if isinstance(session_type, SessionType) else session_type
                    stmt = stmt.where(table.c.session_type == session_type_value)

                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = await sess.scalar(count_stmt) or 0

                # Sorting
                stmt = apply_sorting(stmt, table, sort_by, sort_order)

                # Paginating
                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset((page - 1) * limit)

                result = await sess.execute(stmt)
                records = result.fetchall()
                if records is None:
                    return [], 0

                session = [dict(record._mapping) for record in records]

                # Attach the runs stored in the runs table. If a session has no rows in the
                # runs table, fall back to its legacy `runs` column content, if any.
                if include_runs and runs_table is not None:
                    runs_by_session = await self._get_sessions_runs_data(
                        sess=sess, runs_table=runs_table, session_ids=[s["session_id"] for s in session]
                    )
                    for s in session:
                        runs_data = runs_by_session.get(s["session_id"], [])
                        s["runs"] = merge_runs_table_with_legacy_blob(runs_data, s.get("runs"))
                elif not include_runs:
                    # List views don't need run history; leave it unattached (storage untouched).
                    for s in session:
                        s["runs"] = None

                if not deserialize:
                    return session, total_count

            return deserialize_sessions(session_type, session)

        except Exception as e:
            log_error(f"Exception reading from session table: {str(e)}")
            return [] if deserialize else ([], 0)

    async def rename_session(
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
            table = await self._get_table(table_type="sessions")
            if table is None:
                return None
            runs_table = await self._get_table(table_type="runs")

            async with self.async_session_factory() as sess, sess.begin():
                # Sanitize session_name to remove null bytes
                sanitized_session_name = sanitize_postgres_string(session_name)
                stmt = (
                    update(table)
                    .where(table.c.session_id == session_id)
                    .values(
                        session_data=func.cast(
                            func.jsonb_set(
                                func.cast(table.c.session_data, postgresql.JSONB),
                                text("'{session_name}'"),
                                func.to_jsonb(sanitized_session_name),
                            ),
                            postgresql.JSON,
                        )
                    )
                    .returning(*table.c)
                )
                if session_type is not None:
                    stmt = stmt.where(table.c.session_type == session_type.value)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                result = await sess.execute(stmt)
                row = result.fetchone()
                if not row:
                    return None

                session = dict(row._mapping)

                # Attach the runs stored in the runs table, merged with any runs still
                # sitting in the legacy `runs` column (so partially-migrated sessions
                # don't silently lose history).
                if runs_table is not None:
                    runs_data = await self._get_session_runs_data(
                        sess=sess, runs_table=runs_table, session_id=session_id
                    )
                    session["runs"] = merge_runs_table_with_legacy_blob(runs_data, session.get("runs"))

            log_debug(f"Renamed session with id '{session_id}' to '{session_name}'")

            if not deserialize:
                return session

            return deserialize_session(session_type, session)

        except Exception as e:
            log_error(f"Exception renaming session: {str(e)}")
            return None

    async def upsert_session(
        self, session: Session, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """
        Insert or update the session row.

        Runs are persisted independently via ``upsert_run()`` — this method does
        not touch the ``agno_runs`` table.

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
            table = await self._get_table(table_type="sessions", create_table_if_not_found=True)
            if table is None:
                return None

            session_dict = session.to_dict(include_runs=False)
            # Sanitize JSON/dict fields to remove null bytes from nested strings
            if session_dict.get("agent_data"):
                session_dict["agent_data"] = sanitize_postgres_strings(session_dict["agent_data"])
            if session_dict.get("team_data"):
                session_dict["team_data"] = sanitize_postgres_strings(session_dict["team_data"])
            if session_dict.get("workflow_data"):
                session_dict["workflow_data"] = sanitize_postgres_strings(session_dict["workflow_data"])
            if session_dict.get("session_data"):
                session_dict["session_data"] = sanitize_postgres_strings(session_dict["session_data"])
            if session_dict.get("summary"):
                session_dict["summary"] = sanitize_postgres_strings(session_dict["summary"])
            if session_dict.get("metadata"):
                session_dict["metadata"] = sanitize_postgres_strings(session_dict["metadata"])

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
            # The legacy `runs` column is intentionally left untouched here. Runs now
            # live in the runs table; the legacy column stays as a frozen backup and is
            # only reclaimed by the explicit cleanup_legacy_runs_column() helper. Nulling
            # it on write would lose history for sessions not yet migrated to the runs table.

            async with self.async_session_factory() as sess, sess.begin():
                stmt = postgresql.insert(table).values(
                    session_id=session_dict.get("session_id"),
                    created_at=session_dict.get("created_at"),
                    updated_at=session_dict.get("created_at"),
                    **values,
                )
                stmt = stmt.on_conflict_do_update(  # type: ignore
                    index_elements=["session_id"],
                    set_=dict(updated_at=int(time.time()), **update_values),
                    where=(table.c.user_id == session_dict.get("user_id")) | (table.c.user_id.is_(None)),
                ).returning(table)
                result = await sess.execute(stmt)
                row = result.fetchone()
                if row is None:
                    return None
                session_dict = dict(row._mapping)

            log_debug(f"Upserted session with id '{session_dict.get('session_id')}'")

            if not deserialize:
                session_dict["runs"] = [run if isinstance(run, dict) else run.to_dict() for run in session.runs or []]
                return session_dict

            session_dict.pop("runs", None)
            upserted_session = deserialize_session(None, session_dict)
            upserted_session.runs = session.runs  # type: ignore[union-attr]
            return upserted_session

        except Exception as e:
            log_error(f"Exception upserting into sessions table: {str(e)}")
            return None

    # -- Memory methods --
    async def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None):
        """Delete a user memory from the database.

        Returns:
            bool: True if deletion was successful, False otherwise.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = await self._get_table(table_type="memories")
            if table is None:
                return

            async with self.async_session_factory() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.memory_id == memory_id)
                if user_id is not None:
                    delete_stmt = delete_stmt.where(table.c.user_id == user_id)
                result = await sess.execute(delete_stmt)

                success = result.rowcount > 0  # type: ignore
                if success:
                    log_debug(f"Successfully deleted user memory id: {memory_id}")
                else:
                    log_debug(f"No user memory found with id: {memory_id}")

        except Exception as e:
            log_error(f"Error deleting user memory: {str(e)}")

    async def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete user memories from the database.

        Args:
            memory_ids (List[str]): The IDs of the memories to delete.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = await self._get_table(table_type="memories")
            if table is None:
                return

            async with self.async_session_factory() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.memory_id.in_(memory_ids))

                if user_id is not None:
                    delete_stmt = delete_stmt.where(table.c.user_id == user_id)

                result = await sess.execute(delete_stmt)

                if result.rowcount == 0:  # type: ignore
                    log_debug(f"No user memories found with ids: {memory_ids}")
                else:
                    log_debug(f"Successfully deleted {result.rowcount} user memories")  # type: ignore

        except Exception as e:
            log_error(f"Error deleting user memories: {str(e)}")

    async def get_all_memory_topics(self, user_id: Optional[str] = None) -> List[str]:
        """Get all memory topics from the database.

        Args:
            user_id (Optional[str]): The ID of the user to filter by.

        Returns:
            List[str]: List of memory topics.
        """
        try:
            table = await self._get_table(table_type="memories")
            if table is None:
                return []

            async with self.async_session_factory() as sess, sess.begin():
                # Filter out NULL topics and ensure topics is an array before extracting elements
                # jsonb_typeof returns 'array' for JSONB arrays
                conditions = [
                    table.c.topics.is_not(None),
                    func.jsonb_typeof(table.c.topics) == "array",
                ]
                if user_id is not None:
                    conditions.append(table.c.user_id == user_id)

                try:
                    # jsonb_array_elements_text is a set-returning function that must be used with select_from
                    stmt = select(func.jsonb_array_elements_text(table.c.topics).label("topic"))
                    stmt = stmt.select_from(table)
                    stmt = stmt.where(and_(*conditions))
                    result = await sess.execute(stmt)
                except ProgrammingError:
                    # Retrying with json_array_elements_text. This works in older versions,
                    # where the topics column was of type JSON instead of JSONB
                    # For JSON (not JSONB), we use json_typeof
                    json_conditions = [
                        table.c.topics.is_not(None),
                        func.json_typeof(table.c.topics) == "array",
                    ]
                    if user_id is not None:
                        json_conditions.append(table.c.user_id == user_id)
                    stmt = select(func.json_array_elements_text(table.c.topics).label("topic"))
                    stmt = stmt.select_from(table)
                    stmt = stmt.where(and_(*json_conditions))
                    result = await sess.execute(stmt)

                records = result.fetchall()
                # Extract topics from records - each record is a Row with a 'topic' attribute
                topics = [record.topic for record in records if record.topic is not None]
                return list(set(topics))

        except Exception as e:
            log_error(f"Exception reading from memory table: {str(e)}")
            return []

    async def get_user_memory(
        self,
        memory_id: str,
        deserialize: Optional[bool] = True,
        user_id: Optional[str] = None,
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Get a memory from the database.

        Args:
            memory_id (str): The ID of the memory to get.
            deserialize (Optional[bool]): Whether to serialize the memory. Defaults to True.
            user_id (Optional[str]): The ID of the user to filter by.

        Returns:
            Union[UserMemory, Dict[str, Any], None]:
                - When deserialize=True: UserMemory object
                - When deserialize=False: UserMemory dictionary

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table = await self._get_table(table_type="memories")
            if table is None:
                return None

            async with self.async_session_factory() as sess, sess.begin():
                stmt = select(table).where(table.c.memory_id == memory_id)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)

                result = await sess.execute(stmt)
                row = result.fetchone()
                if not row:
                    return None

                memory_raw = dict(row._mapping)
                if not deserialize:
                    return memory_raw

            return UserMemory.from_dict(memory_raw)

        except Exception as e:
            log_error(f"Exception reading from memory table: {str(e)}")
            return None

    async def get_user_memories(
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
                - When deserialize=False: Tuple of (memory dictionaries, total count)

        Raises:
            Exception: If an error occurs during retrieval.
        """
        validate_pagination(limit, page)
        try:
            table = await self._get_table(table_type="memories")
            if table is None:
                return [] if deserialize else ([], 0)

            async with self.async_session_factory() as sess, sess.begin():
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
                    stmt = stmt.where(func.cast(table.c.memory, postgresql.TEXT).ilike(f"%{search_content}%"))

                # Get total count after applying filtering
                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = await sess.scalar(count_stmt) or 0

                # Sorting
                stmt = apply_sorting(stmt, table, sort_by, sort_order)

                # Paginating
                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset((page - 1) * limit)

                result = await sess.execute(stmt)
                records = result.fetchall()
                if not records:
                    return [] if deserialize else ([], 0)

                memories_raw = [dict(record._mapping) for record in records]
                if not deserialize:
                    return memories_raw, total_count

            return [UserMemory.from_dict(record) for record in memories_raw]

        except Exception as e:
            log_error(f"Exception reading from memory table: {str(e)}")
            return [] if deserialize else ([], 0)

    async def clear_memories(self) -> None:
        """Delete all memories from the database.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = await self._get_table(table_type="memories")
            if table is None:
                return

            async with self.async_session_factory() as sess, sess.begin():
                await sess.execute(table.delete())

        except Exception as e:
            log_warning(f"Exception deleting all memories: {str(e)}")

    async def get_user_memory_stats(
        self, limit: Optional[int] = None, page: Optional[int] = None, user_id: Optional[str] = None
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
            table = await self._get_table(table_type="memories")
            if table is None:
                return [], 0

            async with self.async_session_factory() as sess, sess.begin():
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
                total_count = await sess.scalar(count_stmt) or 0

                # Pagination
                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset((page - 1) * limit)

                result = await sess.execute(stmt)
                records = result.fetchall()
                if not records:
                    return [], 0

                return [
                    {
                        "user_id": record.user_id,  # type: ignore
                        "total_memories": record.total_memories,
                        "last_memory_updated_at": record.last_memory_updated_at,
                    }
                    for record in records
                ], total_count

        except Exception as e:
            log_error(f"Exception getting user memory stats: {str(e)}")
            return [], 0

    async def upsert_user_memory(
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
            table = await self._get_table(table_type="memories", create_table_if_not_found=True)
            if table is None:
                return None

            current_time = int(time.time())

            # Sanitize string fields to remove null bytes (PostgreSQL doesn't allow them)
            sanitized_input = sanitize_postgres_string(memory.input)
            sanitized_feedback = sanitize_postgres_string(memory.feedback)
            # Sanitize JSONB fields to remove null bytes from nested strings
            sanitized_memory = sanitize_postgres_strings(memory.memory) if memory.memory else None
            sanitized_topics = sanitize_postgres_strings(memory.topics) if memory.topics else None

            async with self.async_session_factory() as sess:
                async with sess.begin():
                    if memory.memory_id is None:
                        memory.memory_id = str(uuid4())

                    stmt = postgresql.insert(table).values(
                        memory_id=memory.memory_id,
                        memory=sanitized_memory,
                        input=sanitized_input,
                        user_id=memory.user_id,
                        agent_id=memory.agent_id,
                        team_id=memory.team_id,
                        topics=sanitized_topics,
                        feedback=sanitized_feedback,
                        created_at=memory.created_at,
                        updated_at=memory.updated_at
                        if memory.updated_at is not None
                        else (memory.created_at if memory.created_at is not None else current_time),
                    )
                    stmt = stmt.on_conflict_do_update(  # type: ignore
                        index_elements=["memory_id"],
                        set_=dict(
                            memory=sanitized_memory,
                            topics=sanitized_topics,
                            input=sanitized_input,
                            agent_id=memory.agent_id,
                            team_id=memory.team_id,
                            feedback=sanitized_feedback,
                            updated_at=current_time,
                            # Preserve created_at on update - don't overwrite existing value
                            created_at=table.c.created_at,
                        ),
                    ).returning(table)

                    result = await sess.execute(stmt)
                    row = result.fetchone()
                    if row is None:
                        return None

            memory_raw = dict(row._mapping)

            log_debug(f"Upserted user memory with id '{memory.memory_id}'")

            if not memory_raw or not deserialize:
                return memory_raw

            return UserMemory.from_dict(memory_raw)

        except Exception as e:
            log_error(f"Exception upserting user memory: {str(e)}")
            return None

    # -- Metrics methods --
    async def _get_all_sessions_for_metrics_calculation(
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
            table = await self._get_table(table_type="sessions")
            if table is None:
                return []
            runs_table = await self._get_table(table_type="runs")

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

            async with self.async_session_factory() as sess:
                result = await sess.execute(stmt)
                records = result.fetchall()
                sessions = [dict(record._mapping) for record in records]

                # Attach lightweight run info (model and provider) from the runs table
                if runs_table is not None and sessions:
                    session_ids = [s["session_id"] for s in sessions]
                    runs_stmt = select(
                        runs_table.c.session_id,
                        runs_table.c.run_data["model"].astext.label("model"),
                        runs_table.c.run_data["model_provider"].astext.label("model_provider"),
                    ).where(runs_table.c.session_id.in_(session_ids))

                    runs_result = await sess.execute(runs_stmt)
                    runs_by_session: Dict[str, List[Dict[str, Any]]] = {}
                    for session_id, model, model_provider in runs_result.fetchall():
                        runs_by_session.setdefault(session_id, []).append(
                            {"model": model, "model_provider": model_provider}
                        )

                    for s in sessions:
                        runs_data = runs_by_session.get(s["session_id"], [])
                        if runs_data or not s.get("runs"):
                            s["runs"] = runs_data

                return sessions

        except Exception as e:
            log_error(f"Exception reading from sessions table: {str(e)}")
            return []

    async def _get_metrics_calculation_starting_date(self, table: Table) -> Optional[date]:
        """Get the first date for which metrics calculation is needed:

        1. If there are metrics records, return the date of the first day without a complete metrics record.
        2. If there are no metrics records, return the date of the first recorded session.
        3. If there are no metrics records and no sessions records, return None.

        Args:
            table (Table): The table to get the starting date for.

        Returns:
            Optional[date]: The starting date for which metrics calculation is needed.
        """
        async with self.async_session_factory() as sess:
            # resume at the earliest incomplete day after the latest completed one, otherwise the
            # day after that one: a day holding a completed row was rebuilt after it ended, so an
            # incomplete row sharing it belongs to an owner whose sessions have gone and can never
            # be rebuilt
            latest_completed = (
                await sess.execute(select(func.max(table.c.date)).where(table.c.completed.is_(True)))
            ).scalar()

            incomplete_stmt = select(func.min(table.c.date)).where(table.c.completed.is_(False))
            if latest_completed is not None:
                incomplete_stmt = incomplete_stmt.where(table.c.date > latest_completed)
            earliest_incomplete = (await sess.execute(incomplete_stmt)).scalar()

            starting_date = metrics_starting_date_from_days(latest_completed, earliest_incomplete)
            if starting_date is not None:
                return starting_date

        # 2. No metrics records. Return the date of the first recorded session.
        first_session, _ = await self.get_sessions(sort_by="created_at", sort_order="asc", limit=1, deserialize=False)

        first_session_date = first_session[0]["created_at"] if first_session else None  # type: ignore[index]

        # 3. No metrics records and no sessions records. Return None.
        if first_session_date is None:
            return None

        return datetime.fromtimestamp(first_session_date, tz=timezone.utc).date()

    async def calculate_metrics(self) -> Optional[list[dict]]:
        """Calculate metrics for all dates without complete metrics.

        Returns:
            Optional[list[dict]]: The calculated metrics.

        Raises:
            Exception: If an error occurs during metrics calculation.
        """
        try:
            # Stamp first so failed runs are throttled too instead of retried on every read
            self._metrics_refreshed_at = time.time()

            table = await self._get_table(table_type="metrics", create_table_if_not_found=True)
            if table is None:
                return None

            starting_date = await self._get_metrics_calculation_starting_date(table)

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

            sessions = await self._get_all_sessions_for_metrics_calculation(
                start_timestamp=start_timestamp, end_timestamp=end_timestamp
            )

            all_sessions_data = fetch_all_sessions_data(
                sessions=sessions, dates_to_process=dates_to_process, start_timestamp=start_timestamp
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

                # One record per distinct user_id, plus an empty-string bucket for unowned sessions
                metrics_records.extend(calculate_date_metrics(date_to_process, sessions_for_date))

            if metrics_records:
                async with self.async_session_factory() as sess, sess.begin():
                    results = await abulk_upsert_metrics(session=sess, table=table, metrics_records=metrics_records)

            log_debug("Updated metrics calculations")

            return results

        except Exception as e:
            log_error(f"Exception refreshing metrics: {str(e)}")
            raise e

    async def get_metrics(
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
            user_id (Optional[str]): If set, only return this user's metrics.

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
                    await self.calculate_metrics()
                except Exception as e:
                    log_warning(f"Could not refresh metrics before reading them: {str(e)}")

            table = await self._get_table(table_type="metrics", create_table_if_not_found=True)
            if table is None:
                return [], None

            async with self.async_session_factory() as sess, sess.begin():
                stmt = select(table)
                if starting_date:
                    stmt = stmt.where(table.c.date >= starting_date)
                if ending_date:
                    stmt = stmt.where(table.c.date <= ending_date)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                result = await sess.execute(stmt)
                records = result.fetchall()
                if not records:
                    return [], None

                # Get the latest updated_at
                latest_stmt = select(func.max(table.c.updated_at))
                if user_id is not None:
                    latest_stmt = latest_stmt.where(table.c.user_id == user_id)
                latest_result = await sess.execute(latest_stmt)
                latest_updated_at = latest_result.scalar()

            # Unowned rows use an empty-string user_id, map it back to None
            rows: List[dict] = []
            for row in records:
                row_dict = dict(row._mapping)
                if row_dict.get("user_id") == "":
                    row_dict["user_id"] = None
                rows.append(row_dict)
            return rows, latest_updated_at

        except Exception as e:
            log_warning(f"Exception getting metrics: {str(e)}")
            return [], None

    # -- Knowledge methods --
    async def delete_knowledge_content(self, id: str, user_id: Optional[str] = None):
        """Delete a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to delete.
            user_id (Optional[str]): If set, only delete the row if owned by this user.
        """
        table = await self._get_table(table_type="knowledge")
        if table is None:
            return

        try:
            async with self.async_session_factory() as sess, sess.begin():
                stmt = table.delete().where(table.c.id == id)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                await sess.execute(stmt)

        except Exception as e:
            log_error(f"Exception deleting knowledge content: {str(e)}")

    async def get_knowledge_content(self, id: str, user_id: Optional[str] = None) -> Optional[KnowledgeRow]:
        """Get a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to get.
            user_id (Optional[str]): If set, only return the row if owned by this user or unowned.

        Returns:
            Optional[KnowledgeRow]: The knowledge row, or None if it doesn't exist.
        """
        table = await self._get_table(table_type="knowledge")
        if table is None:
            return None

        try:
            async with self.async_session_factory() as sess, sess.begin():
                stmt = select(table).where(table.c.id == id)
                if user_id is not None:
                    stmt = stmt.where(or_(table.c.user_id == user_id, table.c.user_id.is_(None)))
                result = await sess.execute(stmt)
                row = result.fetchone()
                if row is None:
                    return None

                return KnowledgeRow.model_validate(row._mapping)

        except Exception as e:
            log_error(f"Exception getting knowledge content: {str(e)}")
            return None

    async def get_knowledge_contents(
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
            user_id (Optional[str]): If set, only return rows owned by this user or unowned.

        Returns:
            List[KnowledgeRow]: The knowledge contents.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        table = await self._get_table(table_type="knowledge")
        if table is None:
            return [], 0

        validate_pagination(limit, page)
        try:
            async with self.async_session_factory() as sess, sess.begin():
                stmt = select(table)

                # Apply linked_to filter if provided
                if linked_to is not None:
                    stmt = stmt.where(table.c.linked_to == linked_to)

                # Apply owner scoping if provided
                if user_id is not None:
                    stmt = stmt.where(or_(table.c.user_id == user_id, table.c.user_id.is_(None)))

                # Apply sorting
                stmt = apply_sorting(stmt, table, sort_by, sort_order)

                # Get total count before applying limit and pagination
                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = await sess.scalar(count_stmt) or 0

                # Apply pagination after count
                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset((page - 1) * limit)

                result = await sess.execute(stmt)
                records = result.fetchall()
                return [KnowledgeRow.model_validate(record._mapping) for record in records], total_count

        except Exception as e:
            log_error(f"Exception getting knowledge contents: {str(e)}")
            return [], 0

    async def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        """Upsert knowledge content in the database.

        Args:
            knowledge_row (KnowledgeRow): The knowledge row to upsert.

        Returns:
            Optional[KnowledgeRow]: The upserted knowledge row, or None if the operation fails.
        """
        try:
            table = await self._get_table(table_type="knowledge", create_table_if_not_found=True)
            if table is None:
                return None
            async with self.async_session_factory() as sess, sess.begin():
                # A scoped write must not overwrite a row it does not own
                if knowledge_row.user_id is not None and knowledge_row.id:
                    stored = (
                        await sess.execute(select(table.c.user_id).where(table.c.id == knowledge_row.id))
                    ).fetchone()
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
                # String fields that need sanitization
                string_fields = {"name", "description", "type", "status", "status_message", "external_id", "linked_to"}

                for model_field, table_column in field_mapping.items():
                    if table_column in table_columns:
                        value = getattr(knowledge_row, model_field, None)
                        if value is not None:
                            # Sanitize string fields to remove null bytes
                            if table_column in string_fields and isinstance(value, str):
                                value = sanitize_postgres_string(value)
                            # Sanitize metadata dict if present
                            elif table_column == "metadata" and isinstance(value, dict):
                                value = sanitize_postgres_strings(value)
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
                        stmt = postgresql.insert(table).values(insert_data)
                        await sess.execute(stmt)
                    else:
                        # If we have no data at all, this is an error
                        log_error("No valid fields found for knowledge row upsert")
                        return None
                else:
                    # Normal upsert with conflict resolution
                    stmt = (
                        postgresql.insert(table)
                        .values(insert_data)
                        .on_conflict_do_update(index_elements=["id"], set_=update_fields)
                    )
                    await sess.execute(stmt)

            log_debug(f"Upserted knowledge row with id '{knowledge_row.id}'")

            return knowledge_row

        except Exception as e:
            log_error(f"Error upserting knowledge row: {str(e)}")
            raise e

    # -- Eval methods --
    async def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        """Create an EvalRunRecord in the database.

        Args:
            eval_run (EvalRunRecord): The eval run to create.

        Returns:
            Optional[EvalRunRecord]: The created eval run, or None if the operation fails.

        Raises:
            Exception: If an error occurs during creation.
        """
        try:
            table = await self._get_table(table_type="evals", create_table_if_not_found=True)
            if table is None:
                return None

            async with self.async_session_factory() as sess, sess.begin():
                current_time = int(time.time())
                eval_data = eval_run.model_dump()
                # Sanitize string fields in eval_run
                if eval_data.get("name"):
                    eval_data["name"] = sanitize_postgres_string(eval_data["name"])
                if eval_data.get("evaluated_component_name"):
                    eval_data["evaluated_component_name"] = sanitize_postgres_string(
                        eval_data["evaluated_component_name"]
                    )
                # Sanitize nested dicts/JSON fields
                if eval_data.get("eval_data"):
                    eval_data["eval_data"] = sanitize_postgres_strings(eval_data["eval_data"])
                if eval_data.get("eval_input"):
                    eval_data["eval_input"] = sanitize_postgres_strings(eval_data["eval_input"])

                stmt = postgresql.insert(table).values(
                    {"created_at": current_time, "updated_at": current_time, **eval_data}
                )
                await sess.execute(stmt)

            log_debug(f"Created eval run with id '{eval_run.run_id}'")

            return eval_run

        except Exception as e:
            log_error(f"Error creating eval run: {str(e)}")
            return None

    async def delete_eval_run(self, eval_run_id: str) -> None:
        """Delete an eval run from the database.

        Args:
            eval_run_id (str): The ID of the eval run to delete.
        """
        try:
            table = await self._get_table(table_type="evals")
            if table is None:
                return

            async with self.async_session_factory() as sess, sess.begin():
                stmt = table.delete().where(table.c.run_id == eval_run_id)
                result = await sess.execute(stmt)

                if result.rowcount == 0:  # type: ignore
                    log_warning(f"No eval run found with ID: {eval_run_id}")
                else:
                    log_debug(f"Deleted eval run with ID: {eval_run_id}")

        except Exception as e:
            log_error(f"Error deleting eval run {eval_run_id}: {str(e)}")

    async def delete_eval_runs(self, eval_run_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete multiple eval runs from the database.

        Args:
            eval_run_ids (List[str]): List of eval run IDs to delete.
            user_id (Optional[str]): If set, only delete runs owned by this user.
        """
        try:
            table = await self._get_table(table_type="evals")
            if table is None:
                return

            async with self.async_session_factory() as sess, sess.begin():
                stmt = table.delete().where(table.c.run_id.in_(eval_run_ids))
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                result = await sess.execute(stmt)

                if result.rowcount == 0:  # type: ignore
                    log_warning(f"No eval runs found with IDs: {eval_run_ids}")
                else:
                    log_debug(f"Deleted {result.rowcount} eval runs")  # type: ignore

        except Exception as e:
            log_error(f"Error deleting eval runs {eval_run_ids}: {str(e)}")

    async def get_eval_run(
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
            table = await self._get_table(table_type="evals")
            if table is None:
                return None

            async with self.async_session_factory() as sess, sess.begin():
                stmt = select(table).where(table.c.run_id == eval_run_id)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                result = await sess.execute(stmt)
                row = result.fetchone()
                if row is None:
                    return None

                eval_run_raw = dict(row._mapping)
                if not deserialize:
                    return eval_run_raw

                return EvalRunRecord.model_validate(eval_run_raw)

        except Exception as e:
            log_error(f"Exception getting eval run {eval_run_id}: {str(e)}")
            return None

    async def get_eval_runs(
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
            eval_type (Optional[List[EvalType]]): The type(s) of eval to filter by.
            filter_type (Optional[EvalFilterType]): Filter by component type (agent, team, workflow).
            deserialize (Optional[bool]): Whether to serialize the eval runs. Defaults to True.
            user_id (Optional[str]): If set, only return runs owned by this user.

        Returns:
            Union[List[EvalRunRecord], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of EvalRunRecord objects
                - When deserialize=False: List of dictionaries

        Raises:
            Exception: If an error occurs during retrieval.
        """
        validate_pagination(limit, page)
        try:
            table = await self._get_table(table_type="evals")
            if table is None:
                return [] if deserialize else ([], 0)

            async with self.async_session_factory() as sess, sess.begin():
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
                total_count = await sess.scalar(count_stmt) or 0

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

                result = await sess.execute(stmt)
                records = result.fetchall()
                if not records:
                    return [] if deserialize else ([], 0)

                eval_runs_raw = [dict(row._mapping) for row in records]
                if not deserialize:
                    return eval_runs_raw, total_count

                return [EvalRunRecord.model_validate(row) for row in eval_runs_raw]

        except Exception as e:
            log_error(f"Exception getting eval runs: {str(e)}")
            return [] if deserialize else ([], 0)

    async def rename_eval_run(
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
            table = await self._get_table(table_type="evals")
            if table is None:
                return None
            async with self.async_session_factory() as sess, sess.begin():
                # Sanitize string field to remove null bytes
                sanitized_name = sanitize_postgres_string(name)
                stmt = (
                    table.update()
                    .where(table.c.run_id == eval_run_id)
                    .values(name=sanitized_name, updated_at=int(time.time()))
                )
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                await sess.execute(stmt)

            eval_run_raw = await self.get_eval_run(eval_run_id=eval_run_id, deserialize=deserialize, user_id=user_id)
            if not eval_run_raw or not deserialize:
                return eval_run_raw

            return EvalRunRecord.model_validate(eval_run_raw)

        except Exception as e:
            log_error(f"Error upserting eval run name {eval_run_id}: {str(e)}")
            return None

    async def update_eval_run_user_id(self, eval_run_id: str, user_id: str) -> None:
        """Set the owner (user_id) on an existing eval run.

        Args:
            eval_run_id (str): The ID of the eval run to update.
            user_id (str): The owner to set.
        """
        try:
            table = await self._get_table(table_type="evals")
            if table is None:
                return

            async with self.async_session_factory() as sess, sess.begin():
                stmt = table.update().where(table.c.run_id == eval_run_id).values(user_id=user_id)
                await sess.execute(stmt)

        except Exception as e:
            log_error(f"Error setting owner on eval run {eval_run_id}: {str(e)}")
            raise e

    # -- Migrations --

    async def migrate_table_from_v1_to_v2(self, v1_db_schema: str, v1_table_name: str, v1_table_type: str):
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
                await self.upsert_session(session)
            log_info(f"Migrated {len(sessions)} Agent sessions to table: {self.session_table}")

        elif v1_table_type == "team_sessions":
            for session in sessions:
                await self.upsert_session(session)
            log_info(f"Migrated {len(sessions)} Team sessions to table: {self.session_table}")

        elif v1_table_type == "workflow_sessions":
            for session in sessions:
                await self.upsert_session(session)
            log_info(f"Migrated {len(sessions)} Workflow sessions to table: {self.session_table}")

        elif v1_table_type == "memories":
            for memory in memories:
                await self.upsert_user_memory(memory)
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

    async def upsert_trace(self, trace: "Trace") -> None:
        """Create or update a single trace record in the database.

        Uses INSERT ... ON CONFLICT DO UPDATE (upsert) to handle concurrent inserts
        atomically and avoid race conditions.

        Args:
            trace: The Trace object to store (one per trace_id).
        """
        try:
            table = await self._get_table(table_type="traces", create_table_if_not_found=True)
            if table is None:
                return

            trace_dict = trace.to_dict()
            trace_dict.pop("total_spans", None)
            trace_dict.pop("error_count", None)
            # Sanitize string fields and nested JSON structures
            if trace_dict.get("name"):
                trace_dict["name"] = sanitize_postgres_string(trace_dict["name"])
            if trace_dict.get("status"):
                trace_dict["status"] = sanitize_postgres_string(trace_dict["status"])
            # Sanitize any nested dict/JSON fields
            trace_dict = cast(Dict[str, Any], sanitize_postgres_strings(trace_dict))

            async with self.async_session_factory() as sess, sess.begin():
                # Use upsert to handle concurrent inserts atomically
                # On conflict, update fields while preserving existing non-null context values
                # and keeping the earliest start_time
                insert_stmt = postgresql.insert(table).values(trace_dict)

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
                # Use LEAST for start_time, GREATEST for end_time to capture full trace duration
                # Use COALESCE to preserve existing non-null context values
                upsert_stmt = insert_stmt.on_conflict_do_update(
                    index_elements=["trace_id"],
                    set_={
                        "end_time": func.greatest(table.c.end_time, insert_stmt.excluded.end_time),
                        "start_time": func.least(table.c.start_time, insert_stmt.excluded.start_time),
                        "duration_ms": func.extract(
                            "epoch",
                            func.cast(
                                func.greatest(table.c.end_time, insert_stmt.excluded.end_time),
                                TIMESTAMP(timezone=True),
                            )
                            - func.cast(
                                func.least(table.c.start_time, insert_stmt.excluded.start_time),
                                TIMESTAMP(timezone=True),
                            ),
                        )
                        * 1000,
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
                await sess.execute(upsert_stmt)

        except Exception as e:
            log_error(f"Error creating trace: {str(e)}")
            # Don't raise - tracing should not break the main application flow

    async def get_trace(
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

            table = await self._get_table(table_type="traces")
            if table is None:
                return None

            # Get spans table for JOIN
            spans_table = await self._get_table(table_type="spans")

            async with self.async_session_factory() as sess:
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
                result = await sess.execute(stmt)
                row = result.fetchone()

                if row:
                    return Trace.from_dict(dict(row._mapping))
                return None

        except Exception as e:
            log_error(f"Error getting trace: {str(e)}")
            return None

    async def get_traces(
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
            from agno.tracing.schemas import Trace

            table = await self._get_table(table_type="traces")
            if table is None:
                return [], 0

            # Get spans table for JOIN
            spans_table = await self._get_table(table_type="spans")

            async with self.async_session_factory() as sess:
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
                total_count = await sess.scalar(count_stmt) or 0
                log_debug(f"Total matching traces: {total_count}")

                # Apply pagination
                offset = (page - 1) * limit if page and limit else 0
                paginated_stmt = base_stmt.order_by(table.c.start_time.desc()).limit(limit).offset(offset)

                result = await sess.execute(paginated_stmt)
                results = result.fetchall()
                log_debug(f"Returning page {page} with {len(results)} traces")

                traces = [Trace.from_dict(dict(row._mapping)) for row in results]
                return traces, total_count

        except Exception as e:
            log_error(f"Error getting traces: {str(e)}")
            return [], 0

    async def get_trace_stats(
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
                name, with the same aggregates.

        Returns:
            tuple[List[Dict], int]: Tuple of (list of stats dicts, total count).
                With group_by="session", each dict contains: session_id, user_id,
                agent_id, team_id, workflow_id, total_traces, first_trace_at, last_trace_at.
                With a component grouping, each dict contains: <group>_id, total_traces,
                total_sessions, avg_duration_ms, p95_duration_ms, max_duration_ms,
                error_traces (traces with status ERROR), first_trace_at, last_trace_at.
                With group_by="endpoint", the grouping key is name instead of <group>_id.
        """
        if group_by not in ("session", "agent", "team", "workflow", "endpoint"):
            raise ValueError(f"Invalid group_by value: {group_by!r}. Allowed: session, agent, team, workflow, endpoint")

        try:
            table = await self._get_table(table_type="traces")
            if table is None:
                return [], 0

            async with self.async_session_factory() as sess:
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
                            func.percentile_cont(0.95).within_group(table.c.duration_ms).label("p95_duration_ms"),
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
                total_count = await sess.scalar(count_stmt) or 0

                # Apply pagination and ordering
                offset = (page - 1) * limit if page and limit else 0
                order_by: List[Any] = (
                    [func.max(table.c.created_at).desc()]
                    if group_by == "session"
                    else [func.count(table.c.trace_id).desc(), group_column]
                )
                paginated_stmt = base_stmt.order_by(*order_by).limit(limit).offset(offset)

                result = await sess.execute(paginated_stmt)
                results = result.fetchall()

                # Convert to list of dicts with datetime objects
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

    # --- Spans ---
    async def create_span(self, span: "Span") -> None:
        """Create a single span in the database.

        Args:
            span: The Span object to store.
        """
        try:
            table = await self._get_table(table_type="spans", create_table_if_not_found=True)
            if table is None:
                return

            async with self.async_session_factory() as sess, sess.begin():
                span_dict = span.to_dict()
                # Sanitize string fields and nested JSON structures
                if span_dict.get("name"):
                    span_dict["name"] = sanitize_postgres_string(span_dict["name"])
                if span_dict.get("status_code"):
                    span_dict["status_code"] = sanitize_postgres_string(span_dict["status_code"])
                # Sanitize any nested dict/JSON fields
                span_dict = cast(Dict[str, Any], sanitize_postgres_strings(span_dict))
                stmt = postgresql.insert(table).values(span_dict)
                await sess.execute(stmt)

        except Exception as e:
            log_error(f"Error creating span: {str(e)}")

    async def create_spans(self, spans: List) -> None:
        """Create multiple spans in the database as a batch.

        Args:
            spans: List of Span objects to store.
        """
        if not spans:
            return

        try:
            table = await self._get_table(table_type="spans", create_table_if_not_found=True)
            if table is None:
                return

            async with self.async_session_factory() as sess, sess.begin():
                for span in spans:
                    span_dict = span.to_dict()
                    # Sanitize string fields and nested JSON structures
                    if span_dict.get("name"):
                        span_dict["name"] = sanitize_postgres_string(span_dict["name"])
                    if span_dict.get("status_code"):
                        span_dict["status_code"] = sanitize_postgres_string(span_dict["status_code"])
                    # Sanitize any nested dict/JSON fields
                    span_dict = sanitize_postgres_strings(span_dict)
                    stmt = postgresql.insert(table).values(span_dict)
                    await sess.execute(stmt)

        except Exception as e:
            log_error(f"Error creating spans batch: {str(e)}")

    async def get_span(self, span_id: str):
        """Get a single span by its span_id.

        Args:
            span_id: The unique span identifier.

        Returns:
            Optional[Span]: The span if found, None otherwise.
        """
        try:
            from agno.tracing.schemas import Span

            table = await self._get_table(table_type="spans")
            if table is None:
                return None

            async with self.async_session_factory() as sess:
                stmt = select(table).where(table.c.span_id == span_id)
                result = await sess.execute(stmt)
                row = result.fetchone()
                if row:
                    return Span.from_dict(dict(row._mapping))
                return None

        except Exception as e:
            log_error(f"Error getting span: {str(e)}")
            return None

    async def get_spans(
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

            table = await self._get_table(table_type="spans")
            if table is None:
                return []

            async with self.async_session_factory() as sess:
                stmt = select(table)

                # Apply filters
                if trace_id:
                    stmt = stmt.where(table.c.trace_id == trace_id)
                if parent_span_id:
                    stmt = stmt.where(table.c.parent_span_id == parent_span_id)

                if limit:
                    stmt = stmt.limit(limit)

                result = await sess.execute(stmt)
                results = result.fetchall()
                return [Span.from_dict(dict(row._mapping)) for row in results]

        except Exception as e:
            log_error(f"Error getting spans: {str(e)}")
            return []

    async def get_span_stats(
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
                p95_duration_ms, max_duration_ms, error_count or last_called_at.
            sort_order: "asc" or "desc".

        Returns:
            Tuple[List[Dict], int]: Tuple of (list of stats dicts, total count of groups).
                Each dict contains: name, span_type, total_calls, avg_duration_ms,
                p95_duration_ms, max_duration_ms, error_count, last_called_at (datetime).
        """
        try:
            table = await self._get_table(table_type="spans")
            if table is None:
                log_debug("Spans table not found")
                return [], 0

            span_type_col = table.c.attributes["openinference.span.kind"].astext

            total_calls_col = func.count(table.c.span_id)
            avg_duration_col = func.avg(table.c.duration_ms)
            p95_duration_col = func.percentile_cont(0.95).within_group(table.c.duration_ms)
            max_duration_col = func.max(table.c.duration_ms)
            error_count_col = func.sum(case((table.c.status_code == "ERROR", 1), else_=0))
            last_called_at_col = func.max(table.c.start_time)

            async with self.async_session_factory() as sess:
                stmt = select(
                    table.c.name,
                    span_type_col.label("span_type"),
                    total_calls_col.label("total_calls"),
                    avg_duration_col.label("avg_duration_ms"),
                    p95_duration_col.label("p95_duration_ms"),
                    max_duration_col.label("max_duration_ms"),
                    error_count_col.label("error_count"),
                    last_called_at_col.label("last_called_at"),
                ).group_by(table.c.name, span_type_col)

                # Component filters live on the traces table
                if agent_id or team_id or workflow_id:
                    traces_table = await self._get_table(table_type="traces")
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
                total_count = await sess.scalar(count_stmt) or 0

                sort_columns = {
                    "total_calls": total_calls_col,
                    "avg_duration_ms": avg_duration_col,
                    "p95_duration_ms": p95_duration_col,
                    "max_duration_ms": max_duration_col,
                    "error_count": error_count_col,
                    "last_called_at": last_called_at_col,
                }
                sort_col = sort_columns.get(sort_by)
                if sort_col is None:
                    log_debug(f"Invalid sort field: '{sort_by}'. Sorting by total_calls.")
                    sort_col = total_calls_col
                order_by = sort_col.asc() if sort_order == "asc" else sort_col.desc()

                offset = (page - 1) * limit if page and limit else 0
                paginated_stmt = stmt.order_by(order_by, table.c.name, span_type_col).limit(limit).offset(offset)

                result = await sess.execute(paginated_stmt)
                results = result.fetchall()

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
                            "p95_duration_ms": round(float(row.p95_duration_ms), 1)
                            if row.p95_duration_ms is not None
                            else None,
                            "max_duration_ms": row.max_duration_ms,
                            "error_count": row.error_count,
                            "last_called_at": last_called_at,
                        }
                    )

                return stats_list, total_count

        except Exception as e:
            log_error(f"Error getting span stats: {str(e)}")
            return [], 0

    # -- Learning methods --
    async def get_learning(
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
        """Async retrieve a learning record.

        Args:
            learning_type: Type of learning ('user_profile', 'session_context', etc.)
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            session_id: Filter by session ID.
            namespace: Filter by namespace ('user', 'global', or custom).
            entity_id: Filter by entity ID (for entity-specific learnings).
            entity_type: Filter by entity type ('person', 'company', etc.).

        Returns:
            Dict with 'content' key containing the learning data, or None.
        """
        try:
            table = await self._get_table(table_type="learnings")
            if table is None:
                return None

            async with self.async_session_factory() as sess:
                stmt = select(table).where(table.c.learning_type == learning_type)

                if user_id is not None:
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

                result = await sess.execute(stmt)
                row = result.fetchone()
                if row is None:
                    return None

                row_dict = dict(row._mapping)
                return {"content": row_dict.get("content")}

        except Exception as e:
            log_debug(f"Error retrieving learning: {e}")
            return None

    async def upsert_learning(
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
        """Async insert or update a learning record.

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
            table = await self._get_table(table_type="learnings", create_table_if_not_found=True)
            if table is None:
                return

            current_time = int(time.time())

            async with self.async_session_factory() as sess, sess.begin():
                stmt = postgresql.insert(table).values(
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
                await sess.execute(stmt)

            log_debug(f"Upserted learning: {id}")

        except Exception as e:
            log_debug(f"Error upserting learning: {e}")

    async def delete_learning(self, id: str) -> bool:
        """Async delete a learning record.

        Args:
            id: The learning ID to delete.

        Returns:
            True if deleted, False otherwise.
        """
        try:
            table = await self._get_table(table_type="learnings")
            if table is None:
                return False

            async with self.async_session_factory() as sess, sess.begin():
                stmt = table.delete().where(table.c.learning_id == id)
                result = await sess.execute(stmt)
                return getattr(result, "rowcount", 0) > 0

        except Exception as e:
            log_debug(f"Error deleting learning: {e}")
            return False

    async def update_learning(
        self, id: str, content: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        try:
            table = await self._get_table(table_type="learnings")
            if table is None:
                return False

            async with self.async_session_factory() as sess, sess.begin():
                stmt = (
                    table.update()
                    .where(table.c.learning_id == id)
                    .values(content=content, metadata=metadata, updated_at=int(time.time()))
                )
                result = await sess.execute(stmt)
                return getattr(result, "rowcount", 0) > 0

        except Exception as e:
            log_error(f"Error updating learning: {e}")
            raise e

    async def delete_user_learnings(self, user_id: str, learning_type: Optional[str] = None) -> int:
        try:
            table = await self._get_table(table_type="learnings")
            if table is None:
                return 0

            async with self.async_session_factory() as sess, sess.begin():
                stmt = table.delete().where(table.c.user_id == user_id)
                if learning_type is not None:
                    stmt = stmt.where(table.c.learning_type == learning_type)
                result = await sess.execute(stmt)
                return getattr(result, "rowcount", 0) or 0

        except Exception as e:
            log_error(f"Error deleting user learnings: {e}")
            raise e

    async def get_learnings(
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
        """Async get multiple learning records.

        Args:
            learning_type: Filter by learning type.
            user_id: Filter by user ID.
            agent_id: Filter by agent ID.
            team_id: Filter by team ID.
            session_id: Filter by session ID.
            namespace: Filter by namespace ('user', 'global', or custom).
            entity_id: Filter by entity ID (for entity-specific learnings).
            entity_type: Filter by entity type ('person', 'company', etc.).
            limit: Maximum number of records to return.

        Returns:
            List of learning records.
        """
        try:
            table = await self._get_table(table_type="learnings")
            if table is None:
                return []

            async with self.async_session_factory() as sess:
                stmt = select(table)

                if learning_type is not None:
                    stmt = stmt.where(table.c.learning_type == learning_type)
                if user_id is not None:
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

                stmt = stmt.order_by(table.c.updated_at.desc())

                if limit is not None:
                    stmt = stmt.limit(limit)

                result = await sess.execute(stmt)
                rows = result.fetchall()
                return [dict(row._mapping) for row in rows]

        except Exception as e:
            log_debug(f"Error getting learnings: {e}")
            return []

    async def search_learnings(
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
        """Async search learning records by text query. See AsyncBaseDb.search_learnings.

        The content column is JSONB, which has no ILIKE operator - it is cast
        to TEXT first (the same shape get_user_memories uses for
        search_content). The query matches in both its space and underscore
        forms. Errors are raised, never swallowed.
        """
        try:
            table = await self._get_table(table_type="learnings")
            if table is None:
                return []

            patterns = learning_search_patterns(query)
            if not patterns:
                return []

            async with self.async_session_factory() as sess:
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

                content_text = func.cast(table.c.content, postgresql.TEXT)
                stmt = stmt.where(or_(*[content_text.ilike(pattern, escape="\\") for pattern in patterns]))

                stmt = stmt.order_by(table.c.updated_at.desc().nulls_last())
                if limit is not None:
                    stmt = stmt.limit(limit)

                result = await sess.execute(stmt)
                rows = result.fetchall()
                return [dict(row._mapping) for row in rows]

        except Exception as e:
            log_error(f"Error searching learnings: {e}")
            raise e

    async def get_learning_by_id(self, id: str) -> Optional[Dict[str, Any]]:
        try:
            table = await self._get_table(table_type="learnings")
            if table is None:
                return None
            async with self.async_session_factory() as sess:
                result = await sess.execute(select(table).where(table.c.learning_id == id))
                row = result.fetchone()
                return dict(row._mapping) if row else None
        except Exception as e:
            log_error(f"Error getting learning by id: {e}")
            raise e

    async def list_learnings(
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
            table = await self._get_table(table_type="learnings")
            if table is None:
                return [], 0

            async with self.async_session_factory() as sess:
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
                count_result = await sess.execute(count_stmt)
                total_count = count_result.scalar() or 0

                stmt = apply_sorting(stmt, table, sort_by or "updated_at", sort_order or "desc")
                stmt = stmt.limit(limit).offset((page - 1) * limit)
                result = await sess.execute(stmt)
                rows = result.fetchall()
                return [dict(row._mapping) for row in rows], int(total_count)

        except Exception as e:
            log_error(f"Error listing learnings: {e}")
            raise e

    async def get_learnings_user_stats(
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
            table = await self._get_table(table_type="learnings")
            if table is None:
                return [], 0

            async with self.async_session_factory() as sess:
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
                count_result = await sess.execute(count_stmt)
                total_count = count_result.scalar() or 0

                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset((page - 1) * limit)

                result = await sess.execute(stmt)
                rows = result.fetchall()
                return [
                    {
                        "user_id": row.user_id,
                        "last_learning_updated_at": row.last_learning_updated_at,
                    }
                    for row in rows
                ], int(total_count)

        except Exception as e:
            log_error(f"Error getting learning user stats: {e}")
            raise e

    # --- Components (Not supported for async) ---
    # The plain-def stubs raising NotImplementedError are inherited from AsyncBaseDb.

    # -- Schedule methods --
    # ``claim_due_schedule`` / ``release_schedule`` take no user_id: the poller fires schedules for all users.
    async def get_schedule(self, schedule_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        try:
            table = await self._get_table(table_type="schedules")
            if table is None:
                return None
            async with self.async_session_factory() as sess:
                stmt = select(table).where(table.c.id == schedule_id)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                result = await sess.execute(stmt)
                row = result.fetchone()
                return dict(row._mapping) if row else None
        except Exception as e:
            log_debug(f"Error getting schedule: {e}")
            return None

    async def get_schedule_by_name(self, name: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        try:
            table = await self._get_table(table_type="schedules")
            if table is None:
                return None
            async with self.async_session_factory() as sess:
                stmt = select(table).where(table.c.name == name)
                # Names are unique per owner: ``None`` addresses the unowned bucket,
                # never another owner's schedule of the same name.
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                else:
                    stmt = stmt.where(table.c.user_id.is_(None))
                result = await sess.execute(stmt)
                row = result.fetchone()
                return dict(row._mapping) if row else None
        except Exception as e:
            log_debug(f"Error getting schedule by name: {e}")
            return None

    async def get_schedules(
        self,
        enabled: Optional[bool] = None,
        limit: int = 100,
        page: int = 1,
        user_id: Optional[str] = None,
        raise_on_error: bool = False,
    ) -> Tuple[List[Dict[str, Any]], int]:
        try:
            table = await self._get_table(table_type="schedules")
            if table is None:
                # _get_table also returns None on connection errors (ais_table_available
                # swallows them), so strict callers must not see this as an empty catalog
                if raise_on_error:
                    raise RuntimeError("schedules table unavailable (database error or table never created)")
                return [], 0
            async with self.async_session_factory() as sess:
                # Build base query with filters
                base_query = select(table)
                if enabled is not None:
                    base_query = base_query.where(table.c.enabled == enabled)
                if user_id is not None:
                    base_query = base_query.where(table.c.user_id == user_id)

                # Get total count
                count_stmt = select(func.count()).select_from(base_query.alias())
                count_result = await sess.execute(count_stmt)
                total_count = count_result.scalar() or 0

                # Calculate offset from page
                offset = (page - 1) * limit

                # Get paginated results (id is a unique tiebreaker so offset pages do not overlap
                # or skip rows when many schedules share a created_at second)
                stmt = base_query.order_by(table.c.created_at.desc(), table.c.id.desc()).limit(limit).offset(offset)
                result = await sess.execute(stmt)
                return [dict(row._mapping) for row in result.fetchall()], total_count
        except Exception as e:
            log_debug(f"Error listing schedules: {e}")
            if raise_on_error:
                raise
            return [], 0

    async def create_schedule(self, schedule_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            table = await self._get_table(table_type="schedules", create_table_if_not_found=True)
            if table is None:
                raise RuntimeError("Failed to get or create schedules table")
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    await sess.execute(table.insert().values(**schedule_data))
            return schedule_data
        except Exception as e:
            log_error(f"Error creating schedule: {str(e)}")
            raise

    async def update_schedule(
        self, schedule_id: str, user_id: Optional[str] = None, **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        from agno.db.schemas.scheduler import validate_schedule_update

        validate_schedule_update(kwargs)
        if kwargs.get("enabled") is True:
            # A system-set disabled_reason describes why the row was off;
            # turning it on retires the explanation.
            kwargs.setdefault("disabled_reason", None)
        try:
            table = await self._get_table(table_type="schedules")
            if table is None:
                return None
            kwargs["updated_at"] = int(time.time())
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    stmt = table.update().where(table.c.id == schedule_id)
                    if user_id is not None:
                        stmt = stmt.where(table.c.user_id == user_id)
                    await sess.execute(stmt.values(**kwargs))
            return await self.get_schedule(schedule_id, user_id=user_id)
        except Exception as e:
            # Let a unique-violation (rename onto a name taken in the same owner bucket)
            # propagate so the router maps it to 409
            from agno.db.utils import is_unique_violation

            if is_unique_violation(e):
                raise
            log_debug(f"Error updating schedule: {e}")
            return None

    async def delete_schedule(self, schedule_id: str, user_id: Optional[str] = None) -> bool:
        try:
            table = await self._get_table(table_type="schedules")
            if table is None:
                return False
            runs_table = await self._get_table(table_type="schedule_runs")
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    if runs_table is not None:
                        # Mirror the owner filter on the cascade delete of schedule runs
                        runs_delete = runs_table.delete().where(runs_table.c.schedule_id == schedule_id)
                        if user_id is not None:
                            runs_delete = runs_delete.where(runs_table.c.user_id == user_id)
                        await sess.execute(runs_delete)
                    delete_stmt = table.delete().where(table.c.id == schedule_id)
                    if user_id is not None:
                        delete_stmt = delete_stmt.where(table.c.user_id == user_id)
                    result = await sess.execute(delete_stmt)
                    return result.rowcount > 0  # type: ignore[attr-defined]
        except Exception as e:
            log_debug(f"Error deleting schedule: {e}")
            return False

    async def disable_schedules_for_target(
        self,
        target_type: str,
        target_id: str,
        reason: Optional[str] = None,
    ) -> int:
        """Disable every enabled schedule aimed at one component; returns the count.

        Async variant of the sync adapter's primitive: matches provenance-tagged
        rows and generic rows whose endpoint is the component's run endpoint,
        across owners, and records the system reason in disabled_reason.
        """
        from agno.db.schemas.scheduler import build_run_endpoint

        try:
            table = await self._get_table(table_type="schedules")
            if table is None:
                return 0
            endpoint = build_run_endpoint(target_type, target_id)
            # RUN_ENDPOINT_RE accepts an optional trailing slash, so a stored
            # "/agents/x/runs/" is a valid run endpoint that plain equality would
            # miss - matching both spellings keeps the cascade from leaking rows.
            endpoints = [endpoint, endpoint + "/"]
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    result = await sess.execute(
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
            return int(getattr(result, "rowcount", 0) or 0)
        except Exception as e:
            log_error(f"Error disabling schedules for target: {e}")
            raise

    async def stamp_schedule_provenance(self, schedule_id: str, **provenance: Any) -> bool:
        """Write provenance columns the generic update_schedule refuses."""
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
            table = await self._get_table(table_type="schedules")
            if table is None:
                return False
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    result = await sess.execute(
                        table.update()
                        .where(table.c.id == schedule_id)
                        .values(updated_at=int(time.time()), **provenance)
                    )
            return getattr(result, "rowcount", 0) > 0
        except Exception as e:
            log_error(f"Error stamping schedule provenance: {e}")
            raise

    async def claim_due_schedule(self, worker_id: str, lock_grace_seconds: int = 300) -> Optional[Dict[str, Any]]:
        try:
            table = await self._get_table(table_type="schedules")
            if table is None:
                return None
            now = int(time.time())
            stale_lock_threshold = now - lock_grace_seconds

            async with self.async_session_factory() as sess:
                async with sess.begin():
                    subq = (
                        select(table.c.id)
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
                        .with_for_update(skip_locked=True)
                        .scalar_subquery()
                    )
                    stmt = (
                        update(table)
                        .where(table.c.id == subq)
                        .values(locked_by=worker_id, locked_at=now)
                        .returning(*table.c)
                    )
                    result = await sess.execute(stmt)
                    row = result.fetchone()
                    if row is None:
                        return None
                    return dict(row._mapping)
        except Exception as e:
            log_debug(f"Error claiming schedule: {e}")
            return None

    async def release_schedule(self, schedule_id: str, next_run_at: Optional[int] = None) -> bool:
        try:
            table = await self._get_table(table_type="schedules")
            if table is None:
                return False
            updates: Dict[str, Any] = {"locked_by": None, "locked_at": None, "updated_at": int(time.time())}
            if next_run_at is not None:
                updates["next_run_at"] = next_run_at
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    result = await sess.execute(table.update().where(table.c.id == schedule_id).values(**updates))
                    return result.rowcount > 0  # type: ignore[attr-defined]
        except Exception as e:
            log_debug(f"Error releasing schedule: {e}")
            return False

    async def create_schedule_run(self, run_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            table = await self._get_table(table_type="schedule_runs", create_table_if_not_found=True)
            if table is None:
                raise RuntimeError("Failed to get or create schedule_runs table")
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    await sess.execute(table.insert().values(**run_data))
            return run_data
        except Exception as e:
            log_error(f"Error creating schedule run: {str(e)}")
            raise

    async def update_schedule_run(self, schedule_run_id: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
        try:
            table = await self._get_table(table_type="schedule_runs")
            if table is None:
                return None
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    await sess.execute(table.update().where(table.c.id == schedule_run_id).values(**kwargs))
            return await self.get_schedule_run(schedule_run_id)
        except Exception as e:
            log_debug(f"Error updating schedule run: {e}")
            return None

    async def get_schedule_run(self, run_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        try:
            table = await self._get_table(table_type="schedule_runs")
            if table is None:
                return None
            async with self.async_session_factory() as sess:
                stmt = select(table).where(table.c.id == run_id)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                result = await sess.execute(stmt)
                row = result.fetchone()
                return dict(row._mapping) if row else None
        except Exception as e:
            log_debug(f"Error getting schedule run: {e}")
            return None

    async def get_schedule_runs(
        self,
        schedule_id: str,
        limit: int = 20,
        page: int = 1,
        user_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        try:
            table = await self._get_table(table_type="schedule_runs")
            if table is None:
                return [], 0
            async with self.async_session_factory() as sess:
                base_filter = table.c.schedule_id == schedule_id
                if user_id is not None:
                    base_filter = and_(base_filter, table.c.user_id == user_id)

                # Get total count
                count_stmt = select(func.count()).select_from(table).where(base_filter)
                count_result = await sess.execute(count_stmt)
                total_count = count_result.scalar() or 0

                # Calculate offset from page
                offset = (page - 1) * limit

                # Get paginated results
                stmt = select(table).where(base_filter).order_by(table.c.created_at.desc()).limit(limit).offset(offset)
                result = await sess.execute(stmt)
                return [dict(row._mapping) for row in result.fetchall()], total_count
        except Exception as e:
            log_debug(f"Error getting schedule runs: {e}")
            return [], 0

    # -- Job queue methods --
    #
    # Durable background job queue: one row per accepted run. Claim/lease with
    # SKIP LOCKED (modeled on claim_due_schedule), stale-lock reclaim gated on
    # the attempt budget, and terminal writes fenced on (locked_by, attempt) so
    # a zombie executor that finishes after reclaim has its write discarded.

    async def update_run_in_session(
        self,
        session_id: str,
        run_id: str,
        fields: Dict[str, Any],
        expected_attempt: Optional[int] = None,
        user_id: Optional[str] = None,
        content_if_absent: Optional[str] = None,
    ) -> "RunPersistOutcome":
        """Atomically patch fields of ONE run - ported to the denormalized
        runs table (v3.0). Same signature and typed-outcome contract as the
        session-JSON original; the implementation is now a single row-locked
        UPDATE on agno_runs instead of a session-blob rewrite, which is the
        shape the P1 fencing design always wanted.

        Attempt fencing: when ``expected_attempt`` is given, the write is
        rejected if the stored run carries a NEWER ``queue_attempt`` (a
        reclaimed job's later attempt owns the row). Terminal guard: a
        completed/cancelled run is never rewritten to a different status.
        The indexed ``status`` column is kept in sync with run_data.
        Exceptions PROPAGATE - a DB failure must never read as a
        fallback-permitting outcome.
        """
        from agno.db.utils import canonical_run_status
        from agno.run.status_persist import RunPersistOutcome

        if fields.get("status") is not None:
            # Callers pass mixed conventions ("completed", RunStatus, "RUNNING");
            # the indexed column and run_data must store the canonical uppercase
            # RunStatus.value or case-sensitive readers miss the row
            fields = {**fields, "status": canonical_run_status(fields["status"])}
        try:
            runs_table = await self._get_table(table_type="runs")
            if runs_table is None:
                return RunPersistOutcome.MISSING
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    row = (
                        await sess.execute(
                            select(runs_table.c.run_data, runs_table.c.status)
                            .where(runs_table.c.run_id == run_id)
                            .where(runs_table.c.session_id == session_id)
                            .where((runs_table.c.user_id == user_id) | (runs_table.c.user_id.is_(None)))
                            .with_for_update()
                        )
                    ).fetchone()
                    if row is None or row[0] is None:
                        return RunPersistOutcome.MISSING
                    run = dict(row[0])
                    stored_attempt = run.get("queue_attempt")
                    if (
                        expected_attempt is not None
                        and stored_attempt is not None
                        and stored_attempt > expected_attempt
                    ):
                        return RunPersistOutcome.STALE_ATTEMPT  # zombie writer fenced out
                    stored_status = str(run.get("status") or row[1] or "").lower()
                    incoming_status = str(fields.get("status") or "").lower()
                    if (
                        stored_status in ("completed", "cancelled")
                        and incoming_status
                        and incoming_status != stored_status
                    ):
                        return RunPersistOutcome.TERMINAL_REFUSED  # terminal row wins
                    run.update(fields)
                    if content_if_absent is not None and not run.get("content"):
                        run["content"] = content_if_absent
                    if expected_attempt is not None:
                        run["queue_attempt"] = expected_attempt
                    values: Dict[str, Any] = {
                        "run_data": sanitize_postgres_strings(run),
                        "updated_at": int(time.time()),
                    }
                    if fields.get("status") is not None:
                        values["status"] = fields["status"]
                    await sess.execute(update(runs_table).where(runs_table.c.run_id == run_id).values(**values))
                    return RunPersistOutcome.UPDATED
        except Exception as e:
            log_warning(f"Error updating run in runs table: {e}")
            raise

    async def append_run_to_session_if_absent(
        self,
        session_id: str,
        run_dict: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> Optional[bool]:
        """Atomically insert a run only if absent - ported to the
        denormalized runs table (v3.0): INSERT ... ON CONFLICT (run_id)
        DO NOTHING, mirroring upsert_run's row shape and run_index backfill.

        Returns True (inserted), False (already present - a concurrent
        writer won, its row wins), None (the SESSION row does not exist yet:
        the FK rejects the insert, and the caller creates the session via
        insert_session_if_absent and retries - the identical contract the
        session-JSON original exposed for a missing session row).
        """
        from sqlalchemy.exc import IntegrityError

        from agno.db.utils import build_single_run_row

        try:
            runs_table = await self._get_table(table_type="runs", create_table_if_not_found=True)
            if runs_table is None:
                return None
            row = build_single_run_row(run=run_dict, session_id=session_id, user_id=user_id, run_index=None)
            row["run_data"] = sanitize_postgres_strings(row["run_data"])
            try:
                async with self.async_session_factory() as sess:
                    async with sess.begin():
                        if row.get("run_index") is None:
                            # Same-session backfill serialization - see upsert_run
                            await sess.execute(
                                text("SELECT pg_advisory_xact_lock(hashtext('agno_run_index'), hashtext(:sid))"),
                                {"sid": session_id},
                            )
                            current_max = (
                                await sess.execute(
                                    select(func.max(runs_table.c.run_index)).where(
                                        runs_table.c.session_id == session_id
                                    )
                                )
                            ).scalar()
                            row["run_index"] = (current_max + 1) if current_max is not None else 0
                        stmt = (
                            postgresql.insert(runs_table)
                            .values(**row)
                            .on_conflict_do_nothing(index_elements=["run_id"])
                            .returning(runs_table.c.run_id)
                        )
                        inserted = (await sess.execute(stmt)).fetchone()
                        return inserted is not None
            except IntegrityError:
                # FK violation: no session row yet - caller creates it and retries
                return None
        except Exception as e:
            log_warning(f"Error appending run to runs table (caller falls back): {e}")
            return None

    async def insert_session_if_absent(self, session: Session) -> Optional[bool]:
        """Insert the session row only when no row with this session_id exists
        (INSERT ... ON CONFLICT DO NOTHING).

        The missing half of the atomic queued-run prepare: when the session
        does not exist yet, append_run_to_session_if_absent has no row to
        lock, and the legacy create-and-save fallback re-opened the unlocked
        read-check-save window (a worker completing the run inside it was
        clobbered back to PENDING). Creating the row this way instead makes
        the append primitive always applicable - no whole-session save
        remains on the prepare path.

        Returns True (inserted), False (a row already existed - the
        concurrent writer's row is authoritative), None (error - the caller
        falls back to the legacy path).
        """
        try:
            table = await self._get_table(table_type="sessions", create_table_if_not_found=True)
            if table is None:
                return None
            session_dict = session.to_dict()
            for data_field in ("agent_data", "team_data", "workflow_data", "session_data", "summary", "metadata"):
                if session_dict.get(data_field):
                    session_dict[data_field] = sanitize_postgres_strings(session_dict[data_field])
            values: Dict[str, Any] = dict(
                session_id=session_dict.get("session_id"),
                user_id=session_dict.get("user_id"),
                session_data=session_dict.get("session_data"),
                summary=session_dict.get("summary"),
                metadata=session_dict.get("metadata"),
                created_at=session_dict.get("created_at"),
                updated_at=session_dict.get("created_at"),
            )
            if isinstance(session, AgentSession):
                values.update(
                    session_type=SessionType.AGENT.value,
                    agent_id=session_dict.get("agent_id"),
                    agent_data=session_dict.get("agent_data"),
                )
            elif isinstance(session, TeamSession):
                values.update(
                    session_type=SessionType.TEAM.value,
                    team_id=session_dict.get("team_id"),
                    team_data=session_dict.get("team_data"),
                )
            elif isinstance(session, WorkflowSession):
                values.update(
                    session_type=SessionType.WORKFLOW.value,
                    workflow_id=session_dict.get("workflow_id"),
                    workflow_data=session_dict.get("workflow_data"),
                )
            else:
                return None
            async with self.async_session_factory() as sess, sess.begin():
                # RETURNING yields a row only when the insert landed; rowcount
                # is unreliable here (psycopg3 reports -1 for this statement)
                stmt = (
                    postgresql.insert(table)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=["session_id"])
                    .returning(table.c.session_id)
                )
                result = await sess.execute(stmt)
                return result.fetchone() is not None
        except Exception as e:
            log_warning(f"Error inserting session if absent (caller falls back): {e}")
            return None

    async def enqueue_job(self, job: Dict[str, Any], max_depth: int = 0) -> Dict[str, Any]:
        """Insert an accepted run job.

        Returns {"accepted": bool, "reason": None | "queue_full" | "duplicate",
        "job": row}. On an idempotency-key conflict the existing row is
        returned with reason "duplicate" (client resubmit dedup). The depth
        gate is best-effort (count + insert, not serialized) per the queue's
        portability contract.
        """
        from sqlalchemy.exc import IntegrityError

        table = await self._get_table(table_type="jobs", create_table_if_not_found=True)
        if table is None:
            raise RuntimeError("Failed to get or create job queue table")
        # Empty-string keys are "no key": the falsy pre-check would skip dedup
        # while the partial-unique index still covered '', turning the second
        # empty-header submit into an IntegrityError -> 500
        if not job.get("idempotency_key"):
            job = {**job, "idempotency_key": None}
        try:
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    # Idempotency FIRST: resubmitting an already-accepted job
                    # must return the existing run even when the queue is full
                    if job.get("idempotency_key"):
                        result = await sess.execute(
                            select(table).where(
                                table.c.idempotency_key == job["idempotency_key"],
                                table.c.user_id.is_not_distinct_from(job.get("user_id")),
                            )
                        )
                        row = result.fetchone()
                        if row is not None:
                            return {"accepted": False, "reason": "duplicate", "job": dict(row._mapping)}
                    if max_depth and max_depth > 0:
                        count_stmt = select(func.count()).select_from(table).where(table.c.status == "queued")
                        queued = (await sess.execute(count_stmt)).scalar() or 0
                        if queued >= max_depth:
                            return {"accepted": False, "reason": "queue_full", "job": None}
                    await sess.execute(table.insert().values(**job))
            return {"accepted": True, "reason": None, "job": job}
        except IntegrityError:
            # Without an idempotency key this is a primary-key collision - a
            # programming error, never a client dedup. Swallowing it as
            # "duplicate" would 202 a run that was never enqueued.
            if not job.get("idempotency_key"):
                raise
            # Race on the partial-unique idempotency index: return the winner
            async with self.async_session_factory() as sess:
                result = await sess.execute(
                    select(table).where(
                        table.c.idempotency_key == job["idempotency_key"],
                        table.c.user_id.is_not_distinct_from(job.get("user_id")),
                    )
                )
                row = result.fetchone()
                if row is not None:
                    return {"accepted": False, "reason": "duplicate", "job": dict(row._mapping)}
            raise

    async def claim_job(
        self, worker_id: str, lock_grace_seconds: int = 60, deployment_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Atomically claim the oldest executable job for this worker.

        Executable: queued, or running with a stale lock while the attempt
        budget is not exhausted (crash reclaim). Claiming increments attempt,
        which doubles as the fencing generation. Deployment affinity filters
        BOTH branches (a reclaim executes too): NULL rides anywhere, stamped
        jobs only on matching workers; deployment_id=None degenerates to
        claiming only unstamped jobs.
        """
        try:
            table = await self._get_table(table_type="jobs")
            if table is None:
                return None
            now = _db_epoch()
            stale = now - lock_grace_seconds
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    subq = (
                        select(table.c.id)
                        .where(
                            table.c.available_at <= now,
                            or_(table.c.deployment_id.is_(None), table.c.deployment_id == deployment_id),
                            or_(
                                table.c.status == "queued",
                                and_(
                                    table.c.status == "running",
                                    table.c.locked_at <= stale,
                                    table.c.attempt < table.c.max_attempts,
                                ),
                            ),
                        )
                        .order_by(table.c.created_at.asc())
                        .limit(1)
                        .with_for_update(skip_locked=True)
                        .scalar_subquery()
                    )
                    stmt = (
                        update(table)
                        .where(table.c.id == subq)
                        .values(
                            status="running",
                            locked_by=worker_id,
                            locked_at=now,
                            attempt=table.c.attempt + 1,
                            updated_at=now,
                        )
                        .returning(*table.c)
                    )
                    row = (await sess.execute(stmt)).fetchone()
                    return dict(row._mapping) if row is not None else None
        except Exception as e:
            log_error(f"Job queue store: claim failed for worker {worker_id} (deployment={deployment_id}): {e}")
            return None

    async def heartbeat_jobs(self, worker_id: str, job_ids: List[str]) -> int:
        """Refresh locked_at for this worker's in-flight jobs (keeps the lock
        grace small without long runs being reclaimed while alive)."""
        if not job_ids:
            return 0
        try:
            table = await self._get_table(table_type="jobs")
            if table is None:
                return 0
            now = _db_epoch()
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    result = await sess.execute(
                        update(table)
                        .where(
                            table.c.id.in_(job_ids),
                            table.c.locked_by == worker_id,
                            table.c.status == "running",
                        )
                        .values(locked_at=now)
                    )
                    return result.rowcount or 0  # type: ignore[attr-defined]
        except Exception as e:
            log_error(
                f"Job queue store: heartbeat failed for worker {worker_id} ({len(job_ids)} jobs, e.g. {job_ids[0]}): {e}"
            )
            return 0

    async def complete_job(
        self, job_id: str, worker_id: str, attempt: int, status: str, error: Optional[str] = None
    ) -> bool:
        """Fenced terminal transition: only the claim holder of this attempt
        may complete the job. A zombie's late write is silently discarded."""
        try:
            table = await self._get_table(table_type="jobs")
            if table is None:
                return False
            now = _db_epoch()
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    result = await sess.execute(
                        update(table)
                        .where(
                            table.c.id == job_id,
                            table.c.locked_by == worker_id,
                            table.c.attempt == attempt,
                            table.c.status == "running",
                        )
                        .values(
                            status=status,
                            error=error,
                            locked_by=None,
                            locked_at=None,
                            completed_at=now,
                            updated_at=now,
                        )
                    )
                    return (result.rowcount or 0) > 0  # type: ignore[attr-defined]
        except Exception as e:
            log_error(
                f"Job queue store: settle failed for job {job_id} (worker={worker_id}, attempt={attempt}, status={status!r}): {e}"
            )
            return False

    async def retry_or_fail_job(
        self, job_id: str, worker_id: str, attempt: int, error: str, retry_delay_seconds: int = 30
    ) -> Optional[str]:
        """Fenced failure handling: requeue with backoff while the attempt
        budget lasts, else fail terminally. Returns the resulting status
        ("queued" | "failed") or None if the fence rejected the write."""
        try:
            table = await self._get_table(table_type="jobs")
            if table is None:
                return None
            now = _db_epoch()
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    fence = (
                        select(table)
                        .where(
                            table.c.id == job_id,
                            table.c.locked_by == worker_id,
                            table.c.attempt == attempt,
                            table.c.status == "running",
                        )
                        .with_for_update()
                    )
                    row = (await sess.execute(fence)).fetchone()
                    if row is None:
                        return None
                    job = dict(row._mapping)
                    if job["attempt"] < job["max_attempts"]:
                        new_status = "queued"
                        values: Dict[str, Any] = {
                            "status": new_status,
                            "error": error,
                            "locked_by": None,
                            "locked_at": None,
                            "available_at": now + retry_delay_seconds,
                            "updated_at": now,
                        }
                    else:
                        new_status = "failed"
                        values = {
                            "status": new_status,
                            "error": error,
                            "locked_by": None,
                            "locked_at": None,
                            "completed_at": now,
                            "updated_at": now,
                        }
                    await sess.execute(update(table).where(table.c.id == job_id).values(**values))
                    return new_status
        except Exception as e:
            log_error(
                f"Job queue store: retry-or-fail failed for job {job_id} (worker={worker_id}, attempt={attempt}): {e}"
            )
            return None

    async def settle_paused_job(self, job_id: str, status: str, error: Optional[str] = None) -> bool:
        """Terminalize a PAUSED ticket whose continue ran INLINE, outside the
        queue (see InMemoryQueueStore.settle_paused_job). Single conditional
        UPDATE on status='paused'; a queued/claimed continuation owns the
        ticket and is never clobbered."""
        if status not in ("completed", "cancelled", "failed"):
            return False
        try:
            table = await self._get_table(table_type="jobs")
            if table is None:
                return False
            now = _db_epoch()
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    result = await sess.execute(
                        update(table)
                        .where(table.c.id == job_id, table.c.status == "paused")
                        .values(
                            status=status,
                            error=error,
                            locked_by=None,
                            locked_at=None,
                            completed_at=now,
                            updated_at=now,
                        )
                    )
                    return (result.rowcount or 0) > 0  # type: ignore[attr-defined]
        except Exception as e:
            log_error(f"Job queue store: paused-settle failed for job {job_id} (status={status!r}): {e}")
            return False

    async def cancel_job(self, job_id: str) -> bool:
        """Tombstone cancellation: only jobs still waiting can be cancelled
        here (contract: 'this job will not execute'). Claimed jobs fall
        through to the running-run cancellation path. Paused tickets count as
        waiting - nothing is executing them, and without this a cancelled
        paused run stayed a paused ticket forever, resurrectable by a later
        continue."""
        try:
            table = await self._get_table(table_type="jobs")
            if table is None:
                return False
            now = _db_epoch()
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    result = await sess.execute(
                        update(table)
                        .where(table.c.id == job_id, table.c.status.in_(["queued", "paused"]))
                        .values(status="cancelled", completed_at=now, updated_at=now)
                    )
                    return (result.rowcount or 0) > 0  # type: ignore[attr-defined]
        except Exception as e:
            log_error(f"Job queue store: cancel failed for job {job_id}: {e}")
            return False

    async def sweep_exhausted_jobs(self, lock_grace_seconds: int = 60, limit: int = 20) -> List[Dict[str, Any]]:
        """Return stale running jobs whose attempt budget is exhausted.

        These are NOT claimable (attempt >= max_attempts): the worker persists
        a terminal error on the run row first, then calls
        settle_swept_job — ordering + idempotence instead of cross-store
        atomicity."""
        try:
            table = await self._get_table(table_type="jobs")
            if table is None:
                return []
            stale = _db_epoch() - lock_grace_seconds
            async with self.async_session_factory() as sess:
                result = await sess.execute(
                    select(table)
                    .where(
                        table.c.status == "running",
                        table.c.locked_at <= stale,
                        table.c.attempt >= table.c.max_attempts,
                    )
                    .order_by(table.c.locked_at.asc())
                    .limit(limit)
                )
                return [dict(row._mapping) for row in result.fetchall()]
        except Exception as e:
            log_warning(f"Job queue store: sweep scan failed (lock_grace={lock_grace_seconds}s): {e}")
            return []

    async def acquire_sweep(self, job_id: str, worker_id: str, lock_grace_seconds: int = 60) -> bool:
        """Take ownership of a stale, budget-exhausted running job BEFORE any
        run-row write (conditional UPDATE = the CAS). A live heartbeat
        between the sweep's select and this acquisition wins here, with the
        run row still untouched. Refreshing locked_at doubles as the retry
        backoff for a failing terminalization."""
        try:
            table = await self._get_table(table_type="jobs")
            if table is None:
                return False
            now = _db_epoch()
            stale = now - lock_grace_seconds
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    result = await sess.execute(
                        update(table)
                        .where(
                            table.c.id == job_id,
                            table.c.status == "running",
                            table.c.locked_at <= stale,
                            table.c.attempt >= table.c.max_attempts,
                        )
                        .values(locked_by=worker_id, locked_at=now, updated_at=now)
                    )
                    return (result.rowcount or 0) > 0  # type: ignore[attr-defined]
        except Exception as e:
            log_error(f"Job queue store: sweep-lock acquisition failed for job {job_id} (worker={worker_id}): {e}")
            return False

    async def settle_swept_job(self, job_id: str, worker_id: str, status: str, error: Optional[str] = None) -> bool:
        """Ownership-keyed settle for the sweeper - see the in-memory store's
        docstring: the sweep reconciles the ticket with what the run row
        says (completed/cancelled/paused/failed), never blind-fails it."""
        if status not in ("completed", "cancelled", "paused", "failed"):
            return False
        try:
            table = await self._get_table(table_type="jobs")
            if table is None:
                return False
            now = _db_epoch()
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    result = await sess.execute(
                        update(table)
                        .where(
                            table.c.id == job_id,
                            table.c.status == "running",
                            table.c.locked_by == worker_id,
                        )
                        .values(
                            status=status,
                            error=error,
                            locked_by=None,
                            locked_at=None,
                            completed_at=now,
                            updated_at=now,
                        )
                    )
                    return (result.rowcount or 0) > 0  # type: ignore[attr-defined]
        except Exception as e:
            log_error(f"Job queue store: swept-job settle failed for job {job_id} (worker={worker_id}): {e}")
            return False

    async def get_job(self, job_id: str, strict: bool = False) -> Optional[Dict[str, Any]]:
        """Look up a ticket. Lenient by default: failures log and read as
        None, which the many fail-open readers (poll fallback, stats)
        rely on. strict=True makes failures PROPAGATE so None means
        exactly "no such ticket" - fail-closed consumers (the
        continue-ownership gate) must not read a store outage as "no
        ticket"; that inference reopens the cross-door double-execution
        race the gate exists to close."""
        if strict:
            table = await self._get_table(table_type="jobs")
            if table is None:
                raise RuntimeError(f"Job queue store: jobs table unavailable for strict lookup of {job_id}")
            async with self.async_session_factory() as sess:
                row = (await sess.execute(select(table).where(table.c.id == job_id))).fetchone()
                return dict(row._mapping) if row is not None else None
        try:
            table = await self._get_table(table_type="jobs")
            if table is None:
                return None
            async with self.async_session_factory() as sess:
                row = (await sess.execute(select(table).where(table.c.id == job_id))).fetchone()
                return dict(row._mapping) if row is not None else None
        except Exception as e:
            log_warning(f"Job queue store: get_job failed for job {job_id}: {e}")
            return None

    async def count_queued_jobs(self) -> int:
        try:
            table = await self._get_table(table_type="jobs")
            if table is None:
                return 0
            async with self.async_session_factory() as sess:
                result = await sess.execute(select(func.count()).select_from(table).where(table.c.status == "queued"))
                return result.scalar() or 0
        except Exception as e:
            log_warning(f"Job queue store: queued-count failed: {e}")
            return 0

    async def list_jobs(
        self,
        status: Optional[Union[str, List[str]]] = None,
        limit: int = 20,
        page: int = 1,
        sort_by: Optional[str] = "created_at",
        sort_order: Optional[str] = "desc",
    ) -> Tuple[List[Dict[str, Any]], int]:
        try:
            table = await self._get_table(table_type="jobs")
            if table is None:
                return [], 0
            stmt = select(table)
            if status is not None:
                statuses = [status] if isinstance(status, str) else list(status)
                stmt = stmt.where(table.c.status.in_(statuses))
            count_stmt = select(func.count()).select_from(stmt.alias())
            stmt = apply_sorting(stmt, table, sort_by, sort_order)
            # Deterministic tiebreaker: timestamps are epoch seconds, so ties
            # are common and would let rows move between pages otherwise
            stmt = stmt.order_by(table.c.id)
            stmt = stmt.limit(limit).offset(max(page - 1, 0) * limit)
            async with self.async_session_factory() as sess:
                total_count = (await sess.execute(count_stmt)).scalar() or 0
                result = await sess.execute(stmt)
                return [dict(row._mapping) for row in result.fetchall()], total_count
        except Exception as e:
            log_warning(f"Job queue store: list_jobs failed (status={status!r}): {e}")
            return [], 0

    async def requeue_job(self, job_id: str) -> bool:
        """Operator requeue for a terminally failed/cancelled job: grants
        exactly one more execution by raising max_attempts to attempt + 1."""
        try:
            table = await self._get_table(table_type="jobs")
            if table is None:
                return False
            now = _db_epoch()
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    result = await sess.execute(
                        update(table)
                        .where(table.c.id == job_id, table.c.status.in_(["failed", "cancelled"]))
                        .values(
                            status="queued",
                            max_attempts=table.c.attempt + 1,
                            available_at=now,
                            locked_by=None,
                            locked_at=None,
                            completed_at=None,
                            updated_at=now,
                        )
                    )
                    return (result.rowcount or 0) > 0  # type: ignore[attr-defined]
        except Exception as e:
            log_error(f"Job queue store: requeue failed for job {job_id}: {e}")
            return False

    async def continue_job(self, job_id: str, continue_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Continuation CAS: flip the EXISTING paused ticket back to queued,
        mirroring requeue_job's transition (row-locked read + conditional
        update in one transaction). No new rows, ever - id == run_id is
        load-bearing. Submit-time payload fields are kept; payload["continue"]
        is REPLACED WHOLESALE with this continue's inputs (never accumulated
        across pause cycles). Budget grant: max_attempts = attempt + 1 -
        exactly one more execution, regardless of the configured retry budget.

        Returns {"outcome": "queued" | "attach" | "conflict", "job": row}:
        queued = CAS won; attach = ticket already queued/running (double-click
        idempotency - the caller attaches, this click's inputs are discarded);
        conflict = terminal ticket or no ticket (job is the row or None).

        Exceptions propagate (like enqueue_job, unlike the ops-surface
        requeue_job): this CAS is the durable acceptance of the continue, and
        a DB failure must surface as a 500, never masquerade as "conflict".
        """
        table = await self._get_table(table_type="jobs")
        if table is None:
            raise RuntimeError("Job queue table not found")
        now = _db_epoch()
        async with self.async_session_factory() as sess:
            async with sess.begin():
                row = (await sess.execute(select(table).where(table.c.id == job_id).with_for_update())).fetchone()
                if row is None:
                    return {"outcome": "conflict", "job": None}
                job = dict(row._mapping)
                if job["status"] in ("completed", "failed", "cancelled"):
                    return {"outcome": "conflict", "job": job}
                if job["status"] in ("queued", "running"):
                    return {"outcome": "attach", "job": job}
                payload = dict(job.get("payload") or {})
                payload["continue"] = dict(continue_payload)
                values: Dict[str, Any] = {
                    "status": "queued",
                    "payload": payload,
                    "max_attempts": job["attempt"] + 1,
                    "available_at": now,
                    "locked_by": None,
                    "locked_at": None,
                    "completed_at": None,
                    "updated_at": now,
                }
                # RETURNING resolves the DB-clock stamps to concrete ints: the
                # timestamp values are SQL expressions (_db_epoch), and copying
                # them into the returned dict verbatim would hand callers
                # unserializable Cast objects where Redis/InMemory return ints.
                stamped = (
                    await sess.execute(
                        update(table)
                        .where(table.c.id == job_id)
                        .values(**values)
                        .returning(table.c.available_at, table.c.updated_at)
                    )
                ).fetchone()
                job.update(values)
                if stamped is not None:
                    job["available_at"], job["updated_at"] = stamped[0], stamped[1]
                return {"outcome": "queued", "job": job}

    async def queue_stats(self) -> Dict[str, Any]:
        try:
            table = await self._get_table(table_type="jobs")
            if table is None:
                return {"counts": {}, "oldest_queued_age_seconds": None}
            now = int(time.time())
            async with self.async_session_factory() as sess:
                counts_result = await sess.execute(select(table.c.status, func.count()).group_by(table.c.status))
                counts = {row[0]: row[1] for row in counts_result.fetchall()}
                oldest_result = await sess.execute(
                    select(func.min(table.c.created_at)).where(table.c.status == "queued")
                )
                oldest_created = oldest_result.scalar()
                oldest_age = (now - oldest_created) if oldest_created is not None else None
                return {"counts": counts, "oldest_queued_age_seconds": oldest_age}
        except Exception as e:
            log_warning(f"Job queue store: stats failed: {e}")
            return {"counts": {}, "oldest_queued_age_seconds": None}

    async def cleanup_jobs(self, older_than_seconds: int = 86400) -> int:
        """Delete terminal jobs whose completed_at is older than the retention
        window. Returns the number of rows removed. Paused tickets are
        deliberately EXEMPT: they must outlive arbitrary human latency to stay
        continuable; cancelling the run is the remedy for abandoned ones."""
        try:
            table = await self._get_table(table_type="jobs")
            if table is None:
                return 0
            cutoff = int(time.time()) - older_than_seconds
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    result = await sess.execute(
                        table.delete().where(
                            table.c.status.in_(["completed", "failed", "cancelled"]),
                            table.c.completed_at.is_not(None),
                            table.c.completed_at <= cutoff,
                        )
                    )
                    return result.rowcount or 0  # type: ignore[attr-defined]
        except Exception as e:
            log_warning(f"Job queue store: retention cleanup failed: {e}")
            return 0

    # -- Approval methods --

    async def create_approval(self, approval_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            table = await self._get_table(table_type="approvals", create_table_if_not_found=True)
            if table is None:
                raise RuntimeError("Failed to get or create approvals table")
            data = {**approval_data}
            now = int(time.time())
            data.setdefault("created_at", now)
            data.setdefault("updated_at", now)
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    await sess.execute(table.insert().values(**data))
            return data
        except Exception as e:
            log_error(f"Error creating approval: {str(e)}")
            raise

    async def get_approval(self, approval_id: str) -> Optional[Dict[str, Any]]:
        try:
            table = await self._get_table(table_type="approvals")
            if table is None:
                return None
            async with self.async_session_factory() as sess:
                result = await sess.execute(select(table).where(table.c.id == approval_id))
                row = result.fetchone()
                return dict(row._mapping) if row else None
        except Exception as e:
            log_debug(f"Error getting approval: {e}")
            return None

    async def get_approvals(
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
            table = await self._get_table(table_type="approvals")
            if table is None:
                return [], 0
            async with self.async_session_factory() as sess:
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
                total = (await sess.execute(count_stmt)).scalar() or 0

                # Calculate offset from page
                offset = (page - 1) * limit

                stmt = stmt.order_by(table.c.created_at.desc()).limit(limit).offset(offset)
                results = (await sess.execute(stmt)).fetchall()
                return [dict(row._mapping) for row in results], total
        except Exception as e:
            log_debug(f"Error listing approvals: {e}")
            return [], 0

    async def update_approval(
        self, approval_id: str, expected_status: Optional[str] = None, **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        try:
            table = await self._get_table(table_type="approvals")
            if table is None:
                return None
            kwargs["updated_at"] = int(time.time())
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    stmt = table.update().where(table.c.id == approval_id)
                    if expected_status is not None:
                        stmt = stmt.where(table.c.status == expected_status)
                    result = await sess.execute(stmt.values(**kwargs))
                    if result.rowcount == 0:  # type: ignore[attr-defined]
                        return None
            return await self.get_approval(approval_id)
        except Exception as e:
            log_debug(f"Error updating approval: {e}")
            return None

    async def delete_approval(self, approval_id: str) -> bool:
        try:
            table = await self._get_table(table_type="approvals")
            if table is None:
                return False
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    result = await sess.execute(table.delete().where(table.c.id == approval_id))
                    return result.rowcount > 0  # type: ignore[attr-defined]
        except Exception as e:
            log_debug(f"Error deleting approval: {e}")
            return False

    async def get_pending_approval_count(self, user_id: Optional[str] = None) -> int:
        try:
            table = await self._get_table(table_type="approvals")
            if table is None:
                return 0
            async with self.async_session_factory() as sess:
                stmt = select(func.count()).select_from(table).where(table.c.status == "pending")
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                return (await sess.execute(stmt)).scalar() or 0
        except Exception as e:
            log_debug(f"Error counting approvals: {e}")
            return 0

    async def update_approval_run_status(self, run_id: str, run_status: RunStatus) -> int:
        """Update run_status on all approvals for a given run_id.

        Args:
            run_id: The run ID to match.
            run_status: The new run status.

        Returns:
            Number of approvals updated.
        """
        try:
            table = await self._get_table(table_type="approvals")
            if table is None:
                return 0
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    stmt = (
                        table.update()
                        .where(table.c.run_id == run_id)
                        .values(run_status=run_status.value, updated_at=int(time.time()))
                    )
                    result = await sess.execute(stmt)
                    return result.rowcount or 0  # type: ignore[attr-defined]
        except Exception as e:
            log_debug(f"Error updating approval run_status: {e}")
            return 0

    # --- Auth Tokens ---

    async def get_auth_token(self, provider: str, user_id: Optional[str], service: str) -> Optional[Dict[str, Any]]:
        try:
            table = await self._get_table(table_type="auth_tokens")
            if table is None:
                return None
            # Use empty string for NULL user_id to satisfy unique constraint on (provider, user_id, service)
            effective_user_id = user_id if user_id is not None else ""
            async with self.async_session_factory() as sess:
                result = await sess.execute(
                    select(table).where(
                        table.c.provider == provider,
                        table.c.user_id == effective_user_id,
                        table.c.service == service,
                    )
                )
                row = result.fetchone()
                if not row:
                    return None
                return dict(row._mapping)
        except Exception as e:
            log_debug(f"Error getting auth token: {e}")
            return None

    async def upsert_auth_token(self, token: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            table = await self._get_table(table_type="auth_tokens", create_table_if_not_found=True)
            if table is None:
                raise RuntimeError("Failed to get or create auth_tokens table")
            data = {**token}
            data["id"] = str(uuid4())
            data["user_id"] = data.get("user_id") or ""
            now = int(time.time())
            data.setdefault("created_at", now)
            data["updated_at"] = now
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    stmt = postgresql.insert(table).values(**data)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["provider", "user_id", "service"],
                        set_={
                            "token_data": stmt.excluded.token_data,
                            "granted_scopes": stmt.excluded.granted_scopes,
                            "updated_at": stmt.excluded.updated_at,
                        },
                    )
                    await sess.execute(stmt)
            return data
        except Exception as e:
            log_debug(f"Error upserting auth token: {e}")
            return None

    async def delete_auth_token(self, provider: str, user_id: Optional[str], service: str) -> bool:
        try:
            table = await self._get_table(table_type="auth_tokens")
            if table is None:
                return False
            effective_user_id = user_id if user_id is not None else ""
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    result = await sess.execute(
                        table.delete().where(
                            table.c.provider == provider,
                            table.c.user_id == effective_user_id,
                            table.c.service == service,
                        )
                    )
                    return result.rowcount > 0  # type: ignore[attr-defined]
        except Exception as e:
            log_debug(f"Error deleting auth token: {e}")
            return False

    # -- Service Accounts methods --

    async def create_service_account(self, account_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            table = await self._get_table(table_type="service_accounts", create_table_if_not_found=True)
            if table is None:
                raise RuntimeError("Failed to get or create service accounts table")
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    await sess.execute(table.insert().values(**account_data))
            return account_data
        except Exception as e:
            log_error(f"Error creating service account: {str(e)}")
            raise

    async def get_service_account(
        self, service_account_id: str, user_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        try:
            table = await self._get_table(table_type="service_accounts")
            if table is None:
                return None
            async with self.async_session_factory() as sess:
                stmt = select(table).where(table.c.id == service_account_id)
                if user_id is not None:
                    stmt = stmt.where(or_(table.c.user_id == user_id, table.c.user_id.is_(None)))
                result = await sess.execute(stmt)
                row = result.fetchone()
                return dict(row._mapping) if row else None
        except Exception as e:
            log_debug(f"Error getting service account: {e}")
            return None

    async def get_service_account_by_token_hash(self, token_hash: str) -> Optional[Dict[str, Any]]:
        """Get a service account by its token hash.

        Re-raises on DB errors so callers can distinguish an unknown token (None) from a DB failure.
        """
        table = await self._get_table(table_type="service_accounts")
        if table is None:
            # _get_table swallows connectivity errors and returns None, which is
            # indistinguishable from "table not created yet". Probe the connection so
            # a real outage propagates (fail closed) instead of reading as an unknown
            # token; a genuinely absent table returns None.
            async with self.async_session_factory() as sess:
                await sess.execute(text("SELECT 1"))
            return None
        try:
            async with self.async_session_factory() as sess:
                result = await sess.execute(select(table).where(table.c.token_hash == token_hash))
                row = result.fetchone()
                return dict(row._mapping) if row else None
        except Exception as e:
            log_error(f"Error getting service account by token hash: {e}")
            raise

    async def get_service_account_by_name(self, name: str, include_revoked: bool = False) -> Optional[Dict[str, Any]]:
        try:
            table = await self._get_table(table_type="service_accounts")
            if table is None:
                return None
            async with self.async_session_factory() as sess:
                stmt = select(table).where(table.c.name == name)
                if not include_revoked:
                    stmt = stmt.where(table.c.revoked_at.is_(None))
                stmt = stmt.order_by(table.c.created_at.desc())
                result = await sess.execute(stmt)
                row = result.fetchone()
                return dict(row._mapping) if row else None
        except Exception as e:
            log_debug(f"Error getting service account by name: {e}")
            return None

    async def get_service_accounts(
        self,
        include_revoked: bool = True,
        limit: int = 20,
        page: int = 1,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        user_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        try:
            table = await self._get_table(table_type="service_accounts")
            if table is None:
                return [], 0
            async with self.async_session_factory() as sess:
                # Build base query with filters
                base_query = select(table)
                if not include_revoked:
                    base_query = base_query.where(table.c.revoked_at.is_(None))
                if user_id is not None:
                    base_query = base_query.where(or_(table.c.user_id == user_id, table.c.user_id.is_(None)))

                # Get total count
                count_stmt = select(func.count()).select_from(base_query.alias())
                count_result = await sess.execute(count_stmt)
                total_count = count_result.scalar() or 0

                # Calculate offset from page
                offset = (page - 1) * limit

                # Get paginated results
                sort_column = table.c[resolve_service_account_sort_column(sort_by)]
                order_by = sort_column.asc() if sort_order == "asc" else sort_column.desc()
                stmt = base_query.order_by(order_by).limit(limit).offset(offset)
                result = await sess.execute(stmt)
                return [dict(row._mapping) for row in result.fetchall()], total_count
        except Exception as e:
            log_debug(f"Error listing service accounts: {e}")
            return [], 0

    async def update_service_account(
        self, service_account_id: str, return_record: bool = True, **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        validate_service_account_update(kwargs)
        try:
            table = await self._get_table(table_type="service_accounts")
            if table is None:
                return None
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    await sess.execute(table.update().where(table.c.id == service_account_id).values(**kwargs))
            if not return_record:
                return None
            return await self.get_service_account(service_account_id)
        except Exception as e:
            log_debug(f"Error updating service account: {e}")
            return None

    async def delete_service_account(self, service_account_id: str) -> bool:
        try:
            table = await self._get_table(table_type="service_accounts")
            if table is None:
                return False
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    result = await sess.execute(table.delete().where(table.c.id == service_account_id))
                    return result.rowcount > 0  # type: ignore[attr-defined]
        except Exception as e:
            log_debug(f"Error deleting service account: {e}")
            return False
