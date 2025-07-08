import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from sqlalchemy import Column, MetaData, Table, func, select, text

from agno.db.base import BaseDb, SessionType
from agno.db.schemas.memory import MemoryRow
from agno.db.sqlite.schemas import get_table_schema_definition
from agno.db.sqlite.utils import apply_sorting, is_table_available, is_valid_table
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info, log_warning

try:
    from sqlalchemy.dialects import sqlite
    from sqlalchemy.engine import Engine, create_engine
    from sqlalchemy.orm import scoped_session, sessionmaker
    from sqlalchemy.schema import Index, UniqueConstraint
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


class SqliteDb(BaseDb):
    def __init__(
        self,
        db_engine: Optional[Engine] = None,
        db_url: Optional[str] = None,
        db_file: Optional[str] = None,
        agent_session_table: Optional[str] = None,
        team_session_table: Optional[str] = None,
        workflow_session_table: Optional[str] = None,
        user_memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
    ):
        """
        Interface for interacting with a SQLite database.

        The following order is used to determine the database connection:
            1. Use the db_engine
            2. Use the db_url
            3. Use the db_file
            4. Create a new database in the current directory

        Args:
            db_engine (Optional[Engine]): The SQLAlchemy database engine to use.
            db_url (Optional[str]): The database URL to connect to.
            db_file (Optional[str]): The database file to connect to.
            agent_session_table (Optional[str]): Name of the table to store Agent sessions.
            team_session_table (Optional[str]): Name of the table to store Team sessions.
            workflow_session_table (Optional[str]): Name of the table to store Workflow sessions.
            user_memory_table (Optional[str]): Name of the table to store user memories.
            metrics_table (Optional[str]): Name of the table to store metrics.
            eval_table (Optional[str]): Name of the table to store evaluation runs data.
            knowledge_table (Optional[str]): Name of the table to store knowledge documents data.

        Raises:
            ValueError: If none of the tables are provided.
        """
        super().__init__(
            agent_session_table=agent_session_table,
            team_session_table=team_session_table,
            workflow_session_table=workflow_session_table,
            user_memory_table=user_memory_table,
            metrics_table=metrics_table,
            eval_table=eval_table,
            knowledge_table=knowledge_table,
        )

        _engine: Optional[Engine] = db_engine
        if _engine is None:
            if db_url is not None:
                _engine = create_engine(db_url)
            elif db_file is not None:
                db_path = Path(db_file).resolve()
                db_path.parent.mkdir(parents=True, exist_ok=True)
                self.db_file = str(db_path)
                _engine = create_engine(f"sqlite:///{db_path}")
            else:
                # If none of db_engine, db_url, or db_file are provided, create a db in the current directory
                default_db_path = Path("./agno.db").resolve()
                _engine = create_engine(f"sqlite:///{default_db_path}")
                self.db_file = str(default_db_path)
                log_debug(f"Created SQLite database: {default_db_path}")

        self.db_engine: Engine = _engine
        self.db_url: Optional[str] = db_url
        self.db_file: Optional[str] = db_file
        self.metadata: MetaData = MetaData()

        # Initialize database session
        self.Session: scoped_session = scoped_session(sessionmaker(bind=self.db_engine))

        log_debug("Created SqliteDb")

    # -- DB methods --

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
            table_schema = get_table_schema_definition(table_type)
            log_debug(f"Creating table {table_name} with schema: {table_schema}")

            columns, indexes, unique_constraints = [], [], []
            schema_unique_constraints = table_schema.pop("_unique_constraints", [])

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

                columns.append(Column(*column_args, **column_kwargs))

            # Create the table object
            table_metadata = MetaData()
            table = Table(table_name, table_metadata, *columns)

            # Add multi-column unique constraints
            for constraint in schema_unique_constraints:
                constraint_name = constraint["name"]
                constraint_columns = constraint["columns"]
                table.append_constraint(UniqueConstraint(*constraint_columns, name=constraint_name))

            # Add indexes to the table definition
            for idx_col in indexes:
                idx_name = f"idx_{table_name}_{idx_col}"
                table.append_constraint(Index(idx_name, idx_col))

            # Create table
            table_without_indexes = Table(
                table_name,
                MetaData(),
                *[c.copy() for c in table.columns],
                *[c for c in table.constraints if not isinstance(c, Index)],
            )
            table_without_indexes.create(self.db_engine, checkfirst=True)

            # Create indexes
            for idx in table.indexes:
                try:
                    log_debug(f"Creating index: {idx.name}")
                    # Check if index already exists
                    with self.Session() as sess:
                        exists_query = text("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = :index_name")
                        exists = sess.execute(exists_query, {"index_name": idx.name}).scalar() is not None
                        if exists:
                            log_debug(f"Index {idx.name} already exists in table {table_name}, skipping creation")
                            continue

                    idx.create(self.db_engine)
                except Exception as e:
                    log_warning(f"Error creating index {idx.name}: {e}")

            log_info(f"Successfully created table {table_name}")
            return table

        except Exception as e:
            log_error(f"Could not create table {table_name}: {e}")
            raise

    def _get_table_for_session_type(self, session_type: SessionType) -> Optional[Table]:
        if session_type == SessionType.AGENT:
            if self.agent_session_table_name is None:
                raise ValueError("Agent session table was not provided on initialization")
            self.agent_session_table = self._get_or_create_table(
                table_name=self.agent_session_table_name, table_type="agent_sessions"
            )
            return self.agent_session_table
        elif session_type == SessionType.TEAM:
            if self.team_session_table_name is None:
                raise ValueError("Team session table was not provided on initialization")
            self.team_session_table = self._get_or_create_table(
                table_name=self.team_session_table_name, table_type="team_sessions"
            )
            return self.team_session_table
        elif session_type == SessionType.WORKFLOW:
            if self.workflow_session_table_name is None:
                raise ValueError("Workflow session table was not provided on initialization")
            self.workflow_session_table = self._get_or_create_table(
                table_name=self.workflow_session_table_name, table_type="workflow_sessions"
            )
            return self.workflow_session_table

    def _get_or_create_table(self, table_name: str, table_type: str) -> Table:
        with self.Session() as sess, sess.begin():
            table_is_available = is_table_available(session=sess, table_name=table_name)

        if not table_is_available:
            return self._create_table(table_name=table_name, table_type=table_type)

        # SQLite version of table validation (no schema)
        if not is_valid_table(db_engine=self.db_engine, table_name=table_name, table_type=table_type):
            raise ValueError(f"Table {table_name} has an invalid schema")

        try:
            # Load table without schema for SQLite
            table = Table(table_name, self.metadata, autoload_with=self.db_engine)
            log_debug(f"Loaded existing table {table_name}")
            return table
        except Exception as e:
            log_error(f"Error loading existing table {table_name}: {e}")
            raise

    # -- Session methods --

    def _upsert_agent_session_raw(self, session: AgentSession) -> Optional[dict]:
        """
        Insert or update an agent session in the database.
        Args:
            session (AgentSession): The session data to upsert.
        Returns:
            Optional[dict]: The upserted session, or None if operation failed.
        Raises:
            Exception: If an error occurs during upsert.
        """
        try:
            table = self._get_table_for_session_type(SessionType.AGENT)
            if table is None:
                raise ValueError("Agent session table not found")

            # Calculated fields - convert to JSON strings for SQLite
            chat_history = (
                json.dumps([chat_message.to_dict() for chat_message in session.chat_history])
                if session.chat_history
                else None
            )
            runs = json.dumps([run.to_dict() for run in session.runs]) if session.runs else None
            summary = json.dumps(session.summary.to_dict()) if session.summary else None

            # Convert other JSON fields to strings
            agent_data = json.dumps(session.agent_data) if session.agent_data else None
            session_data = json.dumps(session.session_data) if session.session_data else None
            extra_data = json.dumps(session.extra_data) if session.extra_data else None

            with self.Session() as sess, sess.begin():
                # SQLite upsert using INSERT OR REPLACE
                stmt = sqlite.insert(table).values(
                    session_id=session.session_id,
                    agent_id=session.agent_id,
                    team_session_id=session.team_session_id,
                    user_id=session.user_id,
                    runs=runs,
                    agent_data=agent_data,
                    session_data=session_data,
                    chat_history=chat_history,
                    summary=summary,
                    extra_data=extra_data,
                    created_at=session.created_at,
                    updated_at=session.created_at,
                )

                # SQLite upsert syntax
                stmt = stmt.on_conflict_do_update(
                    index_elements=["session_id"],
                    set_=dict(
                        agent_id=session.agent_id,
                        team_session_id=session.team_session_id,
                        user_id=session.user_id,
                        agent_data=agent_data,
                        session_data=session_data,
                        chat_history=chat_history,
                        summary=summary,
                        extra_data=extra_data,
                        runs=runs,
                        updated_at=int(time.time()),
                    ),
                )

                sess.execute(stmt)

                # Get the upserted record since SQLite doesn't support RETURNING with upsert
                select_stmt = select(table).where(table.c.session_id == session.session_id)
                row = sess.execute(select_stmt).fetchone()
                sess.commit()

            return row._mapping if row else None

        except Exception as e:
            log_error(f"Exception upserting into agent session table: {e}")
            return None

    def _upsert_team_session_raw(self, session: TeamSession) -> Optional[Dict[str, Any]]:
        pass

    def _upsert_workflow_session_raw(self, session: WorkflowSession) -> Optional[Dict[str, Any]]:
        pass

    def get_session(self, session_id: str, session_type: SessionType) -> Optional[Session]:
        pass

    def get_sessions_raw(
        self,
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        component_id: Optional[str] = None,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
        session_name: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        table: Optional[Table] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Get all sessions in the given table, or of the given session_type, as raw dictionaries.
        Args:
            table (Optional[Table]): Table to read from.
            session_type (Optional[SessionType]): The type of session to get. Used if no table is provided.
            user_id (Optional[str]): The ID of the user to filter by.
            start_timestamp (Optional[int]): The start timestamp to filter by.
            end_timestamp (Optional[int]): The end timestamp to filter by.
            component_id (Optional[str]): The ID of the agent, team or workflow to filter by.
            limit (Optional[int]): The maximum number of sessions to return. Defaults to None.
            page (Optional[int]): The page number to return. Defaults to None.
            sort_by (Optional[str]): The field to sort by. Defaults to None.
            sort_order (Optional[str]): The sort order. Defaults to None.
        Returns:
            Tuple[List[Dict[str, Any]], int]: List of sessions matching the criteria and the total number of sessions.
        """
        try:
            if table is None:
                if session_type is None:
                    raise ValueError("Session type is required when no table is provided")
                table = self._get_table_for_session_type(session_type)
                if table is None:
                    raise ValueError("No table found")

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
                if start_timestamp is not None:
                    stmt = stmt.where(table.c.created_at >= start_timestamp)
                if end_timestamp is not None:
                    stmt = stmt.where(table.c.created_at <= end_timestamp)
                if session_name is not None:
                    stmt = stmt.where(
                        func.coalesce(func.json_extract(table.c.session_data, "$.session_name"), "").like(
                            f"%{session_name}%"
                        )
                    )

                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = sess.execute(count_stmt).scalar()

                # Sorting
                stmt = apply_sorting(stmt, table, sort_by, sort_order)

                # Paginating
                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset((page - 1) * limit)

                records = sess.execute(stmt).fetchall()
                if records is None:
                    return [], 0

                return [record._mapping for record in records], total_count

        except Exception as e:
            log_debug(f"Exception reading from table: {e}")
            return [], 0

    def get_sessions(
        self,
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        component_id: Optional[str] = None,
        session_name: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        table: Optional[Table] = None,
    ) -> Union[List[AgentSession], List[TeamSession], List[WorkflowSession]]:
        """
        Get all sessions in the given table. Can filter by user_id and entity_id.
        Args:
            table (Table): Table to read from.
            user_id (Optional[str]): The ID of the user to filter by.
            entity_id (Optional[str]): The ID of the agent / workflow to filter by.
            limit (Optional[int]): The maximum number of sessions to return. Defaults to None.
        Returns:
            List[Session]: List of Session objects matching the criteria.
        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            if table is None:
                if session_type is None:
                    raise ValueError("Session type is required when no table is provided")
                table = self._get_table_for_session_type(session_type)
                if table is None:
                    raise ValueError("No table found")

            sessions_raw, _ = self.get_sessions_raw(  # Note: Added unpacking here
                session_type=session_type,
                user_id=user_id,
                component_id=component_id,
                session_name=session_name,
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order,
                table=table,
            )

            if table == self.agent_session_table:
                return [AgentSession.from_dict(record) for record in sessions_raw]  # type: ignore
            elif table == self.team_session_table:
                return [TeamSession.from_dict(record) for record in sessions_raw]  # type: ignore
            elif table == self.workflow_session_table:
                return [WorkflowSession.from_dict(record) for record in sessions_raw]  # type: ignore
            else:
                raise ValueError(f"Invalid table: {table}")

        except Exception as e:
            log_debug(f"Exception reading from table: {e}")
            return []

    def upsert_session(self, session: Session) -> Optional[Session]:
        """
        Insert or update a session in the database.

        Args:
            session (Session): The session data to upsert.

        Returns:
            Optional[Session]: The upserted session, or None if operation failed.
        """
        try:
            if isinstance(session, AgentSession):
                session_raw = self._upsert_agent_session_raw(session=session)
                return AgentSession.from_dict(session_raw) if session_raw else None
            elif isinstance(session, TeamSession):
                session_raw = self._upsert_team_session_raw(session=session)
                return TeamSession.from_dict(session_raw) if session_raw else None
            elif isinstance(session, WorkflowSession):
                session_raw = self._upsert_workflow_session_raw(session=session)
                return WorkflowSession.from_dict(session_raw) if session_raw else None

        except Exception as e:
            log_warning(f"Exception upserting into table: {e}")
            return None

    # -- Memory methods --

    def get_user_memories(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        topics: Optional[List[str]] = None,
        search_content: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> List[MemoryRow]:
        return []

    def upsert_user_memory(self, memory: MemoryRow) -> Optional[MemoryRow]:
        pass

    def delete_user_memory(self, memory_id: str) -> bool:
        return True

    def delete_user_memories(self, memory_ids: List[str]) -> None:
        pass
