import time
from typing import Any, List, Optional

from agno.db.base import BaseDb
from agno.storage.session import AgentSession
from agno.utils.log import log_debug, log_info, log_warning, logger

try:
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.engine import Engine, create_engine
    from sqlalchemy.inspection import inspect
    from sqlalchemy.orm import scoped_session, sessionmaker
    from sqlalchemy.schema import Column, MetaData, Table
    from sqlalchemy.sql.expression import select, text
    from sqlalchemy.types import JSON, BigInteger, String
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


class PostgresDb(BaseDb):
    def __init__(
        self,
        db_engine: Optional[Engine] = None,
        db_schema: Optional[str] = None,
        db_url: Optional[str] = None,
        agent_sessions: Optional[str] = None,
        team_sessions: Optional[str] = None,
        workflow_sessions: Optional[str] = None,
        memories: Optional[str] = None,
        learnings: Optional[str] = None,
        evals: Optional[str] = None,
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
            agent_sessions (Optional[str]): Name of the table to store Agent sessions.
            team_sessions (Optional[str]): Name of the table to store Team sessions.
            workflow_sessions (Optional[str]): Name of the table to store Workflow sessions.
            memories (Optional[str]): Name of the table to store user memories.
            learnings (Optional[str]): Name of the table to store learnings.
            evals (Optional[str]): Name of the table to store eval runs.

        Raises:
            ValueError: If neither db_url nor db_engine is provided.
            ValueError: If none of the tables are provided.
        """
        super().__init__(
            agent_sessions=agent_sessions,
            team_sessions=team_sessions,
            workflow_sessions=workflow_sessions,
            memories=memories,
            learnings=learnings,
            evals=evals,
        )

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
        # Database session
        self.Session: scoped_session = scoped_session(sessionmaker(bind=self.db_engine))

        # Setup tables
        self.agent_sessions: Optional[Table] = (
            self.get_or_create_table(
                table_name=self.agent_sessions, table_type="agent_sessions", db_schema=self.db_schema
            )
            if self.agent_sessions is not None
            else None
        )
        self.team_sessions: Optional[Table] = (
            self.get_or_create_table(
                table_name=self.team_sessions, table_type="team_sessions", db_schema=self.db_schema
            )
            if self.team_sessions is not None
            else None
        )
        self.workflow_sessions: Optional[Table] = (
            self.get_or_create_table(
                table_name=self.workflow_sessions, table_type="workflow_sessions", db_schema=self.db_schema
            )
            if self.workflow_sessions is not None
            else None
        )
        self.memories: Optional[Table] = (
            self.get_or_create_table(table_name=self.memories, table_type="memories", db_schema=self.db_schema)
            if self.memories is not None
            else None
        )
        self.learnings: Optional[Table] = (
            self.get_or_create_table(
                table_name=self.learnings, table_type="learnings", db_schema=self.db_schema
            )
            if self.learnings is not None
            else None
        )
        self.evals: Optional[Table] = (
            self.get_or_create_table(
                table_name=self.evals, table_type="eval_runs", db_schema=self.db_schema
            )
            if self.evals is not None
            else None
        )

        log_debug("Created PostgresDb")

    # TODO: the schemas should live together with the app layer classes
    def _get_table_schema_definition(self, table_type: str) -> dict[str, Any]:
        """
        Get the expected schema definition for a given table name.

        Returns:
            Dict[str, Any]: Dictionary containing column definitions for the table
        """
        schemas = {
            # Agent sessions table schema
            "agent_sessions": {
                "session_id": {"type": String, "primary_key": True, "nullable": False},
                "agent_id": {"type": String, "nullable": False},
                "user_id": {"type": String, "nullable": True},
                "team_session_id": {"type": String, "nullable": True},
                "session_data": {"type": JSON, "nullable": True},
                "extra_data": {"type": JSON, "nullable": True},
                "created_at": {"type": BigInteger, "nullable": False},
                "updated_at": {"type": BigInteger, "nullable": True},
                "agent_data": {"type": JSON, "nullable": True},
                "chat_history": {"type": JSON, "nullable": True},
                "runs": {"type": JSON, "nullable": True},
                "summary": {"type": JSON, "nullable": True},
            },
            "team_sessions": {
                "session_id": {"type": String, "primary_key": True, "nullable": False},
                "team_id": {"type": String, "nullable": False},
                "user_id": {"type": String, "nullable": True},
                "team_session_id": {"type": String, "nullable": True},
                "memory": {"type": JSON, "nullable": True},
                "team_data": {"type": JSON, "nullable": True},
                "session_data": {"type": JSON, "nullable": True},
                "extra_data": {"type": JSON, "nullable": True},
                "created_at": {"type": BigInteger, "nullable": False},
                "updated_at": {"type": BigInteger, "nullable": True},
                "chat_history": {"type": JSON, "nullable": True},
                "runs": {"type": JSON, "nullable": True},
                "summary": {"type": JSON, "nullable": True},
            },
            "workflow_sessions": {
                "session_id": {"type": String, "primary_key": True, "nullable": False},
                "workflow_id": {"type": String, "nullable": False},
                "user_id": {"type": String, "nullable": True},
                "memory": {"type": JSON, "nullable": True},
                "workflow_data": {"type": JSON, "nullable": True},
                "session_data": {"type": JSON, "nullable": True},
                "extra_data": {"type": JSON, "nullable": True},
                "created_at": {"type": BigInteger, "nullable": False},
                "updated_at": {"type": BigInteger, "nullable": True},
                "chat_history": {"type": JSON, "nullable": True},
                "runs": {"type": JSON, "nullable": True},
                "summary": {"type": JSON, "nullable": True},
            },
            "memories": {},
            "learnings": {},
            "evals": {},
        }

        for schema_key, schema_def in schemas.items():
            if schema_key in table_type.lower() or table_type.lower().endswith(schema_key):
                return schema_def

        raise ValueError(f"Unknown table type: {table_type}")

    # TODO: do we need to carry these Table objects?
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
            logger.error(f"Error loading existing table {db_schema}.{table_name}: {e}")
            raise

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
            expected_table_schema = self._get_table_schema_definition(table_type)
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
            logger.error(f"Error validating table schema for {db_schema}.{table_name}: {e}")
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
            logger.error(f"Error checking if table exists: {e}")
            return False

    def _create_schema(self, db_schema: str) -> None:
        """Create the database schema if it doesn't exist."""
        try:
            with self.Session() as sess, sess.begin():
                log_debug(f"Creating schema if not exists: {db_schema}")
                sess.execute(text(f"CREATE SCHEMA IF NOT EXISTS {db_schema};"))
        except Exception as e:
            logger.warning(f"Could not create schema {db_schema}: {e}")

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
            table_schema = self._get_table_schema_definition(table_type)

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
            self._create_schema(db_schema=db_schema)

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
                    logger.warning(f"Error creating index {idx.name}: {e}")

            log_info(f"Successfully created table {db_schema}.{table_name}")
            return table

        except Exception as e:
            logger.error(f"Could not create table {db_schema}.{table_name}: {e}")
            raise

    def get_session(self, session_id: str, user_id: Optional[str] = None) -> Optional[AgentSession]:
        """
        Read a Session from the database.

        Args:
            table (Table): Table to read from.
            session_id (str): ID of the session to read.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Returns:
            Optional[Session]: Session object if found, None otherwise.
        """
        try:
            with self.Session() as sess:
                stmt = select(self.agent_sessions).where(self.agent_sessions.c.session_id == session_id)
                if user_id:
                    stmt = stmt.where(self.agent_sessions.c.user_id == user_id)
                result = sess.execute(stmt).fetchone()
                log_info(f"Result: {AgentSession.from_dict(result._mapping)}")
                return AgentSession.from_dict(result._mapping) if result is not None else None

        except Exception as e:
            log_debug(f"Exception reading from table: {e}")
        return None

    def get_all_session_ids(
        self, table: Table, user_id: Optional[str] = None, entity_id: Optional[str] = None
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

    def get_sessions(
        self,
        table: Table,
        user_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[AgentSession]:
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
            with self.Session() as sess, sess.begin():
                stmt = select(table)

                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                if entity_id is not None:
                    stmt = stmt.where(table.c.agent_id == entity_id)
                if limit is not None:
                    stmt = stmt.limit(limit)
                stmt = stmt.order_by(table.c.created_at.desc())

                rows = sess.execute(stmt).fetchall()
                if rows is not None:
                    return [AgentSession.from_dict(row._mapping) for row in rows]  # type: ignore
                else:
                    return []
        except Exception as e:
            log_debug(f"Exception reading from table: {e}")
            return []

    def upsert_agent_session(self, session: AgentSession) -> Optional[AgentSession]:
        """
        Insert or update an AgentSession in the database.

        Args:
            session (Session): The session data to upsert.
            table (Table): Table to upsert into.
            create_and_retry (bool): Retry upsert if table does not exist.

        Returns:
            Optional[AgentSession]: The upserted AgentSession, or None if operation failed.
        """

        try:
            with self.Session() as sess, sess.begin():
                stmt = postgresql.insert(self.agent_sessions).values(
                    session_id=session.session_id,
                    agent_id=session.agent_id,  # type: ignore
                    team_session_id=session.team_session_id,  # type: ignore
                    user_id=session.user_id,
                    agent_data=session.agent_data,  # type: ignore
                    session_data=session.session_data,
                    runs=session.runs,
                    summary=session.summary,
                    extra_data=session.extra_data,
                    created_at=int(time.time()),
                    updated_at=int(time.time()),
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["session_id"],
                    set_=dict(
                        agent_id=session.agent_id,  # type: ignore
                        team_session_id=session.team_session_id,  # type: ignore
                        user_id=session.user_id,
                        agent_data=session.agent_data,  # type: ignore
                        session_data=session.session_data,
                        runs=session.runs,
                        summary=session.summary,
                        extra_data=session.extra_data,
                        updated_at=int(time.time()),
                    ),
                )

                sess.execute(stmt)

            return self.get_session(session_id=session.session_id)
        except Exception as e:
            log_warning(f"Exception upserting into table: {e}")
            return None

    def delete_session(self, table: Table, session_id: str) -> None:
        """
        Delete a Session from the database.

        Args:
            table (Table): Table to delete from.
            session_id (str): ID of the session to delete

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            with self.Session() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.session_id == session_id)
                result = sess.execute(delete_stmt)
                if result.rowcount == 0:
                    log_debug(f"No session found with session_id: {session_id} in table {table.name}")
                else:
                    log_debug(f"Successfully deleted session with session_id: {session_id} in table {table.name}")
        except Exception as e:
            logger.error(f"Error deleting session: {e}")