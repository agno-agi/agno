import time
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from agno.db.base import BaseDb, SessionType
from agno.db.postgres.schemas import get_table_schema_definition
from agno.db.schemas import MemoryRow
from agno.eval.schemas import EvalRunRecord, EvalType
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info, log_warning

try:
    from sqlalchemy import func, or_
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.engine import Engine, create_engine
    from sqlalchemy.inspection import inspect
    from sqlalchemy.orm import scoped_session, sessionmaker
    from sqlalchemy.schema import Column, MetaData, Table
    from sqlalchemy.sql.expression import select, text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


class PostgresDb(BaseDb):
    def __init__(
        self,
        db_engine: Optional[Engine] = None,
        db_schema: Optional[str] = None,
        db_url: Optional[str] = None,
        agent_session_table: Optional[str] = None,
        team_session_table: Optional[str] = None,
        workflow_session_table: Optional[str] = None,
        user_memory_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
    ):
        """
        Interface for interacting with a PostgreSQL database.

        The following order is used to determine the database connection:
            1. Use the db_engine if provided
            2. Use the db_url
            3. Raise an error if neither is provided

        Args:
            db_url (Optional[str]): The database URL to connect to.
            db_engine (Optional[Engine]): The SQLAlchemy database engine to use.
            db_schema (Optional[str]): The database schema to use.
            agent_session_table (Optional[str]): Name of the table to store Agent sessions.
            team_session_table (Optional[str]): Name of the table to store Team sessions.
            workflow_session_table (Optional[str]): Name of the table to store Workflow sessions.
            user_memory_table (Optional[str]): Name of the table to store user memories.
            eval_table (Optional[str]): Name of the table to store evaluation runs data.
            knowledge_table (Optional[str]): Name of the table to store knowledge documents data.

        Raises:
            ValueError: If neither db_url nor db_engine is provided.
            ValueError: If none of the tables are provided.
        """
        super().__init__(
            agent_session_table=agent_session_table,
            team_session_table=team_session_table,
            workflow_session_table=workflow_session_table,
            user_memory_table=user_memory_table,
            eval_table=eval_table,
            knowledge_table=knowledge_table,
        )

        self.agent_session_table: Optional[Table] = None

        _engine: Optional[Engine] = db_engine
        if _engine is None and db_url is not None:
            _engine = create_engine(db_url)
        if _engine is None:
            raise ValueError("One of db_url or db_engine must be provided")

        self.db_url: Optional[str] = db_url
        self.db_engine: Engine = _engine
        self.db_schema: str = db_schema if db_schema is not None else "ai"

        # Initialize metadata for table management
        self.metadata = MetaData()
        # Initialize database session
        self.Session: scoped_session = scoped_session(sessionmaker(bind=self.db_engine))

        log_debug("Created PostgresDb")

    # -- DB methods --

    # TODO: should also check column types, indexes
    def is_valid_table(self, table_name: str, table_type: str, db_schema: str) -> bool:
        """
        Check if the existing table has the expected column names.

        Args:
            table_name (str): Name of the table to validate
            schema (str): Database schema name

        Returns:
            bool: True if table has all expected columns, False otherwise
        """
        try:
            expected_table_schema = get_table_schema_definition(table_type)
            expected_columns = set(expected_table_schema.keys())

            # Get existing columns
            inspector = inspect(self.db_engine)
            existing_columns_info = inspector.get_columns(table_name, schema=db_schema)
            existing_columns = set(col["name"] for col in existing_columns_info)

            # Check if all expected columns exist
            missing_columns = expected_columns - existing_columns
            if missing_columns:
                log_warning(f"Missing columns {missing_columns} in table {db_schema}.{table_name}")
                return False

            log_debug(f"Table {db_schema}.{table_name} has all expected columns")
            return True
        except Exception as e:
            log_error(f"Error validating table schema for {db_schema}.{table_name}: {e}")
            return False

    def table_exists(self, table_name: str, db_schema: str) -> bool:
        """
        Check if the given table exists in the given schema.

        Returns:
            bool: True if the table exists, False otherwise.
        """
        try:
            with self.Session() as sess:
                exists_query = text(
                    "SELECT 1 FROM information_schema.tables WHERE table_schema = :schema AND table_name = :table"
                )
                exists = sess.execute(exists_query, {"schema": db_schema, "table": table_name}).scalar() is not None
                if not exists:
                    log_debug(f"Table {db_schema}.{table_name} {'exists' if exists else 'does not exist'}")

                return exists

        except Exception as e:
            log_error(f"Error checking if table exists: {e}")
            return False

    def create_schema(self, db_schema: str) -> None:
        """Create the database schema if it doesn't exist."""
        try:
            with self.Session() as sess, sess.begin():
                log_debug(f"Creating schema if not exists: {db_schema}")
                sess.execute(text(f"CREATE SCHEMA IF NOT EXISTS {db_schema};"))
        except Exception as e:
            log_warning(f"Could not create schema {db_schema}: {e}")

    def create_table(self, table_name: str, table_type: str, db_schema: str) -> Table:
        """
        Create a table with the appropriate schema based on the table name.

        Args:
            table_name (str): Name of the table to create
            db_schema (str): Database schema name

        Returns:
            Table: SQLAlchemy Table object
        """
        try:
            table_schema = get_table_schema_definition(table_type)

            log_debug(f"Creating table {db_schema}.{table_name} with schema: {table_schema}")

            columns, indexes = [], []
            for col_name, col_config in table_schema.items():
                column_args = [col_name, col_config["type"]()]
                column_kwargs = {}

                if col_config.get("primary_key", False):
                    column_kwargs["primary_key"] = True
                if "nullable" in col_config:
                    column_kwargs["nullable"] = col_config["nullable"]
                if col_config.get("index", False):
                    indexes.append(col_name)

                columns.append(Column(*column_args, **column_kwargs))

            # Create the table object
            table_metadata = MetaData(schema=db_schema)
            table = Table(table_name, table_metadata, *columns, schema=db_schema)

            # Add indexes to the table definition
            for idx_col in indexes:
                from sqlalchemy import Index

                idx_name = f"idx_{table_name}_{idx_col}"
                table.append_constraint(Index(idx_name, idx_col))

            # TODO: do we want this?
            self.create_schema(db_schema=db_schema)

            # Create table
            table_without_indexes = Table(
                table_name,
                MetaData(schema=db_schema),
                *[c.copy() for c in table.columns],
                schema=db_schema,
            )
            table_without_indexes.create(self.db_engine, checkfirst=True)

            # Create indexes
            for idx in table.indexes:
                try:
                    idx_name = idx.name
                    log_debug(f"Creating index: {idx_name}")

                    # Check if index already exists
                    with self.Session() as sess:
                        exists_query = text(
                            "SELECT 1 FROM pg_indexes WHERE schemaname = :schema AND indexname = :index_name"
                        )
                        exists = (
                            sess.execute(exists_query, {"schema": db_schema, "index_name": idx_name}).scalar()
                            is not None
                        )

                    if not exists:
                        idx.create(self.db_engine)
                    else:
                        log_debug(f"Index {idx_name} already exists in {db_schema}.{table_name}, skipping creation")

                except Exception as e:
                    log_warning(f"Error creating index {idx.name}: {e}")

            log_info(f"Successfully created table {db_schema}.{table_name}")
            return table

        except Exception as e:
            log_error(f"Could not create table {db_schema}.{table_name}: {e}")
            raise

    def get_table_for_session_type(self, session_type: Optional[SessionType] = None) -> Optional[Table]:
        """Map the given session type into the appropriate table.
        If the table has not been created yet, handle its creation.

        Args:
            session_type (Optional[SessionType]): The type of session to get the table for.

        Returns:
            Optional[Table]: The table for the given session type.
        """
        log_debug(f"Getting table for session type: {session_type}")
        if session_type is None:
            return None

        if session_type == SessionType.AGENT:
            if not hasattr(self, "agent_session_table"):
                if self.agent_session_table_name is None:
                    raise ValueError("Agent session table was not provided on initialization")
            self.agent_session_table = self.get_or_create_table(
                table_name=self.agent_session_table_name, table_type="agent_sessions", db_schema=self.db_schema
            )
            return self.agent_session_table

        elif session_type == SessionType.TEAM:
            if not hasattr(self, "team_session_table"):
                if self.team_session_table_name is None:
                    raise ValueError("Team session table was not provided on initialization")
            self.team_session_table = self.get_or_create_table(
                table_name=self.team_session_table_name, table_type="team_sessions", db_schema=self.db_schema
            )
            return self.team_session_table

        elif session_type == SessionType.WORKFLOW:
            if not hasattr(self, "workflow_session_table"):
                if self.workflow_session_table_name is None:
                    raise ValueError("Workflow session table was not provided on initialization")
            self.workflow_session_table = self.get_or_create_table(
                table_name=self.workflow_session_table_name,
                table_type="workflow_sessions",
                db_schema=self.db_schema,
            )
            return self.workflow_session_table

    def get_or_create_table(self, table_name: str, table_type: str, db_schema: str) -> Table:
        """
        Check if the table exists and is valid, else create it.

        Returns:
            Table: SQLAlchemy Table object representing the schema.
        """

        if not self.table_exists(table_name=table_name, db_schema=db_schema):
            return self.create_table(table_name=table_name, table_type=table_type, db_schema=db_schema)

        if not self.is_valid_table(table_name=table_name, table_type=table_type, db_schema=db_schema):
            raise ValueError(f"Table {db_schema}.{table_name} has an invalid schema")

        try:
            table = Table(table_name, self.metadata, schema=db_schema, autoload_with=self.db_engine)
            log_debug(f"Loaded existing table {db_schema}.{table_name}")
            return table

        except Exception as e:
            log_error(f"Error loading existing table {db_schema}.{table_name}: {e}")
            raise

    def _apply_sorting(self, stmt, table: Table, sort_by: Optional[str] = None, sort_order: Optional[str] = None):
        """Apply sorting to the given SQLAlchemy statement.

        Args:
            stmt: The SQLAlchemy statement to modify
            table: The table being queried
            sort_by: The field to sort by
            sort_order: The sort order ('asc' or 'desc')

        Returns:
            The modified statement with sorting applied
        """
        if sort_by is None or not hasattr(table.c, sort_by):
            log_debug(f"Invalid sort field '{sort_by}', will not apply any sorting")
            return stmt

        # Apply the given sorting
        sort_column = getattr(table.c, sort_by)
        if sort_order and sort_order == "asc":
            return stmt.order_by(sort_column.asc())
        else:
            return stmt.order_by(sort_column.desc())

    # -- Session methods --

    def delete_session(
        self,
        session_id: str,
        session_type: Optional[SessionType] = None,
        table: Optional[Table] = None,
    ) -> None:
        """
        Delete a Session from the database.

        Args:
            table (Table): Table to delete from.
            session_id (str): ID of the session to delete

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            if table is None:
                table = self.get_table_for_session_type(session_type)
                if table is None:
                    raise ValueError("No table found")

            with self.Session() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.session_id == session_id)
                result = sess.execute(delete_stmt)
                if result.rowcount == 0:
                    log_debug(f"No session found with session_id: {session_id} in table {table.name}")
                else:
                    log_debug(f"Successfully deleted session with session_id: {session_id} in table {table.name}")

        except Exception as e:
            log_error(f"Error deleting session: {e}")

    def get_runs_raw(self, session_id: str, session_type: SessionType) -> Optional[List[Dict[str, Any]]]:
        """
        Get all runs for the given session, as raw dictionaries.

        Args:
            session_id (str): The ID of the session to get runs for.
            session_type (SessionType): The type of session to get runs for.

        Returns:
            List[Dict[str, Any]]: List of run dictionaries.
        """
        try:
            table = self.get_table_for_session_type(session_type)
            if table is None:
                raise ValueError(f"Table not found for session type: {session_type}")

            with self.Session() as sess:
                stmt = select(table).where(table.c.session_id == session_id)
                result = sess.execute(stmt).fetchone()
                if result is None:
                    return None

            return result.runs

        except Exception as e:
            log_debug(f"Exception reading from table: {e}")
            return []

    def get_session_raw(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        session_type: Optional[SessionType] = None,
        table: Optional[Table] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get a session as a raw dictionary.

        Args:
            session_id (str): The ID of the session to get.
            session_type (SessionType): The type of session to get.

        Returns:
            Optional[Dict[str, Any]]: The session as a raw dictionary, or None if not found.
        """
        try:
            if table is None:
                table = self.get_table_for_session_type(session_type)
                if table is None:
                    raise ValueError(f"Table not found for session type: {session_type}")

            with self.Session() as sess:
                stmt = select(table).where(table.c.session_id == session_id)
                if user_id:
                    stmt = stmt.where(table.c.user_id == user_id)
                result = sess.execute(stmt).fetchone()
                if result is None:
                    return None

                return result._mapping

        except Exception as e:
            log_debug(f"Exception reading from table: {e}")
            return None

    def get_session(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        session_type: Optional[SessionType] = None,
        table: Optional[Table] = None,
    ) -> Optional[Union[AgentSession, TeamSession, WorkflowSession]]:
        """
        Read a Session from the database.

        Args:
            table (Table): Table to read from.
            session_id (str): ID of the session to read.
            user_id (Optional[str]): User ID to filter by. Defaults to None.
            session_type (Optional[SessionType]): Type of session to read. Defaults to None.

        Returns:
            Optional[Session]: Session object if found, None otherwise.
        """
        try:
            if table is None:
                table = self.get_table_for_session_type(session_type)
                if table is None:
                    raise ValueError(f"Table not found for session type: {session_type}")

            session_raw = self.get_session_raw(
                session_id=session_id,
                user_id=user_id,
                session_type=session_type,
                table=table,
            )
            if session_raw is None:
                return None

            if table == self.agent_session_table:
                return AgentSession.from_dict(session_raw)
            elif table == self.team_session_table:
                return TeamSession.from_dict(session_raw)
            elif table == self.workflow_session_table:
                return WorkflowSession.from_dict(session_raw)

        except Exception as e:
            log_debug(f"Exception reading from table: {e}")
            return None

    def get_sessions_raw(
        self,
        session_type: Optional[SessionType] = None,
        user_id: Optional[str] = None,
        component_id: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        table: Optional[Table] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Get all sessions in the given table as raw dictionaries.

        Args:
            table (Table): Table to read from.
            user_id (Optional[str]): The ID of the user to filter by.
            entity_id (Optional[str]): The ID of the agent / workflow to filter by.
            limit (Optional[int]): The maximum number of sessions to return. Defaults to None.

        Returns:
            Tuple[List[Dict[str, Any]], int]: List of Session objects matching the criteria and the total number of sessions.
        """
        try:
            if table is None:
                table = self.get_table_for_session_type(session_type)
                if table is None:
                    raise ValueError("No table found")

            with self.Session() as sess, sess.begin():
                stmt = select(table)
                # Filtering
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                if component_id is not None:
                    stmt = stmt.where(table.c.agent_id == component_id)

                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = sess.execute(count_stmt).scalar()

                # Sorting
                stmt = self._apply_sorting(stmt, table, sort_by, sort_order)
                # Paginating
                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset(page * limit)

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
        """
        try:
            if table is None:
                table = self.get_table_for_session_type(session_type)
                if table is None:
                    raise ValueError("No table found")

            sessions_raw = self.get_sessions_raw(
                session_type=session_type,
                user_id=user_id,
                component_id=component_id,
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

    def get_recent_sessions(
        self,
        session_type: Optional[SessionType] = None,
        component_id: Optional[str] = None,
        limit: Optional[int] = 3,
        table: Optional[Table] = None,
    ) -> Union[List[AgentSession], List[TeamSession], List[WorkflowSession]]:
        """Get the most recent sessions for the given entity."""
        return self.get_sessions(session_type=session_type, component_id=component_id, limit=limit, table=table)

    def get_all_session_ids(
        self,
        session_type: Optional[SessionType] = None,
        table: Optional[Table] = None,
        user_id: Optional[str] = None,
        entity_id: Optional[str] = None,
    ) -> List[str]:
        """
        Get all session IDs. Can filter by user_id and entity_id.

        Args:
            table (Table): Table to read from.
            user_id (Optional[str]): The ID of the user to filter by.
            entity_id (Optional[str]): The ID of the agent / workflow to filter by.

        Returns:
            List[str]: List of session IDs matching the criteria.
        """
        try:
            if table is None:
                table = self.get_table_for_session_type(session_type)
                if table is None:
                    raise ValueError("No table found")

            with self.Session() as sess, sess.begin():
                stmt = select(table.c.session_id)

                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                if entity_id is not None:
                    stmt = stmt.where(table.c.agent_id == entity_id)
                stmt = stmt.order_by(table.c.created_at.desc())

                rows = sess.execute(stmt).fetchall()
                return [row[0] for row in rows] if rows is not None else []

        except Exception as e:
            log_debug(f"Exception reading from table: {e}")
            return []

    def upsert_agent_session_raw(self, session: AgentSession, table: Optional[Table] = None) -> Optional[AgentSession]:
        try:
            if table is None:
                table = self.get_table_for_session_type(SessionType.AGENT)
                if table is None:
                    raise ValueError("Agent session table not found")

            with self.Session() as sess, sess.begin():
                stmt = postgresql.insert(table).values(
                    session_id=session.session_id,
                    agent_id=session.agent_id,
                    team_session_id=session.team_session_id,
                    user_id=session.user_id,
                    runs=session.runs,
                    agent_data=session.agent_data,
                    session_data=session.session_data,
                    summary=session.summary,
                    extra_data=session.extra_data,
                    created_at=session.created_at,
                )

                # TODO: Review the conflict params
                stmt = stmt.on_conflict_do_update(
                    index_elements=["session_id"],
                    set_=dict(
                        agent_id=session.agent_id,
                        team_session_id=session.team_session_id,
                        user_id=session.user_id,
                        agent_data=session.agent_data,
                        session_data=session.session_data,
                        summary=session.summary,
                        extra_data=session.extra_data,
                        runs=session.runs,
                        updated_at=int(time.time()),
                    ),
                ).returning(table)
                result = sess.execute(stmt)
                row = result.fetchone()
                sess.commit()

            return row._mapping

        except Exception as e:
            log_error(f"Exception upserting into agent session table: {e}")
            return None

    def upsert_team_session_raw(self, session: TeamSession, table: Optional[Table] = None) -> Optional[TeamSession]:
        try:
            if table is None:
                table = self.get_table_for_session_type(SessionType.TEAM)
                if table is None:
                    raise ValueError("Team session table not found")

            with self.Session() as sess, sess.begin():
                stmt = postgresql.insert(table).values(
                    session_id=session.session_id,
                    team_id=session.team_id,
                    team_session_id=session.team_session_id,
                    user_id=session.user_id,
                    runs=session.runs,
                    team_data=session.team_data,
                    session_data=session.session_data,
                    summary=session.summary,
                    extra_data=session.extra_data,
                    created_at=session.created_at,
                    chat_history=session.chat_history,
                )
                # TODO: Review the conflict params
                stmt = stmt.on_conflict_do_update(
                    index_elements=["session_id"],
                    set_=dict(
                        team_id=session.team_id,
                        team_session_id=session.team_session_id,
                        user_id=session.user_id,
                        team_data=session.team_data,
                        session_data=session.session_data,
                        summary=session.summary,
                        extra_data=session.extra_data,
                        runs=session.runs,
                        chat_history=session.chat_history,
                        updated_at=int(time.time()),
                    ),
                ).returning(table)
                result = sess.execute(stmt)
                row = result.fetchone()
                sess.commit()

            return row._mapping

        except Exception as e:
            log_error(f"Exception upserting into team session table: {e}")
            return None

    def upsert_workflow_session_raw(
        self, session: WorkflowSession, table: Optional[Table] = None
    ) -> Optional[WorkflowSession]:
        try:
            if table is None:
                table = self.get_table_for_session_type(SessionType.WORKFLOW)
                if table is None:
                    raise ValueError("Workflow session table not found")

            with self.Session() as sess, sess.begin():
                stmt = postgresql.insert(table).values(
                    session_id=session.session_id,
                    workflow_id=session.workflow_id,
                    user_id=session.user_id,
                    runs=session.runs,
                    workflow_data=session.workflow_data,
                    session_data=session.session_data,
                    summary=session.summary,
                    extra_data=session.extra_data,
                    created_at=session.created_at,
                    chat_history=session.chat_history,
                )
                # TODO: Review the conflict params
                stmt = stmt.on_conflict_do_update(
                    index_elements=["session_id"],
                    set_=dict(
                        workflow_id=session.workflow_id,
                        user_id=session.user_id,
                        workflow_data=session.workflow_data,
                        session_data=session.session_data,
                        summary=session.summary,
                        extra_data=session.extra_data,
                        runs=session.runs,
                        chat_history=session.chat_history,
                        updated_at=int(time.time()),
                    ),
                ).returning(table)
                result = sess.execute(stmt)
                row = result.fetchone()
                sess.commit()

            return row._mapping

        except Exception as e:
            log_error(f"Exception upserting into workflow session table: {e}")
            return None

    def upsert_session_raw(self, session: Session) -> Optional[Session]:
        """
        Insert or update a Session in the database.

        Args:
            session (Session): The session data to upsert.
            table (Table): Table to upsert into.

        Returns:
            Optional[AgentSession]: The upserted AgentSession, or None if operation failed.
        """

        try:
            if isinstance(session, AgentSession):
                return self.upsert_agent_session_raw(session=session)
            elif isinstance(session, TeamSession):
                return self.upsert_team_session_raw(session=session)
            elif isinstance(session, WorkflowSession):
                return self.upsert_workflow_session_raw(session=session)

        except Exception as e:
            log_warning(f"Exception upserting into table: {e}")
            return None

    def upsert_session(self, session: Session) -> Optional[Session]:
        """
        Insert or update a Session in the database.
        """
        session_raw = self.upsert_session_raw(session=session)
        if session_raw is None:
            return None

        # TODO:

        return session_raw

    # -- Memory methods --

    def get_user_memory_table(self) -> Table:
        """Get or create the user memory table."""
        if not hasattr(self, "user_memory_table"):
            if self.user_memory_table_name is None:
                raise ValueError("User memory table was not provided on initialization")
            log_info(f"Getting user memory table: {self.user_memory_table_name}")
            self.user_memory_table = self.get_or_create_table(
                table_name=self.user_memory_table_name, table_type="user_memories", db_schema=self.db_schema
            )
        return self.user_memory_table

    def get_user_memory_raw(self, memory_id: str, table: Optional[Table] = None) -> Optional[Dict[str, Any]]:
        """Get a memory from the database as a raw dictionary.

        Args:
            memory_id (str): The ID of the memory to get.
            table (Table): Table to read from.

        Returns:
            Optional[Dict[str, Any]]: The memory as a raw dictionary, or None if not found.
        """
        try:
            if table is None:
                table = self.get_user_memory_table()

            # TODO: Review if we need to use begin() for read operations
            with self.Session() as sess, sess.begin():
                stmt = select(table).where(table.c.memory_id == memory_id)
                result = sess.execute(stmt).fetchone()
                if result is None:
                    return None

            return result._mapping

        except Exception as e:
            log_debug(f"Exception reading from table: {e}")
            return None

    def get_user_memory(self, memory_id: str, table: Optional[Table] = None) -> Optional[MemoryRow]:
        """Get a memory from the database.

        Args:
            memory_id (str): The ID of the memory to get.
            table (Table): Table to read from.

        Returns:
            Optional[MemoryRow]: The memory as a MemoryRow object, or None if not found.
        """
        try:
            if table is None:
                table = self.get_user_memory_table()

            memory_raw = self.get_user_memory_raw(memory_id=memory_id, table=table)
            if memory_raw is None:
                return None

            return MemoryRow(
                id=memory_raw["memory_id"],
                user_id=memory_raw["user_id"],
                memory=memory_raw["memory"],
                last_updated=memory_raw["last_updated"],
            )

        except Exception as e:
            log_debug(f"Exception reading from table: {e}")
            return None

    def get_user_memories_raw(
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
        table: Optional[Table] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get all memories from the database as raw dictionaries.

        Args:
            user_id (Optional[str]): The ID of the user to filter by.
            agent_id (Optional[str]): The ID of the agent to filter by.
            team_id (Optional[str]): The ID of the team to filter by.
            workflow_id (Optional[str]): The ID of the workflow to filter by.
            topics (Optional[List[str]]): The topics to filter by.
            search_content (Optional[str]): The content to search for.
            limit (Optional[int]): The maximum number of memories to return.
            page (Optional[int]): The page number.
            table (Optional[Table]): The table to read from.

        Returns:
            Tuple[List[Dict[str, Any]], int]: The memories as raw dictionaries and the total number of memories.
        """
        try:
            if table is None:
                table = self.get_user_memory_table()

            # TODO: Review if we need to use begin() for read operations
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
                if topics is not None:
                    topic_conditions = [table.c.topics.contains([topic]) for topic in topics]
                    stmt = stmt.where(or_(*topic_conditions))
                if search_content is not None:
                    stmt = stmt.where(table.c.memory.ilike(f"%{search_content}%"))

                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = sess.execute(count_stmt).scalar()

                # Sorting
                stmt = self._apply_sorting(stmt, table, sort_by, sort_order)
                # Paginating
                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset(page * limit)

                result = sess.execute(stmt).fetchall()
                if not result:
                    return [], 0

                return [record._mapping for record in result], total_count

        except Exception as e:
            log_debug(f"Exception reading from table: {e}")
            return [], 0

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
        table: Optional[Table] = None,
    ) -> List[MemoryRow]:
        """Get all memories from the database as MemoryRow objects.

        Args:
            user_id (Optional[str]): The ID of the user to filter by.
            agent_id (Optional[str]): The ID of the agent to filter by.
            team_id (Optional[str]): The ID of the team to filter by.
            workflow_id (Optional[str]): The ID of the workflow to filter by.
            topics (Optional[List[str]]): The topics to filter by.
            search_content (Optional[str]): The content to search for.
            limit (Optional[int]): The maximum number of memories to return.
            page (Optional[int]): The page number.
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by.
            table (Optional[Table]): The table to read from.

        Returns:
            List[MemoryRow]: The memories as MemoryRow objects.
        """
        try:
            if table is None:
                table = self.get_user_memory_table()

            user_memories_raw, total_count = self.get_user_memories_raw(
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                workflow_id=workflow_id,
                topics=topics,
                search_content=search_content,
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order,
                table=table,
            )
            if not user_memories_raw:
                return []

            return [
                MemoryRow(
                    id=record["memory_id"],
                    user_id=record["user_id"],
                    memory=record["memory"],
                    last_updated=record["last_updated"],
                )
                for record in user_memories_raw
            ]

        except Exception as e:
            log_debug(f"Exception reading from table: {e}")
            return []

    def upsert_user_memory_raw(self, memory: MemoryRow, table: Optional[Table] = None) -> Optional[Dict[str, Any]]:
        """Upsert a user memory in the database, and return the upserted memory as a raw dictionary.

        Args:
            memory (MemoryRow): The user memory to upsert.
            table (Optional[Table]): The table to upsert into.

        Returns:
            Optional[Dict[str, Any]]: The upserted user memory, or None if the operation fails.
        """
        try:
            if table is None:
                table = self.get_user_memory_table()

            with self.Session() as sess, sess.begin():
                if memory.id is None:
                    memory.id = str(uuid4())

                stmt = postgresql.insert(table).values(
                    user_id=memory.user_id,
                    agent_id=memory.agent_id,
                    team_id=memory.team_id,
                    memory_id=memory.id,
                    memory=memory.memory,
                    topics=memory.memory.get("topics", []),
                    feedback=memory.memory.get("feedback", None),
                    last_updated=int(time.time()),
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["memory_id"],
                    set_=dict(
                        memory=memory.memory,
                        topics=memory.memory.get("topics", []),
                        feedback=memory.memory.get("feedback", None),
                        last_updated=int(time.time()),
                    ),
                ).returning(table)
                result = sess.execute(stmt)
                row = result.fetchone()
                sess.commit()

            return row._mapping

        except Exception as e:
            log_error(f"Exception upserting user memory: {e}")
            return None

    def upsert_user_memory(self, memory: MemoryRow) -> Optional[MemoryRow]:
        """Upsert a user memory in the database.

        Args:
            memory (MemoryRow): The user memory to upsert.

        Returns:
            Optional[UserMemory]: The upserted user memory, or None if the operation fails.
        """
        try:
            table = self.get_user_memory_table()

            user_memory_raw = self.upsert_user_memory_raw(memory=memory, table=table)
            if user_memory_raw is None:
                return None

            return MemoryRow(
                id=user_memory_raw["memory_id"],
                user_id=user_memory_raw["user_id"],
                agent_id=user_memory_raw["agent_id"],
                team_id=user_memory_raw["team_id"],
                memory=user_memory_raw["memory"],
                last_updated=user_memory_raw["last_updated"],
            )

        except Exception as e:
            log_error(f"Exception upserting user memory: {e}")
            return None

    def delete_user_memory(self, memory_id: str) -> bool:
        """Delete a user memory from the database.

        Returns:
            bool: True if deletion was successful, False otherwise.
        """
        try:
            table = self.get_user_memory_table()

            with self.Session() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.memory_id == memory_id)
                result = sess.execute(delete_stmt)

                success = result.rowcount > 0
                if success:
                    log_debug(f"Successfully deleted user memory id: {memory_id}")
                else:
                    log_debug(f"No user memory found with id: {memory_id}")

                return success

        except Exception as e:
            log_error(f"Error deleting user memory: {e}")
            return False

    # -- Knowledge methods --

    def delete_knowledge_document(self, knowledge_id: str):
        return

    def get_knowledge_document(self, knowledge_id: str):
        return

    def get_knowledge_documents(self, knowledge_id: str):
        return

    def upsert_knowledge_document(self, knowledge_id: str):
        return

    # -- Eval methods --

    def get_eval_table(self) -> Table:
        """Get or create the eval table."""
        if not hasattr(self, "eval_table"):
            if self.eval_table_name is None:
                raise ValueError("Eval table was not provided on initialization")
            log_info(f"Getting eval table: {self.eval_table_name}")
            self.eval_table = self.get_or_create_table(
                table_name=self.eval_table_name, table_type="evals", db_schema=self.db_schema
            )
        return self.eval_table

    def create_eval_run(self, eval_run: EvalRunRecord) -> Optional[EvalRunRecord]:
        """Create an EvalRunRecord in the database."""
        try:
            table = self.get_eval_table()

            with self.Session() as sess, sess.begin():
                stmt = postgresql.insert(table).values({"created_at": int(time.time()), **eval_run.model_dump()})
                sess.execute(stmt)
                sess.commit()

            return eval_run

        except Exception as e:
            log_error(f"Error creating eval run: {e}")
            return None

    def get_eval_run_raw(self, eval_run_id: str, table: Optional[Table] = None) -> Optional[Dict[str, Any]]:
        """Get an eval run from the database as a raw dictionary.

        Args:
            eval_run_id (str): The ID of the eval run to get.

        Returns:
            Optional[Dict[str, Any]]: The eval run as a raw dictionary, or None if not found.
        """
        try:
            if table is None:
                table = self.get_eval_table()

            with self.Session() as sess, sess.begin():
                stmt = select(table).where(table.c.run_id == eval_run_id)
                result = sess.execute(stmt).fetchone()
                if result is None:
                    return None

                return result._mapping

        except Exception as e:
            log_debug(f"Exception getting eval run {eval_run_id}: {e}")
            return None

    def get_eval_run(self, eval_run_id: str, table: Optional[Table] = None) -> Optional[EvalRunRecord]:
        """Get an eval run from the database.

        Args:
            eval_run_id (str): The ID of the eval run to get.
            table (Optional[Table]): The table to read from.

        Returns:
            Optional[EvalRunRecord]: The eval run, or None if not found.
        """
        try:
            if table is None:
                table = self.get_eval_table()

            eval_run_raw = self.get_eval_run_raw(eval_run_id=eval_run_id, table=table)
            if eval_run_raw is None:
                return None

            return EvalRunRecord.model_validate(eval_run_raw)

        except Exception as e:
            log_debug(f"Exception getting eval run {eval_run_id}: {e}")
            return None

    def get_eval_runs_raw(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        table: Optional[Table] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        model_id: Optional[str] = None,
        eval_type: Optional[EvalType] = None,
    ) -> List[Dict[str, Any]]:
        """Get all eval runs from the database as raw dictionaries.

        Args:
            limit (Optional[int]): The maximum number of eval runs to return.
            page (Optional[int]): The page number.
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by.
            table (Optional[Table]): The table to read from.
            agent_id (Optional[str]): The ID of the agent to filter by.
            team_id (Optional[str]): The ID of the team to filter by.
            workflow_id (Optional[str]): The ID of the workflow to filter by.
            model_id (Optional[str]): The ID of the model to filter by.
            eval_type (Optional[EvalType]): The type of eval to filter by.

        Returns:
            List[Dict[str, Any]]: The eval runs as raw dictionaries.
        """
        try:
            if table is None:
                table = self.get_eval_table()

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
                if eval_type is not None:
                    stmt = stmt.where(table.c.eval_type == eval_type)
                # Sorting
                stmt = self._apply_sorting(stmt, table, sort_by, sort_order)
                # Paginating
                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None:
                        stmt = stmt.offset(page * limit)

                result = sess.execute(stmt).fetchall()
                if not result:
                    return []

                return [row._mapping for row in result]

        except Exception as e:
            log_debug(f"Exception getting eval runs: {e}")
            return []

    def get_eval_runs(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        table: Optional[Table] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        model_id: Optional[str] = None,
        eval_type: Optional[EvalType] = None,
    ) -> List[EvalRunRecord]:
        """Get all eval runs from the database.

        Args:
            limit (Optional[int]): The maximum number of eval runs to return.
            page (Optional[int]): The page number.
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by.
            table (Optional[Table]): The table to read from.
            agent_id (Optional[str]): The ID of the agent to filter by.
            team_id (Optional[str]): The ID of the team to filter by.
            workflow_id (Optional[str]): The ID of the workflow to filter by.
            model_id (Optional[str]): The ID of the model to filter by.
            eval_type (Optional[EvalType]): The type of eval to filter by.

        Returns:
            List[EvalRunRecord]: The eval runs.
        """
        try:
            if table is None:
                table = self.get_eval_table()

            eval_runs_raw = self.get_eval_runs_raw(
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order,
                table=table,
                agent_id=agent_id,
                team_id=team_id,
                workflow_id=workflow_id,
                model_id=model_id,
                eval_type=eval_type,
            )
            if not eval_runs_raw:
                return []

            return [EvalRunRecord.model_validate(row) for row in eval_runs_raw]

        except Exception as e:
            log_debug(f"Exception getting eval runs: {e}")
            return []
