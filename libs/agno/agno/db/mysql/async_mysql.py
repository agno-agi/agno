import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Tuple, Union
from uuid import uuid4

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace

from agno.db.base import AsyncBaseDb, SessionType
from agno.db.migrations.manager import MigrationManager
from agno.db.mysql.schemas import get_table_schema_definition
from agno.db.mysql.utils import (
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
from agno.db.utils import (
    HISTORY_SKIP_STATUSES,
    build_single_run_row,
    deserialize_run,
    deserialize_session,
    deserialize_sessions,
    filter_context_runs,
    json_serializer,
    merge_runs_table_with_legacy_blob,
    metrics_starting_date_from_days,
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
    from sqlalchemy import TEXT, ForeignKey, Index, UniqueConstraint, and_, cast, func, or_, update
    from sqlalchemy.dialects import mysql
    from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
    from sqlalchemy.schema import Column, MetaData, Table
    from sqlalchemy.sql.expression import select, text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


class AsyncMySQLDb(AsyncBaseDb):
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
        create_schema: bool = True,
    ):
        """
        Async interface for interacting with a MySQL database.

        The following order is used to determine the database connection:
            1. Use the db_engine if provided
            2. Use the db_url
            3. Raise an error if neither is provided

        Args:
            id (Optional[str]): The ID of the database.
            db_url (Optional[str]): The database URL to connect to. Should use asyncmy driver (e.g. mysql+asyncmy://...)
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
            create_schema (bool): Whether to automatically create the database schema if it doesn't exist.
                Set to False if schema is managed externally (e.g., via migrations). Defaults to True.

        Raises:
            ValueError: If neither db_url nor db_engine is provided.
            ValueError: If none of the tables are provided.
        """
        if id is None:
            # Parenthesized on purpose; see SqliteDb: unparenthesized, db_url is
            # dead without an engine and every instance shares one id.
            base_seed = db_url or (str(db_engine.url) if db_engine else "")  # type: ignore
            schema_suffix = db_schema if db_schema is not None else "ai"
            seed = f"{base_seed}#{schema_suffix}"
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
        )

        _engine: Optional[AsyncEngine] = db_engine
        if _engine is None and db_url is not None:
            _engine = create_async_engine(db_url, json_serializer=json_serializer)
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

    async def close(self) -> None:
        """Close database connections and dispose of the connection pool.

        Should be called during application shutdown to properly release
        all database connections.
        """
        if self.db_engine is not None:
            await self.db_engine.dispose()

    # -- DB methods --
    async def table_exists(self, table_name: str) -> bool:
        """Check if a table with the given name exists in the MySQL database.

        Args:
            table_name: Name of the table to check

        Returns:
            bool: True if the table exists in the database, False otherwise
        """
        async with self.async_session_factory() as sess:
            return await ais_table_available(session=sess, table_name=table_name, db_schema=self.db_schema)

    async def _create_table(self, table_name: str, table_type: str) -> Table:
        """
        Create a table with the appropriate schema based on the table type.

        Args:
            table_name (str): Name of the table to create
            table_type (str): Type of table (used to get schema definition)
            db_schema (str): Database schema name

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
                        await self._resolve_table(
                            table_name=ref_name,
                            table_type=ref_type,
                            create_table_if_not_found=True,
                        )

            log_debug(f"Creating table {self.db_schema}.{table_name} with schema: {table_schema}")

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

            # Create the table object - use self.metadata to maintain FK references
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

            # Add composite indexes with table-specific names
            for composite in schema_composite_indexes:
                composite_name = f"{table_name}_{composite['name']}"
                table.append_constraint(Index(composite_name, *composite["columns"]))

            # Create schema if not exists
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
                log_debug(f"Table {self.db_schema}.{table_name} already exists, skipping creation")

            # Create indexes
            for idx in table.indexes:
                try:
                    # Check if index already exists
                    async with self.async_session_factory() as sess:
                        exists_query = text(
                            "SELECT 1 FROM information_schema.statistics WHERE table_schema = :schema "
                            "AND table_name = :table_name AND index_name = :index_name"
                        )
                        result = await sess.execute(
                            exists_query, {"schema": self.db_schema, "table_name": table_name, "index_name": idx.name}
                        )
                        exists = result.scalar() is not None
                        if exists:
                            continue

                    async with self.db_engine.begin() as conn:
                        await conn.run_sync(idx.create)
                    log_debug(f"Created index: {idx.name} for table {self.db_schema}.{table_name}")

                except Exception as e:
                    log_error(f"Error creating index {idx.name}: {str(e)}")

            log_debug(f"Successfully created table {table_name} in schema {self.db_schema}")

            # Store the schema version for the created table
            if table_name != self.versions_table_name and table_created:
                latest_schema_version = MigrationManager(self).latest_schema_version
                await self.upsert_schema_version(table_name=table_name, version=latest_schema_version.public)
                log_info(
                    f"Successfully stored version {latest_schema_version.public} in database for table {table_name}"
                )

            return table

        except Exception as e:
            log_error(f"Could not create table {self.db_schema}.{table_name}: {str(e)}")
            raise

    async def _create_all_tables(self):
        """Create all tables for the database."""
        tables_to_create = [
            (self.session_table_name, "sessions"),
            (self.runs_table_name, "runs"),
            (self.memory_table_name, "memories"),
            (self.metrics_table_name, "metrics"),
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
            if not await self.table_exists(table_name):
                self._invalidate_table_cache(table_name)
            await self._get_or_create_table(
                table_name=table_name, table_type=table_type, create_table_if_not_found=True
            )

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
        async with self.async_session_factory() as sess:
            # Latest version for the given table
            stmt = select(table).where(table.c.table_name == table_name).order_by(table.c.version.desc()).limit(1)  # type: ignore
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
            await sess.execute(stmt)

    async def cleanup_legacy_runs_column(self, force: bool = False) -> bool:
        """Drop the legacy ``runs`` column from the sessions table.

        See :meth:`MySQLDb.cleanup_legacy_runs_column` for details.
        """
        async with self.async_session_factory() as sess, sess.begin():
            column_exists = (
                await sess.execute(
                    text(
                        "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
                        "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table AND COLUMN_NAME = 'runs'"
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
                            f"SELECT COUNT(*) FROM `{self.db_schema}`.`{self.session_table_name}` WHERE runs IS NOT NULL"
                        )
                    )
                ).scalar() or 0
                if pending > 0:
                    raise RuntimeError(
                        f"Refusing to drop {self.session_table_name}.runs: {pending} session(s) still have "
                        "non-null `runs` content. Run MigrationManager(db).up() first, or pass force=True."
                    )

            log_info(f"Dropping legacy runs column from {self.session_table_name}")
            await sess.execute(text(f"ALTER TABLE `{self.db_schema}`.`{self.session_table_name}` DROP COLUMN `runs`"))

        self._invalidate_table_cache(self.session_table_name)
        return True

    # -- Run methods --
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
            rows = [json.loads(row[0]) if isinstance(row[0], str) else row[0] for row in result.fetchall()]
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
        return [json.loads(row[0]) if isinstance(row[0], str) else row[0] for row in result.fetchall()]

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
            if isinstance(run_data, str):
                run_data = json.loads(run_data)
            runs_by_session.setdefault(session_id, []).append(run_data)
        return runs_by_session

    async def upsert_run(
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
            runs_table = await self._get_table(table_type="runs", create_table_if_not_found=True)
            if runs_table is None:
                return

            row = build_single_run_row(
                run=run,
                session_id=session_id,
                user_id=user_id,
                run_index=run_index,
            )

            backfill_lock: Optional[str] = None
            async with self.async_session_factory() as sess:
                try:
                    async with sess.begin():
                        # Backfill a monotonic run_index when the run arrives without one
                        # (e.g. a background/continue save that couldn't resolve its position).
                        # A NULL index has no position and breaks ORDER BY run_index. ON DUPLICATE KEY
                        # preserves the existing index, so this only sets it on a genuine insert.
                        if row.get("run_index") is None:
                            # Serialize same-session backfills: two concurrent
                            # max-reads can both see the same MAX and land
                            # duplicate indexes. GET_LOCK is connection-scoped
                            # and survives COMMIT, so it is released in the
                            # finally below - AFTER the row is durable.
                            backfill_lock = run_index_lock_name(session_id)
                            acquired = (
                                await sess.execute(text("SELECT GET_LOCK(:name, 5)"), {"name": backfill_lock})
                            ).scalar()
                            if not acquired:
                                log_warning(
                                    f"run_index backfill lock timed out for session {session_id}; "
                                    "proceeding unserialized"
                                )
                            current_max = (
                                await sess.execute(
                                    select(func.max(runs_table.c.run_index)).where(
                                        runs_table.c.session_id == session_id
                                    )
                                )
                            ).scalar()
                            row["run_index"] = (current_max + 1) if current_max is not None else 0

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
                        await sess.execute(stmt)
                finally:
                    if backfill_lock is not None:
                        try:
                            await sess.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": backfill_lock})
                        except Exception:
                            pass  # a dead connection frees its named locks on close

        except Exception as e:
            log_error(f"Exception upserting run to runs table: {str(e)}")
            raise e

    async def get_run(
        self, run_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[RunOutput, TeamRunOutput, WorkflowRunOutput, Dict[str, Any]]]:
        """Read a single run from the runs table."""
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
        """Get all runs matching the given filters."""
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
        """Async variant of the legacy-blob scrub. See mysql.py for rationale."""
        if not run_ids:
            return
        try:
            import json as _json

            sessions_table = await self._get_table(table_type="sessions")
            if sessions_table is None or "runs" not in sessions_table.c:
                return
            wanted = set(run_ids)
            async with self.async_session_factory() as sess, sess.begin():
                result = await sess.execute(
                    select(sessions_table.c.session_id, sessions_table.c.runs).where(sessions_table.c.runs.isnot(None))
                )
                rows = result.fetchall()
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
                    await sess.execute(
                        sessions_table.update().where(sessions_table.c.session_id == sid).values(runs=_json.dumps(kept))
                    )
        except Exception:
            log_debug("legacy-runs scrub failed; the primary delete still succeeded", exc_info=True)

    async def delete_run(self, run_id: str) -> bool:
        """Delete a single run from the runs table."""
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
        """Delete all given runs from the runs table."""
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

                if runs_table is not None:
                    await sess.execute(runs_table.delete().where(runs_table.c.session_id == session_id))

                log_debug(f"Successfully deleted session with session_id: {session_id} in table {table.name}")
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
                delete_stmt = table.delete().where(table.c.session_id.in_(session_ids))
                if user_id is not None:
                    delete_stmt = delete_stmt.where(table.c.user_id == user_id)
                result = await sess.execute(delete_stmt)

                if runs_table is not None:
                    runs_delete_stmt = runs_table.delete().where(runs_table.c.session_id.in_(session_ids))
                    if user_id is not None:
                        runs_delete_stmt = runs_delete_stmt.where(runs_table.c.user_id == user_id)
                    await sess.execute(runs_delete_stmt)

            log_debug(f"Successfully deleted {result.rowcount} sessions")  # type: ignore

        except Exception as e:
            log_error(f"Error deleting sessions: {str(e)}")

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
            session_type (Optional[SessionType]): Type of session to get. Defaults to None.
            user_id (Optional[str]): User ID to filter by. Defaults to None.
            deserialize (Optional[bool]): Whether to serialize the session. Defaults to True.

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
                if runs_table is not None and runs_limit is not None and not legacy_runs:
                    # Fully migrated: push "most recent N" down to the DB (indexed).
                    session["runs"] = await self._get_session_runs_data(
                        sess=sess, runs_table=runs_table, session_id=session_id, limit=runs_limit
                    )
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
    ) -> Union[List[Session], Tuple[List[Dict[str, Any]], int]]:
        """
        Get all sessions in the given table. Can filter by user_id and entity_id.

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

                if runs_table is not None:
                    runs_by_session = await self._get_sessions_runs_data(
                        sess=sess, runs_table=runs_table, session_ids=[s["session_id"] for s in session]
                    )
                    for s in session:
                        runs_data = runs_by_session.get(s["session_id"], [])
                        s["runs"] = merge_runs_table_with_legacy_blob(runs_data, s.get("runs"))

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
            session_type (SessionType): The type of session to rename.
            session_name (str): The new name for the session.
            user_id (Optional[str]): User ID to filter by. Defaults to None.
            deserialize (Optional[bool]): Whether to serialize the session. Defaults to True.

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
                await sess.execute(stmt)

                # Fetch the updated row
                select_stmt = select(table).where(table.c.session_id == session_id)
                if session_type is not None:
                    select_stmt = select_stmt.where(table.c.session_type == session_type.value)
                if user_id is not None:
                    select_stmt = select_stmt.where(table.c.user_id == user_id)
                result = await sess.execute(select_stmt)
                row = result.fetchone()
                if not row:
                    return None

                session = dict(row._mapping)
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
            table = await self._get_table(table_type="sessions", create_table_if_not_found=True)
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

            async with self.async_session_factory() as sess, sess.begin():
                existing_result = await sess.execute(
                    select(table.c.user_id)
                    .where(table.c.session_id == session_dict.get("session_id"))
                    .with_for_update()
                )
                existing_row = existing_result.fetchone()
                if existing_row is not None:
                    existing_uid = existing_row[0]
                    if existing_uid is not None and existing_uid != session_dict.get("user_id"):
                        return None

                current_time = int(time.time())
                stmt = mysql.insert(table).values(
                    session_id=session_dict.get("session_id"),
                    created_at=session_dict.get("created_at") or current_time,
                    updated_at=session_dict.get("updated_at") or current_time,
                    **values,
                )
                stmt = stmt.on_duplicate_key_update(**update_values)
                await sess.execute(stmt)

                # Fetch the row
                select_stmt = select(table).where(table.c.session_id == session_dict.get("session_id"))
                result = await sess.execute(select_stmt)
                row = result.fetchone()
                if row is None:
                    return None
                session_dict = dict(row._mapping)

            session_dict["runs"] = [run if isinstance(run, dict) else run.to_dict() for run in session.runs or []]
            log_debug(f"Upserted session with id '{session_dict.get('session_id')}'")

            if not deserialize:
                return session_dict
            return deserialize_session(None, session_dict)

        except Exception as e:
            log_error(f"Exception upserting into sessions table: {str(e)}")
            return None

    async def upsert_sessions(
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
            table = await self._get_table(table_type="sessions")
            if table is None:
                log_info("Sessions table not available, falling back to individual upserts")
                return [
                    result
                    for session in sessions
                    if session is not None
                    for result in [await self.upsert_session(session, deserialize=deserialize)]
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
            async with self.async_session_factory() as sess, sess.begin():
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
                        await sess.execute(stmt, agent_data)

                        # Fetch the results for agent sessions
                        agent_ids = [session.session_id for session in agent_sessions]
                        select_stmt = select(table).where(table.c.session_id.in_(agent_ids))
                        result = await sess.execute(select_stmt)
                        fetched_rows = result.fetchall()

                        for row in fetched_rows:
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
                        await sess.execute(stmt, team_data)

                        # Fetch the results for team sessions
                        team_ids = [session.session_id for session in team_sessions]
                        select_stmt = select(table).where(table.c.session_id.in_(team_ids))
                        result = await sess.execute(select_stmt)
                        fetched_rows = result.fetchall()

                        for row in fetched_rows:
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
                        await sess.execute(stmt, workflow_data)

                        # Fetch the results for workflow sessions
                        workflow_ids = [session.session_id for session in workflow_sessions]
                        select_stmt = select(table).where(table.c.session_id.in_(workflow_ids))
                        result = await sess.execute(select_stmt)
                        fetched_rows = result.fetchall()

                        for row in fetched_rows:
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
                for result in [await self.upsert_session(session, deserialize=deserialize)]
                if result is not None
            ]

    # -- Memory methods --
    async def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None) -> None:
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
            user_id (Optional[str]): Optional user ID to filter deletions.

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
            user_id (Optional[str]): Optional user ID to filter topics.

        Returns:
            List[str]: List of memory topics.
        """
        try:
            table = await self._get_table(table_type="memories")
            if table is None:
                return []

            async with self.async_session_factory() as sess, sess.begin():
                # MySQL approach: extract JSON array elements differently
                stmt = select(table.c.topics)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                result = await sess.execute(stmt)
                records = result.fetchall()

                topics_set = set()
                for row in records:
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
            return []

    async def get_user_memory(
        self, memory_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Get a memory from the database.

        Args:
            memory_id (str): The ID of the memory to get.
            deserialize (Optional[bool]): Whether to serialize the memory. Defaults to True.

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
                    # MySQL JSON contains syntax
                    topic_conditions = []
                    for topic in topics:
                        topic_conditions.append(func.json_contains(table.c.topics, f'"{topic}"'))
                    stmt = stmt.where(and_(*topic_conditions))
                if search_content is not None:
                    stmt = stmt.where(cast(table.c.memory, TEXT).ilike(f"%{search_content}%"))

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

            async with self.async_session_factory() as sess, sess.begin():
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
                await sess.execute(stmt)

                # Fetch the row
                select_stmt = select(table).where(table.c.memory_id == memory.memory_id)
                result = await sess.execute(select_stmt)
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

    async def upsert_memories(
        self, memories: List[UserMemory], deserialize: Optional[bool] = True, preserve_updated_at: bool = False
    ) -> List[Union[UserMemory, Dict[str, Any]]]:
        """
        Bulk upsert multiple user memories for improved performance on large datasets.

        Args:
            memories (List[UserMemory]): List of memories to upsert.
            deserialize (Optional[bool]): Whether to deserialize the memories. Defaults to True.
            preserve_updated_at (bool): If True, preserve the updated_at from the memory object.

        Returns:
            List[Union[UserMemory, Dict[str, Any]]]: List of upserted memories.

        Raises:
            Exception: If an error occurs during bulk upsert.
        """
        if not memories:
            return []

        try:
            table = await self._get_table(table_type="memories", create_table_if_not_found=True)
            if table is None:
                log_info("Memories table not available, falling back to individual upserts")
                return [
                    result
                    for memory in memories
                    if memory is not None
                    for result in [await self.upsert_user_memory(memory, deserialize=deserialize)]
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

            async with self.async_session_factory() as sess, sess.begin():
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
                await sess.execute(stmt, bulk_data)

                # Fetch results
                memory_ids = [memory.memory_id for memory in memories if memory.memory_id]
                select_stmt = select(table).where(table.c.memory_id.in_(memory_ids))
                result = await sess.execute(select_stmt)
                fetched_rows = result.fetchall()

                for row in fetched_rows:
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
                for result in [await self.upsert_user_memory(memory, deserialize=deserialize)]
                if result is not None
            ]

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

                if runs_table is not None and sessions:
                    session_ids = [s["session_id"] for s in sessions]
                    runs_stmt = select(
                        runs_table.c.session_id,
                        func.json_unquote(func.json_extract(runs_table.c.run_data, "$.model")).label("model"),
                        func.json_unquote(func.json_extract(runs_table.c.run_data, "$.model_provider")).label(
                            "model_provider"
                        ),
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

                # One record per user_id, plus the empty-string bucket for unowned sessions
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

        Args:
            starting_date (Optional[date]): The starting date to filter metrics by.
            ending_date (Optional[date]): The ending date to filter metrics by.
            user_id (Optional[str]): If set, only return that user's bucket. ``None`` returns all buckets.

        Returns:
            Tuple[List[dict], Optional[int]]: A tuple containing the metrics and the timestamp of the latest update.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table = await self._get_table(table_type="metrics", create_table_if_not_found=True)
            if table is None:
                return [], 0

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

            # Map the empty-string sentinel back to None
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
            user_id (Optional[str]): If set, only delete rows owned by this user. Unowned rows are not deleted.
        """
        table = await self._get_table(table_type="knowledge")
        if table is None:
            return None

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
            user_id (Optional[str]): If set, only return the row if owned by this user or unowned (NULL).

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
            user_id (Optional[str]): If set, only return rows owned by this user plus shared (NULL) rows.

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

                # Apply owner scoping: rows owned by this user, plus shared (NULL) rows
                if user_id is not None:
                    stmt = stmt.where(or_(table.c.user_id == user_id, table.c.user_id.is_(None)))

                # Apply sorting
                if sort_by is not None:
                    stmt = stmt.order_by(getattr(table.c, sort_by) * (1 if sort_order == "asc" else -1))

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
                        await sess.execute(stmt)
                    else:
                        # If we have no data at all, this is an error
                        log_error("No valid fields found for knowledge row upsert")
                        return None
                else:
                    # Normal upsert with conflict resolution
                    stmt = mysql.insert(table).values(insert_data).on_duplicate_key_update(**update_fields)
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
            table = await self._get_table(table_type="evals")
            if table is None:
                return None

            async with self.async_session_factory() as sess, sess.begin():
                current_time = int(time.time())
                stmt = mysql.insert(table).values(
                    {"created_at": current_time, "updated_at": current_time, **eval_run.model_dump()}
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
            user_id (Optional[str]): If set, only return runs owned by this user.
            eval_type (Optional[List[EvalType]]): The type(s) of eval to filter by.
            filter_type (Optional[EvalFilterType]): Filter by component type (agent, team, workflow).
            deserialize (Optional[bool]): Whether to serialize the eval runs. Defaults to True.

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
                stmt = (
                    table.update().where(table.c.run_id == eval_run_id).values(name=name, updated_at=int(time.time()))
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

        from typing import Sequence

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
            log_info(f"Migrated {len(sessions)} Agent sessions to table: {self.session_table_name}")

        elif v1_table_type == "team_sessions":
            for session in sessions:
                await self.upsert_session(session)
            log_info(f"Migrated {len(sessions)} Team sessions to table: {self.session_table_name}")

        elif v1_table_type == "workflow_sessions":
            for session in sessions:
                await self.upsert_session(session)
            log_info(f"Migrated {len(sessions)} Workflow sessions to table: {self.session_table_name}")

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

    async def upsert_trace(self, trace: "Trace") -> None:
        """Create or update a single trace record in the database.

        Uses INSERT ... ON DUPLICATE KEY UPDATE (upsert) to handle concurrent inserts
        atomically and avoid race conditions.

        Args:
            trace: The Trace object to store (one per trace_id).
        """
        from sqlalchemy import case

        try:
            table = await self._get_table(table_type="traces", create_table_if_not_found=True)
            if table is None:
                return

            trace_dict = trace.to_dict()
            trace_dict.pop("total_spans", None)
            trace_dict.pop("error_count", None)

            async with self.async_session_factory() as sess, sess.begin():
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

            table = await self._get_table(table_type="traces")
            if table is None:
                log_debug("Traces table not found")
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

                # Get total count
                count_stmt = select(func.count()).select_from(base_stmt.alias())
                count_result = await sess.execute(count_stmt)
                total_count = count_result.scalar() or 0

                # Apply pagination
                offset = (page - 1) * limit if page and limit else 0
                paginated_stmt = base_stmt.order_by(table.c.start_time.desc()).limit(limit).offset(offset)

                result = await sess.execute(paginated_stmt)
                results = result.fetchall()

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
            table = await self._get_table(table_type="traces")
            if table is None:
                log_debug("Traces table not found")
                return [], 0

            async with self.async_session_factory() as sess:
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
                count_result = await sess.execute(count_stmt)
                total_count = count_result.scalar() or 0

                # Apply pagination and ordering
                offset = (page - 1) * limit if page and limit else 0
                paginated_stmt = base_stmt.order_by(func.max(table.c.created_at).desc()).limit(limit).offset(offset)

                result = await sess.execute(paginated_stmt)
                results = result.fetchall()

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
                stmt = mysql.insert(table).values(span.to_dict())
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
                    stmt = mysql.insert(table).values(span.to_dict())
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

    # -- Learning methods (stubs) --
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
        raise NotImplementedError("Learning methods not yet implemented for AsyncMySQLDb")

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
        raise NotImplementedError("Learning methods not yet implemented for AsyncMySQLDb")

    async def delete_learning(self, id: str) -> bool:
        raise NotImplementedError("Learning methods not yet implemented for AsyncMySQLDb")

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
        raise NotImplementedError("Learning methods not yet implemented for AsyncMySQLDb")
