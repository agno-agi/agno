import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple, Union, cast
from uuid import uuid4

from sqlalchemy import or_

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace

from agno.db.base import AsyncBaseDb, ComponentType, SessionType
from agno.db.migrations.manager import MigrationManager
from agno.db.schemas.culture import CulturalKnowledge
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.db.sqlite.schemas import get_table_schema_definition
from agno.db.sqlite.utils import (
    abulk_upsert_metrics,
    ais_table_available,
    ais_valid_table,
    apply_sorting,
    calculate_date_metrics,
    deserialize_cultural_knowledge_from_db,
    fetch_all_sessions_data,
    get_dates_to_calculate_metrics_for,
    serialize_cultural_knowledge_for_db,
)
from agno.db.utils import deserialize_session_json_fields, serialize_session_json_fields
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.string import generate_id

try:
    from sqlalchemy import Column, ForeignKey, MetaData, String, Table, func, select, text
    from sqlalchemy.dialects import sqlite
    from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
    from sqlalchemy.schema import Index, UniqueConstraint
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


class AsyncSqliteDb(AsyncBaseDb):
    def __init__(
        self,
        db_file: Optional[str] = None,
        db_engine: Optional[AsyncEngine] = None,
        db_url: Optional[str] = None,
        session_table: Optional[str] = None,
        culture_table: Optional[str] = None,
        memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
        traces_table: Optional[str] = None,
        spans_table: Optional[str] = None,
        versions_table: Optional[str] = None,
        learnings_table: Optional[str] = None,
        schedules_table: Optional[str] = None,
        schedule_runs_table: Optional[str] = None,
        approvals_table: Optional[str] = None,
        id: Optional[str] = None,
    ):
        """
        Async interface for interacting with a SQLite database.

        The following order is used to determine the database connection:
            1. Use the db_engine
            2. Use the db_url
            3. Use the db_file
            4. Create a new database in the current directory

        Args:
            db_file (Optional[str]): The database file to connect to.
            db_engine (Optional[AsyncEngine]): The SQLAlchemy async database engine to use.
            db_url (Optional[str]): The database URL to connect to.
            session_table (Optional[str]): Name of the table to store Agent, Team and Workflow sessions.
            culture_table (Optional[str]): Name of the table to store cultural notions.
            memory_table (Optional[str]): Name of the table to store user memories.
            metrics_table (Optional[str]): Name of the table to store metrics.
            eval_table (Optional[str]): Name of the table to store evaluation runs data.
            knowledge_table (Optional[str]): Name of the table to store knowledge documents data.
            traces_table (Optional[str]): Name of the table to store run traces.
            spans_table (Optional[str]): Name of the table to store span events.
            versions_table (Optional[str]): Name of the table to store schema versions.
            learnings_table (Optional[str]): Name of the table to store learning records.
            schedules_table (Optional[str]): Name of the table to store cron schedules.
            schedule_runs_table (Optional[str]): Name of the table to store schedule run history.
            id (Optional[str]): ID of the database.

        Raises:
            ValueError: If none of the tables are provided.
        """
        if id is None:
            seed = db_url or db_file or str(db_engine.url) if db_engine else "sqlite+aiosqlite:///agno.db"
            id = generate_id(seed)

        super().__init__(
            id=id,
            session_table=session_table,
            culture_table=culture_table,
            memory_table=memory_table,
            metrics_table=metrics_table,
            eval_table=eval_table,
            knowledge_table=knowledge_table,
            traces_table=traces_table,
            spans_table=spans_table,
            versions_table=versions_table,
            learnings_table=learnings_table,
            schedules_table=schedules_table,
            schedule_runs_table=schedule_runs_table,
            approvals_table=approvals_table,
        )

        _engine: Optional[AsyncEngine] = db_engine
        if _engine is None:
            if db_url is not None:
                _engine = create_async_engine(db_url)
            elif db_file is not None:
                db_path = Path(db_file).resolve()
                db_path.parent.mkdir(parents=True, exist_ok=True)
                db_file = str(db_path)
                _engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            else:
                # If none of db_engine, db_url, or db_file are provided, create a db in the current directory
                default_db_path = Path("./agno.db").resolve()
                _engine = create_async_engine(f"sqlite+aiosqlite:///{default_db_path}")
                db_file = str(default_db_path)
                log_debug(f"Created SQLite database: {default_db_path}")

        self.db_engine: AsyncEngine = _engine
        self.db_url: Optional[str] = db_url
        self.db_file: Optional[str] = db_file
        self.metadata: MetaData = MetaData()

        # Initialize database session factory
        self.async_session_factory = async_sessionmaker(bind=self.db_engine, expire_on_commit=False)

    async def close(self) -> None:
        """Close database connections and dispose of the connection pool.

        Should be called during application shutdown to properly release
        all database connections.
        """
        if self.db_engine is not None:
            await self.db_engine.dispose()

    # -- DB methods --
    async def table_exists(self, table_name: str) -> bool:
        """Check if a table with the given name exists in the SQLite database.

        Args:
            table_name: Name of the table to check

        Returns:
            bool: True if the table exists in the database, False otherwise
        """
        async with self.async_session_factory() as sess:
            return await ais_table_available(session=sess, table_name=table_name)

    async def _create_all_tables(self):
        """Create all tables for the database."""
        tables_to_create = [
            (self.session_table_name, "sessions"),
            (self.memory_table_name, "memories"),
            (self.metrics_table_name, "metrics"),
            (self.eval_table_name, "evals"),
            (self.knowledge_table_name, "knowledge"),
            (self.versions_table_name, "versions"),
            (self.learnings_table_name, "learnings"),
            (self.schedules_table_name, "schedules"),
            (self.schedule_runs_table_name, "schedule_runs"),
            (self.approvals_table_name, "approvals"),
        ]

        for table_name, table_type in tables_to_create:
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
            # Pass table names for foreign key resolution
            table_schema = get_table_schema_definition(
                table_type,
                traces_table_name=self.trace_table_name,
                schedules_table_name=self.schedules_table_name,
            ).copy()

            columns: List[Column] = []
            indexes: List[str] = []
            unique_constraints: List[str] = []
            schema_unique_constraints = table_schema.pop("_unique_constraints", [])
            schema_composite_indexes = table_schema.pop("__composite_indexes__", [])

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
            table = Table(table_name, self.metadata, *columns)

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

            # Create table
            table_created = False
            if not await self.table_exists(table_name):
                async with self.db_engine.begin() as conn:
                    await conn.run_sync(table.create, checkfirst=True)
                log_debug(f"Successfully created table '{table_name}'")
                table_created = True
            else:
                log_debug(f"Table {table_name} already exists, skipping creation")

            # Create indexes
            for idx in table.indexes:
                try:
                    # Check if index already exists
                    async with self.async_session_factory() as sess:
                        exists_query = text("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = :index_name")
                        result = await sess.execute(exists_query, {"index_name": idx.name})
                        exists = result.scalar() is not None
                        if exists:
                            log_debug(f"Index {idx.name} already exists in table {table_name}, skipping creation")
                            continue

                    async with self.db_engine.begin() as conn:
                        await conn.run_sync(idx.create)
                    log_debug(f"Created index: {idx.name} for table {table_name}")

                except Exception as e:
                    log_warning(f"Error creating index {idx.name}: {e}")

            # Store the schema version for the created table
            if table_name != self.versions_table_name and table_created:
                latest_schema_version = MigrationManager(self).latest_schema_version
                await self.upsert_schema_version(table_name=table_name, version=latest_schema_version.public)

            return table

        except Exception as e:
            log_error(f"Could not create table '{table_name}': {e}")
            raise e

    async def _get_table(self, table_type: str, create_table_if_not_found: Optional[bool] = False) -> Optional[Table]:
        if table_type == "sessions":
            self.session_table = await self._get_or_create_table(
                table_name=self.session_table_name,
                table_type=table_type,
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.session_table

        elif table_type == "memories":
            self.memory_table = await self._get_or_create_table(
                table_name=self.memory_table_name,
                table_type="memories",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.memory_table

        elif table_type == "metrics":
            self.metrics_table = await self._get_or_create_table(
                table_name=self.metrics_table_name,
                table_type="metrics",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.metrics_table

        elif table_type == "evals":
            self.eval_table = await self._get_or_create_table(
                table_name=self.eval_table_name,
                table_type="evals",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.eval_table

        elif table_type == "knowledge":
            self.knowledge_table = await self._get_or_create_table(
                table_name=self.knowledge_table_name,
                table_type="knowledge",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.knowledge_table

        elif table_type == "culture":
            self.culture_table = await self._get_or_create_table(
                table_name=self.culture_table_name,
                table_type="culture",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.culture_table

        elif table_type == "versions":
            self.versions_table = await self._get_or_create_table(
                table_name=self.versions_table_name,
                table_type="versions",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.versions_table

        elif table_type == "traces":
            self.traces_table = await self._get_or_create_table(
                table_name=self.trace_table_name,
                table_type="traces",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.traces_table

        elif table_type == "spans":
            # Ensure traces table exists first (spans has FK to traces)
            if create_table_if_not_found:
                await self._get_table(table_type="traces", create_table_if_not_found=True)
            self.spans_table = await self._get_or_create_table(
                table_name=self.span_table_name,
                table_type="spans",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.spans_table

        elif table_type == "learnings":
            self.learnings_table = await self._get_or_create_table(
                table_name=self.learnings_table_name,
                table_type="learnings",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.learnings_table

        elif table_type == "schedules":
            self.schedules_table = await self._get_or_create_table(
                table_name=self.schedules_table_name,
                table_type="schedules",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.schedules_table

        elif table_type == "schedule_runs":
            self.schedule_runs_table = await self._get_or_create_table(
                table_name=self.schedule_runs_table_name,
                table_type="schedule_runs",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.schedule_runs_table

        elif table_type == "approvals":
            self.approvals_table = await self._get_or_create_table(
                table_name=self.approvals_table_name,
                table_type="approvals",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.approvals_table

        else:
            raise ValueError(f"Unknown table type: '{table_type}'")

    async def _get_or_create_table(
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
        async with self.async_session_factory() as sess, sess.begin():
            table_is_available = await ais_table_available(session=sess, table_name=table_name)

        if not table_is_available:
            if not create_table_if_not_found:
                return None
            return await self._create_table(table_name=table_name, table_type=table_type)

        # SQLite version of table validation (no schema)
        if not await ais_valid_table(db_engine=self.db_engine, table_name=table_name, table_type=table_type):
            raise ValueError(f"Table {table_name} has an invalid schema")

        try:
            async with self.db_engine.connect() as conn:

                def load_table(connection):
                    return Table(table_name, self.metadata, autoload_with=connection)

                table = await conn.run_sync(load_table)
                return table

        except Exception as e:
            log_error(f"Error loading existing table {table_name}: {e}")
            raise e

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
            await sess.execute(stmt)

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

            async with self.async_session_factory() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.session_id == session_id)
                if user_id is not None:
                    delete_stmt = delete_stmt.where(table.c.user_id == user_id)
                result = await sess.execute(delete_stmt)
                if result.rowcount == 0:  # type: ignore
                    log_debug(f"No session found to delete with session_id: {session_id}")
                    return False
                else:
                    log_debug(f"Successfully deleted session with session_id: {session_id}")
                    return True

        except Exception as e:
            log_error(f"Error deleting session: {e}")
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

            async with self.async_session_factory() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.session_id.in_(session_ids))
                if user_id is not None:
                    delete_stmt = delete_stmt.where(table.c.user_id == user_id)
                result = await sess.execute(delete_stmt)

            log_debug(f"Successfully deleted {result.rowcount} sessions")  # type: ignore

        except Exception as e:
            log_error(f"Error deleting sessions: {e}")

    async def get_session(
        self,
        session_id: str,
        session_type: SessionType,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """
        Read a session from the database.

        Args:
            session_id (str): ID of the session to read.
            session_type (SessionType): Type of session to get.
            user_id (Optional[str]): User ID to filter by. Defaults to None.
            deserialize (Optional[bool]): Whether to serialize the session. Defaults to True.

        Returns:
            Optional[Union[Session, Dict[str, Any]]]:
                - When deserialize=True: Session object
                - When deserialize=False: Session dictionary

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table = await self._get_table(table_type="sessions")
            if table is None:
                return None

            async with self.async_session_factory() as sess, sess.begin():
                stmt = select(table).where(table.c.session_id == session_id)

                # Filtering
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)

                result = await sess.execute(stmt)
                row = result.fetchone()
                if row is None:
                    return None

                session_raw = deserialize_session_json_fields(dict(row._mapping))
                if not session_raw or not deserialize:
                    return session_raw

            if session_type == SessionType.AGENT:
                return AgentSession.from_dict(session_raw)
            elif session_type == SessionType.TEAM:
                return TeamSession.from_dict(session_raw)
            elif session_type == SessionType.WORKFLOW:
                return WorkflowSession.from_dict(session_raw)
            else:
                raise ValueError(f"Invalid session type: {session_type}")

        except Exception as e:
            log_debug(f"Exception reading from sessions table: {e}")
            raise e

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

        Returns:
            List[Session]:
                - When deserialize=True: List of Session objects matching the criteria.
                - When deserialize=False: List of Session dictionaries matching the criteria.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table = await self._get_table(table_type="sessions")
            if table is None:
                return [] if deserialize else ([], 0)

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
                count_result = await sess.execute(count_stmt)
                total_count = count_result.scalar() or 0

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
                    return [] if deserialize else ([], 0)

                sessions_raw = [deserialize_session_json_fields(dict(record._mapping)) for record in records]
                if not deserialize:
                    return sessions_raw, total_count
                if not sessions_raw:
                    return []

            if session_type == SessionType.AGENT:
                return [AgentSession.from_dict(record) for record in sessions_raw]  # type: ignore
            elif session_type == SessionType.TEAM:
                return [TeamSession.from_dict(record) for record in sessions_raw]  # type: ignore
            elif session_type == SessionType.WORKFLOW:
                return [WorkflowSession.from_dict(record) for record in sessions_raw]  # type: ignore
            else:
                raise ValueError(f"Invalid session type: {session_type}")

        except Exception as e:
            log_debug(f"Exception reading from sessions table: {e}")
            raise e

    async def rename_session(
        self,
        session_id: str,
        session_type: SessionType,
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
            # Get the current session as a deserialized object
            session = await self.get_session(session_id, session_type, user_id=user_id, deserialize=True)
            if session is None:
                return None

            session = cast(Session, session)
            # Update the session name
            if session.session_data is None:
                session.session_data = {}
            session.session_data["session_name"] = session_name

            # Upsert the updated session back to the database
            return await self.upsert_session(session, deserialize=deserialize)

        except Exception as e:
            log_error(f"Exception renaming session: {e}")
            raise e

    async def upsert_session(
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
            table = await self._get_table(table_type="sessions", create_table_if_not_found=True)
            if table is None:
                return None

            serialized_session = serialize_session_json_fields(session.to_dict())

            if isinstance(session, AgentSession):
                async with self.async_session_factory() as sess, sess.begin():
                    stmt = sqlite.insert(table).values(
                        session_id=serialized_session.get("session_id"),
                        session_type=SessionType.AGENT.value,
                        agent_id=serialized_session.get("agent_id"),
                        user_id=serialized_session.get("user_id"),
                        agent_data=serialized_session.get("agent_data"),
                        session_data=serialized_session.get("session_data"),
                        metadata=serialized_session.get("metadata"),
                        runs=serialized_session.get("runs"),
                        summary=serialized_session.get("summary"),
                        created_at=serialized_session.get("created_at"),
                        updated_at=serialized_session.get("created_at"),
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["session_id"],
                        set_=dict(
                            agent_id=serialized_session.get("agent_id"),
                            user_id=serialized_session.get("user_id"),
                            runs=serialized_session.get("runs"),
                            summary=serialized_session.get("summary"),
                            agent_data=serialized_session.get("agent_data"),
                            session_data=serialized_session.get("session_data"),
                            metadata=serialized_session.get("metadata"),
                            updated_at=int(time.time()),
                        ),
                        where=(table.c.user_id == serialized_session.get("user_id")) | (table.c.user_id.is_(None)),
                    )
                    stmt = stmt.returning(*table.columns)  # type: ignore
                    result = await sess.execute(stmt)
                    row = result.fetchone()

                    session_raw = deserialize_session_json_fields(dict(row._mapping)) if row else None
                    if session_raw is None or not deserialize:
                        return session_raw
                    return AgentSession.from_dict(session_raw)

            elif isinstance(session, TeamSession):
                async with self.async_session_factory() as sess, sess.begin():
                    stmt = sqlite.insert(table).values(
                        session_id=serialized_session.get("session_id"),
                        session_type=SessionType.TEAM.value,
                        team_id=serialized_session.get("team_id"),
                        user_id=serialized_session.get("user_id"),
                        runs=serialized_session.get("runs"),
                        summary=serialized_session.get("summary"),
                        created_at=serialized_session.get("created_at"),
                        updated_at=serialized_session.get("created_at"),
                        team_data=serialized_session.get("team_data"),
                        session_data=serialized_session.get("session_data"),
                        metadata=serialized_session.get("metadata"),
                    )

                    stmt = stmt.on_conflict_do_update(
                        index_elements=["session_id"],
                        set_=dict(
                            team_id=serialized_session.get("team_id"),
                            user_id=serialized_session.get("user_id"),
                            summary=serialized_session.get("summary"),
                            runs=serialized_session.get("runs"),
                            team_data=serialized_session.get("team_data"),
                            session_data=serialized_session.get("session_data"),
                            metadata=serialized_session.get("metadata"),
                            updated_at=int(time.time()),
                        ),
                        where=(table.c.user_id == serialized_session.get("user_id")) | (table.c.user_id.is_(None)),
                    )
                    stmt = stmt.returning(*table.columns)  # type: ignore
                    result = await sess.execute(stmt)
                    row = result.fetchone()

                    session_raw = deserialize_session_json_fields(dict(row._mapping)) if row else None
                    if session_raw is None or not deserialize:
                        return session_raw
                    return TeamSession.from_dict(session_raw)

            else:
                async with self.async_session_factory() as sess, sess.begin():
                    stmt = sqlite.insert(table).values(
                        session_id=serialized_session.get("session_id"),
                        session_type=SessionType.WORKFLOW.value,
                        workflow_id=serialized_session.get("workflow_id"),
                        user_id=serialized_session.get("user_id"),
                        runs=serialized_session.get("runs"),
                        summary=serialized_session.get("summary"),
                        created_at=serialized_session.get("created_at") or int(time.time()),
                        updated_at=serialized_session.get("updated_at") or int(time.time()),
                        workflow_data=serialized_session.get("workflow_data"),
                        session_data=serialized_session.get("session_data"),
                        metadata=serialized_session.get("metadata"),
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["session_id"],
                        set_=dict(
                            workflow_id=serialized_session.get("workflow_id"),
                            user_id=serialized_session.get("user_id"),
                            summary=serialized_session.get("summary"),
                            runs=serialized_session.get("runs"),
                            workflow_data=serialized_session.get("workflow_data"),
                            session_data=serialized_session.get("session_data"),
                            metadata=serialized_session.get("metadata"),
                            updated_at=int(time.time()),
                        ),
                        where=(table.c.user_id == serialized_session.get("user_id")) | (table.c.user_id.is_(None)),
                    )
                    stmt = stmt.returning(*table.columns)  # type: ignore
                    result = await sess.execute(stmt)
                    row = result.fetchone()

                    session_raw = deserialize_session_json_fields(dict(row._mapping)) if row else None
                    if session_raw is None or not deserialize:
                        return session_raw
                    return WorkflowSession.from_dict(session_raw)

        except Exception as e:
            log_warning(f"Exception upserting into table: {e}")
            raise e

    async def upsert_sessions(
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
            table = await self._get_table(table_type="sessions", create_table_if_not_found=True)
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

            results: List[Union[Session, Dict[str, Any]]] = []

            async with self.async_session_factory() as sess, sess.begin():
                # Bulk upsert agent sessions
                if agent_sessions:
                    agent_data = []
                    for session in agent_sessions:
                        serialized_session = serialize_session_json_fields(session.to_dict())
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
                                "runs": serialized_session.get("runs"),
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
                                runs=stmt.excluded.runs,
                                summary=stmt.excluded.summary,
                                updated_at=stmt.excluded.updated_at,
                            ),
                        )
                        await sess.execute(stmt, agent_data)

                        # Fetch the results for agent sessions
                        agent_ids = [session.session_id for session in agent_sessions]
                        select_stmt = select(table).where(table.c.session_id.in_(agent_ids))
                        result = (await sess.execute(select_stmt)).fetchall()

                        for row in result:
                            session_dict = deserialize_session_json_fields(dict(row._mapping))
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
                        serialized_session = serialize_session_json_fields(session.to_dict())
                        # Use preserved updated_at if flag is set and value exists, otherwise use current time
                        updated_at = serialized_session.get("updated_at") if preserve_updated_at else int(time.time())
                        team_data.append(
                            {
                                "session_id": serialized_session.get("session_id"),
                                "session_type": SessionType.TEAM.value,
                                "team_id": serialized_session.get("team_id"),
                                "user_id": serialized_session.get("user_id"),
                                "runs": serialized_session.get("runs"),
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
                                runs=stmt.excluded.runs,
                                summary=stmt.excluded.summary,
                                updated_at=stmt.excluded.updated_at,
                            ),
                        )
                        await sess.execute(stmt, team_data)

                        # Fetch the results for team sessions
                        team_ids = [session.session_id for session in team_sessions]
                        select_stmt = select(table).where(table.c.session_id.in_(team_ids))
                        result = (await sess.execute(select_stmt)).fetchall()

                        for row in result:
                            session_dict = deserialize_session_json_fields(dict(row._mapping))
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
                        serialized_session = serialize_session_json_fields(session.to_dict())
                        # Use preserved updated_at if flag is set and value exists, otherwise use current time
                        updated_at = serialized_session.get("updated_at") if preserve_updated_at else int(time.time())
                        workflow_data.append(
                            {
                                "session_id": serialized_session.get("session_id"),
                                "session_type": SessionType.WORKFLOW.value,
                                "workflow_id": serialized_session.get("workflow_id"),
                                "user_id": serialized_session.get("user_id"),
                                "runs": serialized_session.get("runs"),
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
                                runs=stmt.excluded.runs,
                                summary=stmt.excluded.summary,
                                updated_at=stmt.excluded.updated_at,
                            ),
                        )
                        await sess.execute(stmt, workflow_data)

                        # Fetch the results for workflow sessions
                        workflow_ids = [session.session_id for session in workflow_sessions]
                        select_stmt = select(table).where(table.c.session_id.in_(workflow_ids))
                        result = (await sess.execute(select_stmt)).fetchall()

                        for row in result:
                            session_dict = deserialize_session_json_fields(dict(row._mapping))
                            if deserialize:
                                deserialized_workflow_session = WorkflowSession.from_dict(session_dict)
                                if deserialized_workflow_session is None:
                                    continue
                                results.append(deserialized_workflow_session)
                            else:
                                results.append(session_dict)

            return results

        except Exception as e:
            log_error(f"Exception during bulk session upsert, falling back to individual upserts: {e}")
            # Fallback to individual upserts
            return [
                result
                for session in sessions
                if session is not None
                for result in [await self.upsert_session(session, deserialize=deserialize)]
                if result is not None
            ]

    # -- Memory methods --

    async def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None):
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
            log_error(f"Error deleting user memory: {e}")
            raise e

    async def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete user memories from the database.

        Args:
            memory_ids (List[str]): The IDs of the memories to delete.
            user_id (Optional[str]): The user ID to filter by. Defaults to None.

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

        except Exception as e:
            log_error(f"Error deleting user memories: {e}")
            raise e

    async def get_all_memory_topics(self) -> List[str]:
        """Get all memory topics from the database.

        Returns:
            List[str]: List of memory topics.
        """
        try:
            table = await self._get_table(table_type="memories")
            if table is None:
                return []

            async with self.async_session_factory() as sess, sess.begin():
                # Select topics from all results
                stmt = select(table.c.topics)
                result = (await sess.execute(stmt)).fetchall()

                return list(set([record[0] for record in result]))

        except Exception as e:
            log_debug(f"Exception reading from memory table: {e}")
            raise e

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
            user_id (Optional[str]): The user ID to filter by. Defaults to None.

        Returns:
            Optional[Union[UserMemory, Dict[str, Any]]]:
                - When deserialize=True: UserMemory object
                - When deserialize=False: Memory dictionary

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
                result = (await sess.execute(stmt)).fetchone()
                if result is None:
                    return None

                memory_raw = dict(result._mapping)
                if not memory_raw or not deserialize:
                    return memory_raw

            return UserMemory.from_dict(memory_raw)

        except Exception as e:
            log_debug(f"Exception reading from memorytable: {e}")
            raise e

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
                - When deserialize=False: List of UserMemory dictionaries and total count

        Raises:
            Exception: If an error occurs during retrieval.
        """
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
                    stmt = stmt.where(table.c.memory.ilike(f"%{search_content}%"))

                # Get total count after applying filtering
                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = (await sess.execute(count_stmt)).scalar() or 0

                # Sorting
                stmt = apply_sorting(stmt, table, sort_by, sort_order)
                # Paginating
                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset((page - 1) * limit)

                result = (await sess.execute(stmt)).fetchall()
                if not result:
                    return [] if deserialize else ([], 0)

                memories_raw = [dict(record._mapping) for record in result]

                if not deserialize:
                    return memories_raw, total_count

            return [UserMemory.from_dict(record) for record in memories_raw]

        except Exception as e:
            log_error(f"Error reading from memory table: {e}")
            raise e

    async def get_user_memory_stats(
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
                total_count = (await sess.execute(count_stmt)).scalar() or 0

                # Pagination
                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset((page - 1) * limit)

                result = (await sess.execute(stmt)).fetchall()
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
            log_error(f"Error getting user memory stats: {e}")
            raise e

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
            table = await self._get_table(table_type="memories")
            if table is None:
                return None

            if memory.memory_id is None:
                memory.memory_id = str(uuid4())

            current_time = int(time.time())

            async with self.async_session_factory() as sess:
                async with sess.begin():
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

                    result = await sess.execute(stmt)
                    row = result.fetchone()

                if row is None:
                    return None

            memory_raw = dict(row._mapping)
            if not memory_raw or not deserialize:
                return memory_raw

            return UserMemory.from_dict(memory_raw)

        except Exception as e:
            log_error(f"Error upserting user memory: {e}")
            raise e

    async def upsert_memories(
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
            table = await self._get_table(table_type="memories")
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

            async with self.async_session_factory() as sess, sess.begin():
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
                await sess.execute(stmt, bulk_data)

                # Fetch results
                memory_ids = [memory.memory_id for memory in memories if memory.memory_id]
                select_stmt = select(table).where(table.c.memory_id.in_(memory_ids))
                result = (await sess.execute(select_stmt)).fetchall()

                for row in result:
                    memory_dict = dict(row._mapping)
                    if deserialize:
                        results.append(UserMemory.from_dict(memory_dict))
                    else:
                        results.append(memory_dict)

            return results

        except Exception as e:
            log_error(f"Exception during bulk memory upsert, falling back to individual upserts: {e}")

            # Fallback to individual upserts
            return [
                result
                for memory in memories
                if memory is not None
                for result in [await self.upsert_user_memory(memory, deserialize=deserialize)]
                if result is not None
            ]

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
            from agno.utils.log import log_warning

            log_warning(f"Exception deleting all memories: {e}")
            raise e

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
            table = await self._get_table(table_type="sessions", create_table_if_not_found=True)
            if table is None:
                return []

            stmt = select(
                table.c.user_id,
                table.c.session_data,
                table.c.runs,
                table.c.created_at,
                table.c.session_type,
            )

            if start_timestamp is not None:
                stmt = stmt.where(table.c.created_at >= start_timestamp)
            if end_timestamp is not None:
                stmt = stmt.where(table.c.created_at <= end_timestamp)

            async with self.async_session_factory() as sess:
                result = (await sess.execute(stmt)).fetchall()
                return [dict(record._mapping) for record in result]

        except Exception as e:
            log_error(f"Error reading from sessions table: {e}")
            raise e

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
            stmt = select(table).order_by(table.c.date.desc()).limit(1)
            result = (await sess.execute(stmt)).fetchone()

            # 1. Return the date of the first day without a complete metrics record.
            if result is not None:
                if result.completed:
                    return result._mapping["date"] + timedelta(days=1)
                else:
                    return result._mapping["date"]

        # 2. No metrics records. Return the date of the first recorded session.
        first_session, _ = await self.get_sessions(sort_by="created_at", sort_order="asc", limit=1, deserialize=False)
        first_session_date = first_session[0]["created_at"] if first_session else None  # type: ignore

        # 3. No metrics records and no sessions records. Return None.
        if not first_session_date:
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
            table = await self._get_table(table_type="metrics")
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

                metrics_record = calculate_date_metrics(date_to_process, sessions_for_date)
                metrics_records.append(metrics_record)

            if metrics_records:
                async with self.async_session_factory() as sess, sess.begin():
                    results = await abulk_upsert_metrics(session=sess, table=table, metrics_records=metrics_records)

            log_debug("Updated metrics calculations")

            return results

        except Exception as e:
            log_error(f"Error refreshing metrics: {e}")
            raise e

    async def get_metrics(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
    ) -> Tuple[List[dict], Optional[int]]:
        """Get all metrics matching the given date range.

        Args:
            starting_date (Optional[date]): The starting date to filter metrics by.
            ending_date (Optional[date]): The ending date to filter metrics by.

        Returns:
            Tuple[List[dict], Optional[int]]: A tuple containing the metrics and the timestamp of the latest update.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table = await self._get_table(table_type="metrics")
            if table is None:
                return [], None

            async with self.async_session_factory() as sess, sess.begin():
                stmt = select(table)
                if starting_date:
                    stmt = stmt.where(table.c.date >= starting_date)
                if ending_date:
                    stmt = stmt.where(table.c.date <= ending_date)
                result = (await sess.execute(stmt)).fetchall()
                if not result:
                    return [], None

                # Get the latest updated_at
                latest_stmt = select(func.max(table.c.updated_at))
                latest_updated_at = (await sess.execute(latest_stmt)).scalar()

            return [dict(row._mapping) for row in result], latest_updated_at

        except Exception as e:
            log_error(f"Error getting metrics: {e}")
            raise e

    # -- Knowledge methods --

    async def delete_knowledge_content(self, id: str):
        """Delete a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to delete.

        Raises:
            Exception: If an error occurs during deletion.
        """
        table = await self._get_table(table_type="knowledge")
        if table is None:
            return

        try:
            async with self.async_session_factory() as sess, sess.begin():
                stmt = table.delete().where(table.c.id == id)
                await sess.execute(stmt)

        except Exception as e:
            log_error(f"Error deleting knowledge content: {e}")
            raise e

    async def get_knowledge_content(self, id: str) -> Optional[KnowledgeRow]:
        """Get a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to get.

        Returns:
            Optional[KnowledgeRow]: The knowledge row, or None if it doesn't exist.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        table = await self._get_table(table_type="knowledge")
        if table is None:
            return None

        try:
            async with self.async_session_factory() as sess, sess.begin():
                stmt = select(table).where(table.c.id == id)
                result = (await sess.execute(stmt)).fetchone()
                if result is None:
                    return None

                return KnowledgeRow.model_validate(result._mapping)

        except Exception as e:
            log_error(f"Error getting knowledge content: {e}")
            raise e

    async def get_knowledge_contents(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        linked_to: Optional[str] = None,
    ) -> Tuple[List[KnowledgeRow], int]:
        """Get all knowledge contents from the database.

        Args:
            limit (Optional[int]): The maximum number of knowledge contents to return.
            page (Optional[int]): The page number.
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by.
            linked_to (Optional[str]): Filter by linked_to value (knowledge instance name).

        Returns:
            Tuple[List[KnowledgeRow], int]: The knowledge contents and total count.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        table = await self._get_table(table_type="knowledge")
        if table is None:
            return [], 0

        try:
            async with self.async_session_factory() as sess, sess.begin():
                stmt = select(table)

                # Apply linked_to filter if provided
                if linked_to is not None:
                    stmt = stmt.where(table.c.linked_to == linked_to)

                # Apply sorting
                if sort_by is not None:
                    stmt = stmt.order_by(getattr(table.c, sort_by) * (1 if sort_order == "asc" else -1))

                # Get total count before applying limit and pagination
                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = (await sess.execute(count_stmt)).scalar() or 0

                # Apply pagination after count
                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset((page - 1) * limit)

                result = (await sess.execute(stmt)).fetchall()
                return [KnowledgeRow.model_validate(record._mapping) for record in result], total_count

        except Exception as e:
            log_error(f"Error getting knowledge contents: {e}")
            raise e

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
                await sess.execute(stmt)

            return knowledge_row

        except Exception as e:
            log_error(f"Error upserting knowledge content: {e}")
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
                stmt = sqlite.insert(table).values(
                    {
                        "created_at": current_time,
                        "updated_at": current_time,
                        **eval_run.model_dump(),
                    }
                )
                await sess.execute(stmt)

            log_debug(f"Created eval run with id '{eval_run.run_id}'")

            return eval_run

        except Exception as e:
            log_error(f"Error creating eval run: {e}")
            raise e

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
            log_error(f"Error deleting eval run {eval_run_id}: {e}")
            raise e

    async def delete_eval_runs(self, eval_run_ids: List[str]) -> None:
        """Delete multiple eval runs from the database.

        Args:
            eval_run_ids (List[str]): List of eval run IDs to delete.
        """
        try:
            table = await self._get_table(table_type="evals")
            if table is None:
                return

            async with self.async_session_factory() as sess, sess.begin():
                stmt = table.delete().where(table.c.run_id.in_(eval_run_ids))
                result = await sess.execute(stmt)
                if result.rowcount == 0:  # type: ignore
                    log_debug(f"No eval runs found with IDs: {eval_run_ids}")
                else:
                    log_debug(f"Deleted {result.rowcount} eval runs")  # type: ignore

        except Exception as e:
            log_error(f"Error deleting eval runs {eval_run_ids}: {e}")
            raise e

    async def get_eval_run(
        self, eval_run_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Get an eval run from the database.

        Args:
            eval_run_id (str): The ID of the eval run to get.
            deserialize (Optional[bool]): Whether to serialize the eval run. Defaults to True.

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
                result = (await sess.execute(stmt)).fetchone()
                if result is None:
                    return None

                eval_run_raw = dict(result._mapping)
                if not eval_run_raw or not deserialize:
                    return eval_run_raw

            return EvalRunRecord.model_validate(eval_run_raw)

        except Exception as e:
            log_error(f"Exception getting eval run {eval_run_id}: {e}")
            raise e

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
            create_table_if_not_found (Optional[bool]): Whether to create the table if it doesn't exist.

        Returns:
            Union[List[EvalRunRecord], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of EvalRunRecord objects
                - When deserialize=False: List of EvalRun dictionaries and total count

        Raises:
            Exception: If an error occurs during retrieval.
        """
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
                total_count = (await sess.execute(count_stmt)).scalar() or 0

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

                result = (await sess.execute(stmt)).fetchall()
                if not result:
                    return [] if deserialize else ([], 0)

                eval_runs_raw = [dict(row._mapping) for row in result]
                if not deserialize:
                    return eval_runs_raw, total_count

            return [EvalRunRecord.model_validate(row) for row in eval_runs_raw]

        except Exception as e:
            log_error(f"Exception getting eval runs: {e}")
            raise e

    async def rename_eval_run(
        self, eval_run_id: str, name: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Upsert the name of an eval run in the database, returning raw dictionary.

        Args:
            eval_run_id (str): The ID of the eval run to update.
            name (str): The new name of the eval run.
            deserialize (Optional[bool]): Whether to serialize the eval run. Defaults to True.

        Returns:
            Optional[Union[EvalRunRecord, Dict[str, Any]]]:
                - When deserialize=True: EvalRunRecord object
                - When deserialize=False: EvalRun dictionary

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
                await sess.execute(stmt)

            eval_run_raw = await self.get_eval_run(eval_run_id=eval_run_id, deserialize=deserialize)

            log_debug(f"Renamed eval run with id '{eval_run_id}' to '{name}'")

            if not eval_run_raw or not deserialize:
                return eval_run_raw

            return EvalRunRecord.model_validate(eval_run_raw)

        except Exception as e:
            log_error(f"Error renaming eval run {eval_run_id}: {e}")
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

    # -- Culture methods --

    async def clear_cultural_knowledge(self) -> None:
        """Delete all cultural artifacts from the database.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = await self._get_table(table_type="culture")
            if table is None:
                return

            async with self.async_session_factory() as sess, sess.begin():
                await sess.execute(table.delete())

        except Exception as e:
            log_error(f"Exception deleting all cultural artifacts: {e}")

    async def delete_cultural_knowledge(self, id: str) -> None:
        """Delete a cultural artifact from the database.

        Args:
            id (str): The ID of the cultural artifact to delete.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = await self._get_table(table_type="culture")
            if table is None:
                return

            async with self.async_session_factory() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.id == id)
                result = await sess.execute(delete_stmt)

                success = result.rowcount > 0  # type: ignore
                if success:
                    log_debug(f"Successfully deleted cultural artifact id: {id}")
                else:
                    log_debug(f"No cultural artifact found with id: {id}")

        except Exception as e:
            log_error(f"Error deleting cultural artifact: {e}")

    async def get_cultural_knowledge(
        self, id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[CulturalKnowledge, Dict[str, Any]]]:
        """Get a cultural artifact from the database.

        Args:
            id (str): The ID of the cultural artifact to get.
            deserialize (Optional[bool]): Whether to serialize the cultural artifact. Defaults to True.

        Returns:
            Optional[CulturalKnowledge]: The cultural artifact, or None if it doesn't exist.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table = await self._get_table(table_type="culture")
            if table is None:
                return None

            async with self.async_session_factory() as sess, sess.begin():
                stmt = select(table).where(table.c.id == id)
                result = (await sess.execute(stmt)).fetchone()
                if result is None:
                    return None

                db_row = dict(result._mapping)
                if not db_row or not deserialize:
                    return db_row

            return deserialize_cultural_knowledge_from_db(db_row)

        except Exception as e:
            log_error(f"Exception reading from cultural artifacts table: {e}")
            return None

    async def get_all_cultural_knowledge(
        self,
        name: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[CulturalKnowledge], Tuple[List[Dict[str, Any]], int]]:
        """Get all cultural artifacts from the database as CulturalNotion objects.

        Args:
            name (Optional[str]): The name of the cultural artifact to filter by.
            agent_id (Optional[str]): The ID of the agent to filter by.
            team_id (Optional[str]): The ID of the team to filter by.
            limit (Optional[int]): The maximum number of cultural artifacts to return.
            page (Optional[int]): The page number.
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by.
            deserialize (Optional[bool]): Whether to serialize the cultural artifacts. Defaults to True.

        Returns:
            Union[List[CulturalKnowledge], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of CulturalNotion objects
                - When deserialize=False: List of CulturalNotion dictionaries and total count

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table = await self._get_table(table_type="culture")
            if table is None:
                return [] if deserialize else ([], 0)

            async with self.async_session_factory() as sess, sess.begin():
                stmt = select(table)

                # Filtering
                if name is not None:
                    stmt = stmt.where(table.c.name == name)
                if agent_id is not None:
                    stmt = stmt.where(table.c.agent_id == agent_id)
                if team_id is not None:
                    stmt = stmt.where(table.c.team_id == team_id)

                # Get total count after applying filtering
                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = (await sess.execute(count_stmt)).scalar() or 0

                # Sorting
                stmt = apply_sorting(stmt, table, sort_by, sort_order)
                # Paginating
                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset((page - 1) * limit)

                result = (await sess.execute(stmt)).fetchall()
                if not result:
                    return [] if deserialize else ([], 0)

                db_rows = [dict(record._mapping) for record in result]

                if not deserialize:
                    return db_rows, total_count

            return [deserialize_cultural_knowledge_from_db(row) for row in db_rows]

        except Exception as e:
            log_error(f"Error reading from cultural artifacts table: {e}")
            return [] if deserialize else ([], 0)

    async def upsert_cultural_knowledge(
        self, cultural_knowledge: CulturalKnowledge, deserialize: Optional[bool] = True
    ) -> Optional[Union[CulturalKnowledge, Dict[str, Any]]]:
        """Upsert a cultural artifact into the database.

        Args:
            cultural_knowledge (CulturalKnowledge): The cultural artifact to upsert.
            deserialize (Optional[bool]): Whether to serialize the cultural artifact. Defaults to True.

        Returns:
            Optional[Union[CulturalNotion, Dict[str, Any]]]:
                - When deserialize=True: CulturalNotion object
                - When deserialize=False: CulturalNotion dictionary

        Raises:
            Exception: If an error occurs during upsert.
        """
        try:
            table = await self._get_table(table_type="culture", create_table_if_not_found=True)
            if table is None:
                return None

            if cultural_knowledge.id is None:
                cultural_knowledge.id = str(uuid4())

            # Serialize content, categories, and notes into a JSON string for DB storage (SQLite requires strings)
            content_json_str = serialize_cultural_knowledge_for_db(cultural_knowledge)

            async with self.async_session_factory() as sess, sess.begin():
                stmt = sqlite.insert(table).values(
                    id=cultural_knowledge.id,
                    name=cultural_knowledge.name,
                    summary=cultural_knowledge.summary,
                    content=content_json_str,
                    metadata=cultural_knowledge.metadata,
                    input=cultural_knowledge.input,
                    created_at=cultural_knowledge.created_at,
                    updated_at=int(time.time()),
                    agent_id=cultural_knowledge.agent_id,
                    team_id=cultural_knowledge.team_id,
                )
                stmt = stmt.on_conflict_do_update(  # type: ignore
                    index_elements=["id"],
                    set_=dict(
                        name=cultural_knowledge.name,
                        summary=cultural_knowledge.summary,
                        content=content_json_str,
                        metadata=cultural_knowledge.metadata,
                        input=cultural_knowledge.input,
                        updated_at=int(time.time()),
                        agent_id=cultural_knowledge.agent_id,
                        team_id=cultural_knowledge.team_id,
                    ),
                ).returning(table)

                result = await sess.execute(stmt)
                row = result.fetchone()

                if row is None:
                    return None

            db_row: Dict[str, Any] = dict(row._mapping)
            if not db_row or not deserialize:
                return db_row

            return deserialize_cultural_knowledge_from_db(db_row)

        except Exception as e:
            log_error(f"Error upserting cultural knowledge: {e}")
            raise e

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
                        # Preserve existing non-null context values using COALESCE
                        "run_id": func.coalesce(insert_stmt.excluded.run_id, table.c.run_id),
                        "session_id": func.coalesce(insert_stmt.excluded.session_id, table.c.session_id),
                        "user_id": func.coalesce(insert_stmt.excluded.user_id, table.c.user_id),
                        "agent_id": func.coalesce(insert_stmt.excluded.agent_id, table.c.agent_id),
                        "team_id": func.coalesce(insert_stmt.excluded.team_id, table.c.team_id),
                        "workflow_id": func.coalesce(insert_stmt.excluded.workflow_id, table.c.workflow_id),
                    },
                )
                await sess.execute(upsert_stmt)

        except Exception as e:
            log_error(f"Error creating trace: {e}")
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
            log_error(f"Error getting trace: {e}")
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
                total_count = await sess.scalar(count_stmt) or 0

                # Apply pagination
                offset = (page - 1) * limit if page and limit else 0
                paginated_stmt = base_stmt.order_by(table.c.start_time.desc()).limit(limit).offset(offset)

                result = await sess.execute(paginated_stmt)
                results = result.fetchall()

                traces = [Trace.from_dict(dict(row._mapping)) for row in results]
                return traces, total_count

        except Exception as e:
            log_error(f"Error getting traces: {e}")
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

        Returns:
            tuple[List[Dict], int]: Tuple of (list of session stats dicts, total count).
                Each dict contains: session_id, user_id, agent_id, team_id, total_traces,
                workflow_id, first_trace_at, last_trace_at.
        """
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
                        table.c.user_id,
                        table.c.agent_id,
                        table.c.team_id,
                        table.c.workflow_id,
                        func.count(table.c.trace_id).label("total_traces"),
                        func.min(table.c.created_at).label("first_trace_at"),
                        func.max(table.c.created_at).label("last_trace_at"),
                    )
                    .where(table.c.session_id.isnot(None))  # Only sessions with session_id
                    .group_by(
                        table.c.session_id, table.c.user_id, table.c.agent_id, table.c.team_id, table.c.workflow_id
                    )
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
                total_count = await sess.scalar(count_stmt) or 0

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
            log_error(f"Error getting trace stats: {e}")
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
                stmt = sqlite.insert(table).values(span.to_dict())
                await sess.execute(stmt)

        except Exception as e:
            log_error(f"Error creating span: {e}")

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
                    stmt = sqlite.insert(table).values(span.to_dict())
                    await sess.execute(stmt)

        except Exception as e:
            log_error(f"Error creating spans batch: {e}")

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
            log_error(f"Error getting span: {e}")
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
            log_error(f"Error getting spans: {e}")
            return []

    # -- Learning methods --
    async def get_learning(
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
        workflow_id: Optional[str] = None,
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
            workflow_id: Associated workflow ID.
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
                stmt = sqlite.insert(table).values(
                    learning_id=id,
                    learning_type=learning_type,
                    namespace=namespace,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    workflow_id=workflow_id,
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
        """Delete a learning record.

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

    async def get_learnings(
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

                result = await sess.execute(stmt)
                results = result.fetchall()
                return [dict(row._mapping) for row in results]

        except Exception as e:
            log_debug(f"Error getting learnings: {e}")
            return []

    # --- Components (Not yet supported for async) ---
    def get_component(
        self,
        component_id: str,
        component_type: Optional[ComponentType] = None,
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("Component methods not yet supported for async databases")

    def upsert_component(
        self,
        component_id: str,
        component_type: Optional[ComponentType] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError("Component methods not yet supported for async databases")

    def delete_component(
        self,
        component_id: str,
        hard_delete: bool = False,
    ) -> bool:
        raise NotImplementedError("Component methods not yet supported for async databases")

    def list_components(
        self,
        component_type: Optional[ComponentType] = None,
        include_deleted: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        raise NotImplementedError("Component methods not yet supported for async databases")

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
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        raise NotImplementedError("Component methods not yet supported for async databases")

    def get_config(
        self,
        component_id: str,
        version: Optional[int] = None,
        label: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("Component methods not yet supported for async databases")

    def upsert_config(
        self,
        component_id: str,
        config: Optional[Dict[str, Any]] = None,
        version: Optional[int] = None,
        label: Optional[str] = None,
        stage: Optional[str] = None,
        notes: Optional[str] = None,
        links: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError("Component methods not yet supported for async databases")

    def delete_config(
        self,
        component_id: str,
        version: int,
    ) -> bool:
        raise NotImplementedError("Component methods not yet supported for async databases")

    def list_configs(
        self,
        component_id: str,
        include_config: bool = False,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError("Component methods not yet supported for async databases")

    def set_current_version(
        self,
        component_id: str,
        version: int,
    ) -> bool:
        raise NotImplementedError("Component methods not yet supported for async databases")

    def get_links(
        self,
        component_id: str,
        version: int,
        link_kind: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError("Component methods not yet supported for async databases")

    def get_dependents(
        self,
        component_id: str,
        version: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError("Component methods not yet supported for async databases")

    def load_component_graph(
        self,
        component_id: str,
        version: Optional[int] = None,
        label: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("Component methods not yet supported for async databases")

    # -- Schedule methods --
    async def get_schedule(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        try:
            table = await self._get_table(table_type="schedules")
            if table is None:
                return None
            async with self.async_session_factory() as sess:
                result = await sess.execute(select(table).where(table.c.id == schedule_id))
                row = result.fetchone()
                return dict(row._mapping) if row else None
        except Exception as e:
            log_debug(f"Error getting schedule: {e}")
            return None

    async def get_schedule_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        try:
            table = await self._get_table(table_type="schedules")
            if table is None:
                return None
            async with self.async_session_factory() as sess:
                result = await sess.execute(select(table).where(table.c.name == name))
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
    ) -> Tuple[List[Dict[str, Any]], int]:
        try:
            table = await self._get_table(table_type="schedules")
            if table is None:
                return [], 0
            async with self.async_session_factory() as sess:
                # Build base query with filters
                base_query = select(table)
                if enabled is not None:
                    base_query = base_query.where(table.c.enabled == enabled)

                # Get total count
                count_stmt = select(func.count()).select_from(base_query.alias())
                count_result = await sess.execute(count_stmt)
                total_count = count_result.scalar() or 0

                # Calculate offset from page
                offset = (page - 1) * limit

                # Get paginated results
                stmt = base_query.order_by(table.c.created_at.desc()).limit(limit).offset(offset)
                result = await sess.execute(stmt)
                return [dict(row._mapping) for row in result.fetchall()], total_count
        except Exception as e:
            log_debug(f"Error listing schedules: {e}")
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
            log_error(f"Error creating schedule: {e}")
            raise

    async def update_schedule(self, schedule_id: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
        try:
            table = await self._get_table(table_type="schedules")
            if table is None:
                return None
            kwargs["updated_at"] = int(time.time())
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    await sess.execute(table.update().where(table.c.id == schedule_id).values(**kwargs))
            return await self.get_schedule(schedule_id)
        except Exception as e:
            log_debug(f"Error updating schedule: {e}")
            return None

    async def delete_schedule(self, schedule_id: str) -> bool:
        try:
            table = await self._get_table(table_type="schedules")
            if table is None:
                return False
            runs_table = await self._get_table(table_type="schedule_runs")
            async with self.async_session_factory() as sess:
                async with sess.begin():
                    if runs_table is not None:
                        await sess.execute(runs_table.delete().where(runs_table.c.schedule_id == schedule_id))
                    result = await sess.execute(table.delete().where(table.c.id == schedule_id))
                    return result.rowcount > 0  # type: ignore[attr-defined]
        except Exception as e:
            log_debug(f"Error deleting schedule: {e}")
            return False

    async def claim_due_schedule(self, worker_id: str, lock_grace_seconds: int = 300) -> Optional[Dict[str, Any]]:
        try:
            table = await self._get_table(table_type="schedules")
            if table is None:
                return None
            now = int(time.time())
            stale_lock_threshold = now - lock_grace_seconds
            async with self.async_session_factory() as sess:
                async with sess.begin():
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
                    result = await sess.execute(stmt)
                    row = result.fetchone()
                    if row is None:
                        return None
                    schedule = dict(row._mapping)
                    claim_result = await sess.execute(
                        table.update()
                        .where(
                            table.c.id == schedule["id"],
                            or_(
                                table.c.locked_by.is_(None),
                                table.c.locked_at <= stale_lock_threshold,
                            ),
                        )
                        .values(locked_by=worker_id, locked_at=now)
                    )
                    if claim_result.rowcount == 0:  # type: ignore[attr-defined]
                        return None
                    schedule["locked_by"] = worker_id
                    schedule["locked_at"] = now
                    return schedule
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
            log_error(f"Error creating schedule run: {e}")
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

    async def get_schedule_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        try:
            table = await self._get_table(table_type="schedule_runs")
            if table is None:
                return None
            async with self.async_session_factory() as sess:
                result = await sess.execute(select(table).where(table.c.id == run_id))
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
    ) -> Tuple[List[Dict[str, Any]], int]:
        try:
            table = await self._get_table(table_type="schedule_runs")
            if table is None:
                return [], 0
            async with self.async_session_factory() as sess:
                # Get total count
                count_stmt = select(func.count()).select_from(table).where(table.c.schedule_id == schedule_id)
                count_result = await sess.execute(count_stmt)
                total_count = count_result.scalar() or 0

                # Calculate offset from page
                offset = (page - 1) * limit

                # Get paginated results
                stmt = (
                    select(table)
                    .where(table.c.schedule_id == schedule_id)
                    .order_by(table.c.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
                result = await sess.execute(stmt)
                return [dict(row._mapping) for row in result.fetchall()], total_count
        except Exception as e:
            log_debug(f"Error getting schedule runs: {e}")
            return [], 0

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
            log_error(f"Error creating approval: {e}")
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
