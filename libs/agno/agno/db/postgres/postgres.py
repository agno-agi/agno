import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from sqlalchemy import Index, UniqueConstraint

from agno.db.base import BaseDb, SessionType
from agno.db.postgres.schemas import get_table_schema_definition
from agno.db.postgres.utils import (
    apply_sorting,
    bulk_upsert_metrics,
    calculate_date_metrics,
    create_schema,
    fetch_all_sessions_data,
    get_dates_to_calculate_metrics_for,
    hydrate_session,
    is_table_available,
    is_valid_table,
)
from agno.db.schemas import MemoryRow
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info, log_warning

try:
    from sqlalchemy import and_, func, update
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.engine import Engine, create_engine
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
        session_table: Optional[str] = None,
        user_memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
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
            session_table (Optional[str]): Name of the table to store Agent, Team and Workflow sessions.
            user_memory_table (Optional[str]): Name of the table to store user memories.
            metrics_table (Optional[str]): Name of the table to store metrics.
            eval_table (Optional[str]): Name of the table to store evaluation runs data.
            knowledge_table (Optional[str]): Name of the table to store knowledge content.

        Raises:
            ValueError: If neither db_url nor db_engine is provided.
            ValueError: If none of the tables are provided.
        """
        super().__init__(
            session_table=session_table,
            user_memory_table=user_memory_table,
            metrics_table=metrics_table,
            eval_table=eval_table,
            knowledge_table=knowledge_table,
        )

        _engine: Optional[Engine] = db_engine
        if _engine is None and db_url is not None:
            _engine = create_engine(db_url)
        if _engine is None:
            raise ValueError("One of db_url or db_engine must be provided")

        self.db_url: Optional[str] = db_url
        self.db_engine: Engine = _engine
        self.db_schema: str = db_schema if db_schema is not None else "ai"
        self.metadata: MetaData = MetaData()

        # Initialize database session
        self.Session: scoped_session = scoped_session(sessionmaker(bind=self.db_engine))

    # -- DB methods --

    def _create_table(self, table_name: str, table_type: str, db_schema: str) -> Table:
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
            table_schema = get_table_schema_definition(table_type)

            log_debug(f"Creating table {db_schema}.{table_name} with schema: {table_schema}")

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
            table_metadata = MetaData(schema=db_schema)
            table = Table(table_name, table_metadata, *columns, schema=db_schema)

            # Add multi-column unique constraints
            for constraint in schema_unique_constraints:
                constraint_name = constraint["name"]
                constraint_columns = constraint["columns"]
                table.append_constraint(UniqueConstraint(*constraint_columns, name=constraint_name))

            # Add indexes to the table definition
            for idx_col in indexes:
                idx_name = f"idx_{table_name}_{idx_col}"
                table.append_constraint(Index(idx_name, idx_col))

            with self.Session() as sess, sess.begin():
                create_schema(session=sess, db_schema=db_schema)

            # Create table
            table_without_indexes = Table(
                table_name,
                MetaData(schema=db_schema),
                *[c.copy() for c in table.columns],
                *[c for c in table.constraints if not isinstance(c, Index)],
                schema=db_schema,
            )
            table_without_indexes.create(self.db_engine, checkfirst=True)

            # Create indexes
            for idx in table.indexes:
                try:
                    log_debug(f"Creating index: {idx.name}")

                    # Check if index already exists
                    with self.Session() as sess:
                        exists_query = text(
                            "SELECT 1 FROM pg_indexes WHERE schemaname = :schema AND indexname = :index_name"
                        )
                        exists = (
                            sess.execute(exists_query, {"schema": db_schema, "index_name": idx.name}).scalar()
                            is not None
                        )
                        if exists:
                            log_debug(f"Index {idx.name} already exists in {db_schema}.{table_name}, skipping creation")
                            continue

                    idx.create(self.db_engine)

                except Exception as e:
                    log_warning(f"Error creating index {idx.name}: {e}")

            log_info(f"Successfully created table {db_schema}.{table_name}")
            return table

        except Exception as e:
            log_error(f"Could not create table {db_schema}.{table_name}: {e}")
            raise

    def _get_table(self, table_type: str) -> Table:
        if table_type == "sessions":
            if not hasattr(self, "session_table"):
                if self.session_table_name is None:
                    raise ValueError("Session table was not provided on initialization")

                self.session_table = self._get_or_create_table(
                    table_name=self.session_table_name, table_type="sessions", db_schema=self.db_schema
                )
            return self.session_table

        if table_type == "user_memories":
            if not hasattr(self, "user_memory_table"):
                if self.user_memory_table_name is None:
                    raise ValueError("User memory table was not provided on initialization")

                self.user_memory_table = self._get_or_create_table(
                    table_name=self.user_memory_table_name, table_type="user_memories", db_schema=self.db_schema
                )
            return self.user_memory_table

        if table_type == "metrics":
            if not hasattr(self, "metrics_table"):
                if self.metrics_table_name is None:
                    raise ValueError("Metrics table was not provided on initialization")

                self.metrics_table = self._get_or_create_table(
                    table_name=self.metrics_table_name, table_type="metrics", db_schema=self.db_schema
                )
            return self.metrics_table

        if table_type == "evals":
            if not hasattr(self, "eval_table"):
                if self.eval_table_name is None:
                    raise ValueError("Eval table was not provided on initialization")

                self.eval_table = self._get_or_create_table(
                    table_name=self.eval_table_name, table_type="evals", db_schema=self.db_schema
                )
            return self.eval_table

        if table_type == "knowledge":
            if not hasattr(self, "knowledge_table"):
                if self.knowledge_table_name is None:
                    raise ValueError("Knowledge table was not provided on initialization")

                self.knowledge_table = self._get_or_create_table(
                    table_name=self.knowledge_table_name, table_type="knowledge", db_schema=self.db_schema
                )
            return self.knowledge_table

        raise ValueError(f"Unknown table type: {table_type}")

    def _get_or_create_table(self, table_name: str, table_type: str, db_schema: str) -> Table:
        """
        Check if the table exists and is valid, else create it.

        Args:
            table_name (str): Name of the table to get or create
            table_type (str): Type of table (used to get schema definition)
            db_schema (str): Database schema name

        Returns:
            Table: SQLAlchemy Table object representing the schema.
        """

        with self.Session() as sess, sess.begin():
            table_is_available = is_table_available(session=sess, table_name=table_name, db_schema=db_schema)

        if not table_is_available:
            return self._create_table(table_name=table_name, table_type=table_type, db_schema=db_schema)

        if not is_valid_table(
            db_engine=self.db_engine,
            table_name=table_name,
            table_type=table_type,
            db_schema=db_schema,
        ):
            raise ValueError(f"Table {db_schema}.{table_name} has an invalid schema")

        try:
            table = Table(table_name, self.metadata, schema=db_schema, autoload_with=self.db_engine)
            log_debug(f"Loaded existing table {db_schema}.{table_name}")
            return table

        except Exception as e:
            log_error(f"Error loading existing table {db_schema}.{table_name}: {e}")
            raise

    # -- Session methods --

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session from the database.

        Args:
            session_id (str): ID of the session to delete

        Returns:
            bool: True if the session was deleted, False otherwise.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = self._get_table(table_type="sessions")

            with self.Session() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.session_id == session_id)
                result = sess.execute(delete_stmt)
                if result.rowcount == 0:
                    log_debug(f"No session found to delete with session_id: {session_id} in table {table.name}")
                    return False
                else:
                    log_debug(f"Successfully deleted session with session_id: {session_id} in table {table.name}")
                    return True

        except Exception as e:
            log_error(f"Error deleting session: {e}")
            return False

    def delete_sessions(self, session_ids: List[str]) -> None:
        """Delete all given sessions from the database.
        Can handle multiple session types in the same run.

        Args:
            session_ids (List[str]): The IDs of the sessions to delete.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = self._get_table(table_type="sessions")

            with self.Session() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.session_id.in_(session_ids))
                result = sess.execute(delete_stmt)

            log_debug(f"Successfully deleted {result.rowcount} sessions")

        except Exception as e:
            log_error(f"Error deleting sessions: {e}")

    def get_session(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        session_type: Optional[SessionType] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[AgentSession, TeamSession, WorkflowSession, Dict[str, Any]]]:
        """
        Read a session from the database.

        Args:
            session_id (str): ID of the session to read.
            user_id (Optional[str]): User ID to filter by. Defaults to None.
            session_type (Optional[SessionType]): Type of session to read. Defaults to None.
            deserialize (Optional[bool]): Whether to serialize the session. Defaults to True.

        Returns:
            Union[Session, Dict[str, Any], None]:
                - When deserialize=True: Session object
                - When deserialize=False: Session dictionary

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table = self._get_table(table_type="sessions")

            with self.Session() as sess:
                stmt = select(table).where(table.c.session_id == session_id)

                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                if session_type is not None:
                    session_type_value = session_type.value if isinstance(session_type, SessionType) else session_type
                    stmt = stmt.where(table.c.session_type == session_type_value)
                result = sess.execute(stmt).fetchone()
                if result is None:
                    return None

                session = hydrate_session(dict(result._mapping))

            if not deserialize:
                return session

            if session_type == SessionType.AGENT:
                return AgentSession.from_dict(session)
            elif session_type == SessionType.TEAM:
                return TeamSession.from_dict(session)
            elif session_type == SessionType.WORKFLOW:
                return WorkflowSession.from_dict(session)

        except Exception as e:
            log_debug(f"Exception reading from session table: {e}")
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
    ) -> Union[List[AgentSession], List[TeamSession], List[WorkflowSession], Tuple[List[Dict[str, Any]], int]]:
        """
        Get all sessions in the given table. Can filter by user_id and entity_id.

        Args:
            user_id (Optional[str]): The ID of the user to filter by.
            entity_id (Optional[str]): The ID of the agent / workflow to filter by.
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
        try:
            table = self._get_table(table_type="sessions")

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
                        func.coalesce(func.json_extract_path_text(table.c.session_data, "session_name"), "").ilike(
                            f"%{session_name}%"
                        )
                    )
                if session_type is not None:
                    session_type_value = session_type.value if isinstance(session_type, SessionType) else session_type
                    stmt = stmt.where(table.c.session_type == session_type_value)

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

                session = [hydrate_session(dict(record._mapping)) for record in records]
                if not deserialize:
                    return session, total_count

            if session_type == SessionType.AGENT:
                return [AgentSession.from_dict(record) for record in session]  # type: ignore
            elif session_type == SessionType.TEAM:
                return [TeamSession.from_dict(record) for record in session]  # type: ignore
            elif session_type == SessionType.WORKFLOW:
                return [WorkflowSession.from_dict(record) for record in session]  # type: ignore
            else:
                raise ValueError(f"Invalid session type: {session_type}")

        except Exception as e:
            log_debug(f"Exception reading from session table: {e}")
            return []

    def rename_session(
        self, session_id: str, session_type: SessionType, session_name: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """
        Rename a session in the database.

        Args:
            session_id (str): The ID of the session to rename.
            session_type (SessionType): The type of session to rename.
            session_name (str): The new name for the session.
            deserialize (Optional[bool]): Whether to serialize the session. Defaults to True.

        Returns:
            Optional[Union[Session, Dict[str, Any]]]:
                - When deserialize=True: Session object
                - When deserialize=False: Session dictionary

        Raises:
            Exception: If an error occurs during renaming.
        """
        try:
            table = self._get_table(table_type="sessions")

            with self.Session() as sess, sess.begin():
                stmt = (
                    update(table)
                    .where(table.c.session_id == session_id)
                    .values(
                        session_data=func.cast(
                            func.jsonb_set(
                                func.cast(table.c.session_data, postgresql.JSONB),
                                text("'{session_name}'"),
                                func.to_jsonb(session_name),
                            ),
                            postgresql.JSON,
                        )
                    )
                    .returning(*table.c)
                )
                result = sess.execute(stmt)
                row = result.fetchone()
                if not row:
                    return None

            session = hydrate_session(dict(row._mapping))
            if not deserialize:
                return session

            # Return the appropriate session type
            if session_type == SessionType.AGENT:
                return AgentSession.from_dict(session)
            elif session_type == SessionType.TEAM:
                return TeamSession.from_dict(session)
            elif session_type == SessionType.WORKFLOW:
                return WorkflowSession.from_dict(session)

        except Exception as e:
            log_error(f"Exception renaming session: {e}")
            return None

    def upsert_session(self, session: Session, deserialize: Optional[bool] = True) -> Optional[Session]:
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
            table = self._get_table(table_type="sessions")
            session_dict = session.to_dict()

            if isinstance(session, AgentSession):
                with self.Session() as sess, sess.begin():
                    stmt = postgresql.insert(table).values(
                        session_id=session_dict.get("session_id"),
                        session_type=SessionType.AGENT.value,
                        agent_id=session_dict.get("agent_id"),
                        team_session_id=session_dict.get("team_session_id"),
                        user_id=session_dict.get("user_id"),
                        runs=session_dict.get("runs"),
                        agent_data=session_dict.get("agent_data"),
                        session_data=session_dict.get("session_data"),
                        chat_history=session_dict.get("chat_history"),
                        summary=session_dict.get("summary"),
                        extra_data=session_dict.get("extra_data"),
                        created_at=session_dict.get("created_at"),
                        updated_at=session_dict.get("created_at"),
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["session_id", "agent_id"],
                        set_=dict(
                            agent_id=session_dict.get("agent_id"),
                            team_session_id=session_dict.get("team_session_id"),
                            user_id=session_dict.get("user_id"),
                            agent_data=session_dict.get("agent_data"),
                            session_data=session_dict.get("session_data"),
                            chat_history=session_dict.get("chat_history"),
                            summary=session_dict.get("summary"),
                            extra_data=session_dict.get("extra_data"),
                            runs=session_dict.get("runs"),
                            updated_at=int(time.time()),
                        ),
                    ).returning(table)
                    result = sess.execute(stmt)
                    row = result.fetchone()
                    session = row._mapping
                    if session is None or not deserialize:
                        return session
                    return AgentSession.from_dict(session)

            elif isinstance(session, TeamSession):
                with self.Session() as sess, sess.begin():
                    stmt = postgresql.insert(table).values(
                        session_id=session_dict.get("session_id"),
                        session_type=SessionType.TEAM.value,
                        team_id=session_dict.get("team_id"),
                        team_session_id=session_dict.get("team_session_id"),
                        user_id=session_dict.get("user_id"),
                        runs=session_dict.get("runs"),
                        team_data=session_dict.get("team_data"),
                        session_data=session_dict.get("session_data"),
                        summary=session_dict.get("summary"),
                        extra_data=session_dict.get("extra_data"),
                        chat_history=session_dict.get("chat_history"),
                        created_at=session_dict.get("created_at"),
                        updated_at=session_dict.get("created_at"),
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["session_id", "team_id"],
                        set_=dict(
                            team_id=session_dict.get("team_id"),
                            team_session_id=session_dict.get("team_session_id"),
                            user_id=session_dict.get("user_id"),
                            team_data=session_dict.get("team_data"),
                            session_data=session_dict.get("session_data"),
                            summary=session_dict.get("summary"),
                            extra_data=session_dict.get("extra_data"),
                            runs=session_dict.get("runs"),
                            chat_history=session_dict.get("chat_history"),
                            updated_at=int(time.time()),
                        ),
                    ).returning(table)
                    result = sess.execute(stmt)
                    row = result.fetchone()
                    session = row._mapping
                    if session is None or not deserialize:
                        return session
                    return TeamSession.from_dict(session)

            elif isinstance(session, WorkflowSession):
                with self.Session() as sess, sess.begin():
                    stmt = postgresql.insert(table).values(
                        session_id=session_dict.get("session_id"),
                        session_type=SessionType.WORKFLOW.value,
                        workflow_id=session_dict.get("workflow_id"),
                        user_id=session_dict.get("user_id"),
                        runs=session_dict.get("runs"),
                        workflow_data=session_dict.get("workflow_data"),
                        session_data=session_dict.get("session_data"),
                        summary=session_dict.get("summary"),
                        extra_data=session_dict.get("extra_data"),
                        chat_history=session_dict.get("chat_history"),
                        created_at=session_dict.get("created_at"),
                        updated_at=session_dict.get("created_at"),
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["session_id", "workflow_id"],
                        set_=dict(
                            workflow_id=session_dict.get("workflow_id"),
                            user_id=session_dict.get("user_id"),
                            workflow_data=session_dict.get("workflow_data"),
                            session_data=session_dict.get("session_data"),
                            summary=session_dict.get("summary"),
                            extra_data=session_dict.get("extra_data"),
                            runs=session_dict.get("runs"),
                            chat_history=session_dict.get("chat_history"),
                            updated_at=int(time.time()),
                        ),
                    ).returning(table)
                    result = sess.execute(stmt)
                    row = result.fetchone()
                    session = row._mapping
                    if session is None or not deserialize:
                        return session
                    return WorkflowSession.from_dict(session)

        except Exception as e:
            log_warning(f"Exception upserting into sessions table: {e}")
            return None

    # -- Memory methods --

    def delete_user_memory(self, memory_id: str) -> bool:
        """Delete a user memory from the database.

        Returns:
            bool: True if deletion was successful, False otherwise.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = self._get_table(table_type="user_memories")

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

    def delete_user_memories(self, memory_ids: List[str]) -> None:
        """Delete user memories from the database.

        Args:
            memory_ids (List[str]): The IDs of the memories to delete.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = self._get_table(table_type="user_memories")

            with self.Session() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.memory_id.in_(memory_ids))
                result = sess.execute(delete_stmt)
                if result.rowcount == 0:
                    log_debug(f"No user memories found with ids: {memory_ids}")

        except Exception as e:
            log_error(f"Error deleting user memories: {e}")

    def get_all_memory_topics(self) -> List[str]:
        """Get all memory topics from the database.

        Returns:
            List[str]: List of memory topics.
        """
        try:
            table = self._get_table(table_type="user_memories")

            with self.Session() as sess, sess.begin():
                stmt = select(func.json_array_elements_text(table.c.topics))
                result = sess.execute(stmt).fetchall()
                return [record[0] for record in result]

        except Exception as e:
            log_debug(f"Exception reading from memory table: {e}")
            return []

    def get_user_memory(self, memory_id: str, deserialize: Optional[bool] = True) -> Optional[MemoryRow]:
        """Get a memory from the database.

        Args:
            memory_id (str): The ID of the memory to get.
            deserialize (Optional[bool]): Whether to serialize the memory. Defaults to True.

        Returns:
            Union[MemoryRow, Dict[str, Any], None]:
                - When deserialize=True: MemoryRow object
                - When deserialize=False: Memory dictionary

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table = self._get_table(table_type="user_memories")

            with self.Session() as sess, sess.begin():
                stmt = select(table).where(table.c.memory_id == memory_id)

                result = sess.execute(stmt).fetchone()
                if not result:
                    return None

                memory_raw = result._mapping
                if not deserialize:
                    return memory_raw

            return MemoryRow(
                id=memory_raw["memory_id"],
                user_id=memory_raw["user_id"],
                memory=memory_raw["memory"],
                last_updated=memory_raw["last_updated"],
            )

        except Exception as e:
            log_debug(f"Exception reading from memory table: {e}")
            return None

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
        deserialize: Optional[bool] = True,
    ) -> Union[List[MemoryRow], Tuple[List[Dict[str, Any]], int]]:
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
            deserialize (Optional[bool]): Whether to serialize the memories. Defaults to True.

        Returns:
            Union[List[MemoryRow], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of MemoryRow objects
                - When deserialize=False: Tuple of (memory dictionaries, total count)

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table = self._get_table(table_type="user_memories")

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
                    topic_conditions = [text(f"topics::text LIKE '%\"{topic}\"%'") for topic in topics]
                    stmt = stmt.where(and_(*topic_conditions))
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

                user_memories_raw = [record._mapping for record in result]
                if not deserialize:
                    return user_memories_raw, total_count

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
            log_debug(f"Exception reading from memory table: {e}")
            return []

    def get_user_memory_stats(
        self, limit: Optional[int] = None, page: Optional[int] = None
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
        try:
            table = self._get_table(table_type="user_memories")

            with self.Session() as sess, sess.begin():
                stmt = (
                    select(
                        table.c.user_id,
                        func.count(table.c.memory_id).label("total_memories"),
                        func.max(table.c.last_updated).label("last_memory_updated_at"),
                    )
                    .where(table.c.user_id.is_not(None))
                    .group_by(table.c.user_id)
                    .order_by(func.max(table.c.last_updated).desc())
                )

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
            log_debug(f"Exception getting user memory stats: {e}")
            return [], 0

    def upsert_user_memory(
        self, memory: MemoryRow, deserialize: Optional[bool] = True
    ) -> Optional[Union[MemoryRow, Dict[str, Any]]]:
        """Upsert a user memory in the database.

        Args:
            memory (MemoryRow): The user memory to upsert.
            deserialize (Optional[bool]): Whether to serialize the memory. Defaults to True.

        Returns:
            Optional[Union[MemoryRow, Dict[str, Any]]]:
                - When deserialize=True: MemoryRow object
                - When deserialize=False: Memory dictionary

        Raises:
            Exception: If an error occurs during upsert.
        """
        try:
            table = self._get_table(table_type="user_memories")

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

            user_memory_raw = row._mapping
            if not user_memory_raw or not deserialize:
                return user_memory_raw

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

            with self.Session() as sess:
                result = sess.execute(stmt).fetchall()
                return [record._mapping for record in result]

        except Exception as e:
            log_debug(f"Exception reading from sessions table: {e}")
            return []

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
            stmt = select(table).order_by(table.c.date.desc()).limit(1)
            result = sess.execute(stmt).fetchone()

            # 1. Return the date of the first day without a complete metrics record.
            if result is not None:
                if result.completed:
                    return result._mapping["date"] + timedelta(days=1)
                else:
                    return result._mapping["date"]

        # 2. No metrics records. Return the date of the first recorded session.
        first_session, _ = self.get_sessions(sort_by="created_at", sort_order="asc", limit=1, deserialize=False)
        first_session_date = first_session[0]["created_at"] if first_session else None

        # 3. No metrics records and no sessions records. Return None.
        if first_session_date is None:
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
            table = self._get_table(table_type="metrics")

            starting_date = self._get_metrics_calculation_starting_date(table)
            if starting_date is None:
                log_info("No session data found. Won't calculate metrics.")
                return None

            dates_to_process = get_dates_to_calculate_metrics_for(starting_date)
            if not dates_to_process:
                log_info("Metrics already calculated for all relevant dates.")
                return None

            start_timestamp = int(datetime.combine(dates_to_process[0], datetime.min.time()).timestamp())
            end_timestamp = int(
                datetime.combine(dates_to_process[-1] + timedelta(days=1), datetime.min.time()).timestamp()
            )

            sessions = self._get_all_sessions_for_metrics_calculation(
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

                metrics_record = calculate_date_metrics(date_to_process, sessions_for_date)
                metrics_records.append(metrics_record)

            if metrics_records:
                with self.Session() as sess, sess.begin():
                    results = bulk_upsert_metrics(session=sess, table=table, metrics_records=metrics_records)

            return results

        except Exception as e:
            log_error(f"Exception refreshing metrics: {e}")
            raise e

    def get_metrics(
        self, starting_date: Optional[date] = None, ending_date: Optional[date] = None
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
            table = self._get_table(table_type="metrics")

            with self.Session() as sess, sess.begin():
                stmt = select(table)
                if starting_date:
                    stmt = stmt.where(table.c.date >= starting_date)
                if ending_date:
                    stmt = stmt.where(table.c.date <= ending_date)
                result = sess.execute(stmt).fetchall()
                if not result:
                    return [], None

                # Get the latest updated_at
                latest_stmt = select(func.max(table.c.updated_at))
                latest_updated_at = sess.execute(latest_stmt).scalar()

            return [row._mapping for row in result], latest_updated_at

        except Exception as e:
            log_error(f"Exception getting metrics: {e}")
            return [], None

    # -- Knowledge methods --

    def _get_knowledge_table(self) -> Table:
        """Get or create the knowledge table.

        Returns:
            Table: The knowledge table.
        """
        if not hasattr(self, "knowledge_table"):
            if self.knowledge_table_name is None:
                raise ValueError("Knowledge table was not provided on initialization")

            log_info(f"Getting knowledge table: {self.knowledge_table_name}")
            self.knowledge_table = self._get_or_create_table(
                table_name=self.knowledge_table_name, table_type="knowledge_contents", db_schema=self.db_schema
            )

        return self.knowledge_table

    def delete_knowledge_content(self, id: str):
        table = self._get_knowledge_table()
        with self.Session() as sess, sess.begin():
            stmt = table.delete().where(table.c.id == id)
            sess.execute(stmt)

        return

    def get_knowledge_content(self, id: str) -> Optional[KnowledgeRow]:
        table = self._get_knowledge_table()
        print(f"Getting knowledge content: {id}, {table}")
        with self.Session() as sess, sess.begin():
            stmt = select(table).where(table.c.id == id)
            result = sess.execute(stmt).fetchone()
            if result is None:
                return None
            return KnowledgeRow.model_validate(result._mapping)

    def get_knowledge_contents(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> Tuple[List[KnowledgeRow], int]:
        """Get all knowledge contents from the database.

        Args:
            limit (Optional[int]): The maximum number of knowledge contents to return.
            page (Optional[int]): The page number.
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by.

        Returns:
            List[KnowledgeRow]: The knowledge contents.
        """
        table = self._get_knowledge_table()
        with self.Session() as sess, sess.begin():
            stmt = select(table)

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

    def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        """Upsert knowledge content in the database.

        Args:
            knowledge_row (KnowledgeRow): The knowledge row to upsert.

        Returns:
            Optional[KnowledgeRow]: The upserted knowledge row, or None if the operation fails.
        """
        try:
            table = self._get_knowledge_table()
            with self.Session() as sess, sess.begin():
                # Only include fields that are not None in the update
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
                    }.items()
                    if v is not None
                }

                stmt = (
                    postgresql.insert(table)
                    .values(knowledge_row.model_dump())
                    .on_conflict_do_update(index_elements=["id"], set_=update_fields)
                )
                sess.execute(stmt)

            return knowledge_row

        except Exception as e:
            log_error(f"Error upserting knowledge row: {e}")
            return None

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
            table = self._get_table(table_type="evals")

            with self.Session() as sess, sess.begin():
                current_time = int(time.time())
                stmt = postgresql.insert(table).values(
                    {"created_at": current_time, "updated_at": current_time, **eval_run.model_dump()}
                )
                sess.execute(stmt)

            return eval_run

        except Exception as e:
            log_error(f"Error creating eval run: {e}")
            return None

    def delete_eval_run(self, eval_run_id: str) -> None:
        """Delete an eval run from the database.

        Args:
            eval_run_id (str): The ID of the eval run to delete.
        """
        try:
            table = self._get_table(table_type="evals")

            with self.Session() as sess, sess.begin():
                stmt = table.delete().where(table.c.run_id == eval_run_id)
                result = sess.execute(stmt)
                if result.rowcount == 0:
                    log_warning(f"No eval run found with ID: {eval_run_id}")
                else:
                    log_debug(f"Deleted eval run with ID: {eval_run_id}")

        except Exception as e:
            log_debug(f"Error deleting eval run {eval_run_id}: {e}")
            raise

    def delete_eval_runs(self, eval_run_ids: List[str]) -> None:
        """Delete multiple eval runs from the database.

        Args:
            eval_run_ids (List[str]): List of eval run IDs to delete.
        """
        try:
            table = self._get_table(table_type="evals")

            with self.Session() as sess, sess.begin():
                stmt = table.delete().where(table.c.run_id.in_(eval_run_ids))
                result = sess.execute(stmt)
                if result.rowcount == 0:
                    log_warning(f"No eval runs found with IDs: {eval_run_ids}")
                else:
                    log_debug(f"Deleted {result.rowcount} eval runs")

        except Exception as e:
            log_debug(f"Error deleting eval runs {eval_run_ids}: {e}")
            raise

    def get_eval_run(
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
            table = self._get_table(table_type="evals")

            with self.Session() as sess, sess.begin():
                stmt = select(table).where(table.c.run_id == eval_run_id)
                result = sess.execute(stmt).fetchone()
                if result is None:
                    return None

                eval_run_raw = result._mapping
                if not deserialize:
                    return eval_run_raw

                return EvalRunRecord.model_validate(eval_run_raw)

        except Exception as e:
            log_debug(f"Exception getting eval run {eval_run_id}: {e}")
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
        eval_type: Optional[List[EvalType]] = None,
        filter_type: Optional[EvalFilterType] = None,
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

        Returns:
            Union[List[EvalRunRecord], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of EvalRunRecord objects
                - When deserialize=False: List of dictionaries

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table = self._get_table(table_type="evals")

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
                    return [] if serialize else ([], 0)

                eval_runs_raw = [row._mapping for row in result]
                if not deserialize:
                    return eval_runs_raw, total_count

                return [EvalRunRecord.model_validate(row) for row in eval_runs_raw]

        except Exception as e:
            log_debug(f"Exception getting eval runs: {e}")
            return []

    def rename_eval_run(
        self, eval_run_id: str, name: str, serialize: bool = True
    ) -> Optional[Union[EvalRunRecord, Dict[str, Any]]]:
        """Upsert the name of an eval run in the database, returning raw dictionary.

        Args:
            eval_run_id (str): The ID of the eval run to update.
            name (str): The new name of the eval run.

        Returns:
            Optional[Dict[str, Any]]: The updated eval run, or None if the operation fails.

        Raises:
            Exception: If an error occurs during update.
        """
        try:
            table = self._get_table(table_type="evals")
            with self.Session() as sess, sess.begin():
                stmt = (
                    table.update().where(table.c.run_id == eval_run_id).values(name=name, updated_at=int(time.time()))
                )
                sess.execute(stmt)

            eval_run_raw = self.get_eval_run(eval_run_id=eval_run_id, serialize=serialize)
            if not eval_run_raw or not deserialize:
                return eval_run_raw

            return EvalRunRecord.model_validate(eval_run_raw)

        except Exception as e:
            log_debug(f"Error upserting eval run name {eval_run_id}: {e}")
            raise
