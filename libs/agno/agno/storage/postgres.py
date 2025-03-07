import time
from typing import List, Literal, Optional, Union

from agno.storage.session.agent import AgentSession
from agno.storage.session.workflow import WorkflowSession

try:
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.engine import Engine, create_engine
    from sqlalchemy.inspection import inspect
    from sqlalchemy.orm import scoped_session, sessionmaker
    from sqlalchemy.schema import Column, MetaData, Table
    from sqlalchemy.sql.expression import select, text
    from sqlalchemy.types import BigInteger, String
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")

from agno.storage.base import Storage
from agno.utils.log import logger


class PostgresStorage(Storage):
    def __init__(
        self,
        table_name: str,
        schema: Optional[str] = "ai",
        db_url: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        schema_version: int = 1,
        auto_upgrade_schema: bool = False,
        mode: Optional[Literal["agent", "workflow"]] = "agent",
    ):
        """
        This class provides agent storage using a PostgreSQL table.

        The following order is used to determine the database connection:
            1. Use the db_engine if provided
            2. Use the db_url
            3. Raise an error if neither is provided

        Args:
            table_name (str): Name of the table to store Agent sessions.
            schema (Optional[str]): The schema to use for the table. Defaults to "ai".
            db_url (Optional[str]): The database URL to connect to.
            db_engine (Optional[Engine]): The SQLAlchemy database engine to use.
            schema_version (int): Version of the schema. Defaults to 1.
            auto_upgrade_schema (bool): Whether to automatically upgrade the schema.
            mode (Optional[Literal["agent", "workflow"]]): The mode of the storage.
        Raises:
            ValueError: If neither db_url nor db_engine is provided.
        """
        super().__init__(mode)
        _engine: Optional[Engine] = db_engine
        if _engine is None and db_url is not None:
            _engine = create_engine(db_url)

        if _engine is None:
            raise ValueError("Must provide either db_url or db_engine")

        # Database attributes
        self.table_name: str = table_name
        self.schema: Optional[str] = schema
        self.db_url: Optional[str] = db_url
        self.db_engine: Engine = _engine
        self.metadata: MetaData = MetaData(schema=self.schema)
        self.inspector = inspect(self.db_engine)

        # Table schema version
        self.schema_version: int = schema_version
        # Automatically upgrade schema if True
        self.auto_upgrade_schema: bool = auto_upgrade_schema

        # Database session
        self.Session: scoped_session = scoped_session(sessionmaker(bind=self.db_engine))
        # Database table for storage
        self.table: Table = self.get_table()
        logger.debug(f"Created PostgresStorage: '{self.schema}.{self.table_name}'")

    @property
    def mode(self) -> Literal["agent", "workflow"]:
        """Get the mode of the storage."""
        return super().mode

    @mode.setter
    def mode(self, value: Optional[Literal["agent", "workflow"]]) -> None:
        """Set the mode and refresh the table if mode changes."""
        super(PostgresStorage, type(self)).mode.fset(self, value)  # type: ignore
        if value is not None:
            self.table = self.get_table()

    def get_table_v1(self) -> Table:
        """
        Define the table schema for version 1.

        Returns:
            Table: SQLAlchemy Table object representing the schema.
        """
        # Common columns for both agent and workflow modes
        common_columns = [
            Column("session_id", String, primary_key=True),
            Column("user_id", String, index=True),
            Column("memory", postgresql.JSONB),
            Column("session_data", postgresql.JSONB),
            Column("extra_data", postgresql.JSONB),
            Column("created_at", BigInteger, server_default=text("(extract(epoch from now()))::bigint")),
            Column("updated_at", BigInteger, server_onupdate=text("(extract(epoch from now()))::bigint")),
        ]

        # Mode-specific columns
        if self.mode == "agent":
            specific_columns = [
                Column("agent_id", String, index=True),
                Column("agent_data", postgresql.JSONB),
            ]
        else:
            specific_columns = [
                Column("workflow_id", String, index=True),
                Column("workflow_data", postgresql.JSONB),
            ]

        # Create table with all columns
        table = Table(
            self.table_name, self.metadata, *common_columns, *specific_columns, extend_existing=True, schema=self.schema
        )

        return table

    def get_table(self) -> Table:
        """
        Get the table schema based on the schema version.

        Returns:
            Table: SQLAlchemy Table object for the current schema version.

        Raises:
            ValueError: If an unsupported schema version is specified.
        """
        if self.schema_version == 1:
            return self.get_table_v1()
        else:
            raise ValueError(f"Unsupported schema version: {self.schema_version}")

    def table_exists(self) -> bool:
        """
        Check if the table exists in the database.

        Returns:
            bool: True if the table exists, False otherwise.
        """
        try:
            # Refresh inspector to ensure we have the latest metadata
            self.inspector = inspect(self.db_engine)

            # Check both schema and table existence
            if self.schema is not None:
                # First check if schema exists
                schemas = self.inspector.get_schema_names()
                if self.schema not in schemas:
                    logger.debug(f"Schema '{self.schema}' does not exist")
                    return False

            exists = self.inspector.has_table(self.table.name, schema=self.schema)
            logger.debug(f"Table '{self.table.fullname}' does {'not' if not exists else ''} exist")
            return exists

        except Exception as e:
            logger.error(f"Error checking if table exists: {e}")
            return False

    def create(self) -> None:
        """
        Create the table if it does not exist.
        """
        if not self.table_exists():
            try:
                with self.Session() as sess, sess.begin():
                    if self.schema is not None:
                        logger.debug(f"Creating schema: {self.schema}")
                        sess.execute(text(f"CREATE SCHEMA IF NOT EXISTS {self.schema};"))

                logger.debug(f"Creating table: {self.table_name}")
                # Create table with new indexes
                self.table.create(self.db_engine, checkfirst=True)
            except Exception as e:
                logger.error(f"Could not create table: '{self.table.fullname}': {e}")
                raise

    def read(self, session_id: str, user_id: Optional[str] = None) -> Optional[Union[AgentSession, WorkflowSession]]:
        """
        Read an Session from the database.

        Args:
            session_id (str): ID of the session to read.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Returns:
            Optional[Session]: Session object if found, None otherwise.
        """
        try:
            with self.Session() as sess:
                stmt = select(self.table).where(self.table.c.session_id == session_id)
                if user_id:
                    stmt = stmt.where(self.table.c.user_id == user_id)
                result = sess.execute(stmt).fetchone()
                if self.mode == "agent":
                    return AgentSession.from_dict(result._mapping) if result is not None else None
                else:
                    return WorkflowSession.from_dict(result._mapping) if result is not None else None
        except Exception as e:
            if "does not exist" in str(e):
                logger.debug(f"Table does not exist: {self.table.name}")
                logger.debug("Creating table for future transactions")
                self.create()
            else:
                logger.debug(f"Exception reading from table: {e}")
        return None

    def get_all_session_ids(self, user_id: Optional[str] = None, entity_id: Optional[str] = None) -> List[str]:
        """
        Get all session IDs, optionally filtered by user_id and/or entity_id.

        Args:
            user_id (Optional[str]): The ID of the user to filter by.
            entity_id (Optional[str]): The ID of the agent / workflow to filter by.

        Returns:
            List[str]: List of session IDs matching the criteria.
        """
        try:
            with self.Session() as sess, sess.begin():
                # get all session_ids
                stmt = select(self.table.c.session_id)
                if user_id is not None:
                    stmt = stmt.where(self.table.c.user_id == user_id)
                if entity_id is not None:
                    if self.mode == "agent":
                        stmt = stmt.where(self.table.c.agent_id == entity_id)
                    else:
                        stmt = stmt.where(self.table.c.workflow_id == entity_id)

                # order by created_at desc
                stmt = stmt.order_by(self.table.c.created_at.desc())
                # execute query
                rows = sess.execute(stmt).fetchall()
                return [row[0] for row in rows] if rows is not None else []
        except Exception as e:
            logger.debug(f"Exception reading from table: {e}")
            logger.debug(f"Table does not exist: {self.table.name}")
            logger.debug("Creating table for future transactions")
            self.create()
        return []

    def get_all_sessions(
        self, user_id: Optional[str] = None, entity_id: Optional[str] = None
    ) -> List[Union[AgentSession, WorkflowSession]]:
        """
        Get all sessions, optionally filtered by user_id and/or entity_id.

        Args:
            user_id (Optional[str]): The ID of the user to filter by.
            entity_id (Optional[str]): The ID of the agent / workflow to filter by.

        Returns:
            List[Union[AgentSession, WorkflowSession]]: List of Session objects matching the criteria.
        """
        try:
            with self.Session() as sess, sess.begin():
                # get all sessions
                stmt = select(self.table)
                if user_id is not None:
                    stmt = stmt.where(self.table.c.user_id == user_id)
                if entity_id is not None:
                    if self.mode == "agent":
                        stmt = stmt.where(self.table.c.agent_id == entity_id)
                    else:
                        stmt = stmt.where(self.table.c.workflow_id == entity_id)
                # order by created_at desc
                stmt = stmt.order_by(self.table.c.created_at.desc())
                # execute query
                rows = sess.execute(stmt).fetchall()
                if rows is not None:
                    if self.mode == "agent":
                        return [AgentSession.from_dict(row._mapping) for row in rows]  # type: ignore
                    else:
                        return [WorkflowSession.from_dict(row._mapping) for row in rows]  # type: ignore
                else:
                    return []
        except Exception as e:
            logger.debug(f"Exception reading from table: {e}")
            logger.debug(f"Table does not exist: {self.table.name}")
            logger.debug("Creating table for future transactions")
            self.create()
        return []

    def upsert(
        self, session: Union[AgentSession, WorkflowSession], create_and_retry: bool = True
    ) -> Optional[Union[AgentSession, WorkflowSession]]:
        """
        Insert or update an Session in the database.

        Args:
            session (Union[AgentSession, WorkflowSession]): The session data to upsert.
            create_and_retry (bool): Retry upsert if table does not exist.

        Returns:
            Optional[Union[AgentSession, WorkflowSession]]: The upserted Session, or None if operation failed.
        """
        try:
            with self.Session() as sess, sess.begin():
                # Create an insert statement
                if self.mode == "agent":
                    stmt = postgresql.insert(self.table).values(
                        session_id=session.session_id,
                        agent_id=session.agent_id,  # type: ignore
                        user_id=session.user_id,
                        memory=session.memory,
                        agent_data=session.agent_data,  # type: ignore
                        session_data=session.session_data,
                        extra_data=session.extra_data,
                    )
                    # Define the upsert if the session_id already exists
                    # See: https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#postgresql-insert-on-conflict
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["session_id"],
                        set_=dict(
                            agent_id=session.agent_id,  # type: ignore
                            user_id=session.user_id,
                            memory=session.memory,
                            agent_data=session.agent_data,  # type: ignore
                            session_data=session.session_data,
                            extra_data=session.extra_data,
                            updated_at=int(time.time()),
                        ),  # The updated value for each column
                    )
                else:
                    stmt = postgresql.insert(self.table).values(
                        session_id=session.session_id,
                        workflow_id=session.workflow_id,  # type: ignore
                        user_id=session.user_id,
                        memory=session.memory,
                        workflow_data=session.workflow_data,  # type: ignore
                        session_data=session.session_data,
                        extra_data=session.extra_data,
                    )
                    # Define the upsert if the session_id already exists
                    # See: https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#postgresql-insert-on-conflict
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["session_id"],
                        set_=dict(
                            workflow_id=session.workflow_id,  # type: ignore
                            user_id=session.user_id,
                            memory=session.memory,
                            workflow_data=session.workflow_data,  # type: ignore
                            session_data=session.session_data,
                            extra_data=session.extra_data,
                            updated_at=int(time.time()),
                        ),  # The updated value for each column
                    )

                sess.execute(stmt)
        except Exception as e:
            logger.debug(f"Exception upserting into table: {e}")
            if create_and_retry and not self.table_exists():
                logger.debug(f"Table does not exist: {self.table.name}")
                logger.debug("Creating table and retrying upsert")
                self.create()
                return self.upsert(session, create_and_retry=False)
            return None
        return self.read(session_id=session.session_id)

    def delete_session(self, session_id: Optional[str] = None):
        """
        Delete a session from the database.

        Args:
            session_id (Optional[str], optional): ID of the session to delete. Defaults to None.

        Raises:
            Exception: If an error occurs during deletion.
        """
        if session_id is None:
            logger.warning("No session_id provided for deletion.")
            return

        try:
            with self.Session() as sess, sess.begin():
                # Delete the session with the given session_id
                delete_stmt = self.table.delete().where(self.table.c.session_id == session_id)
                result = sess.execute(delete_stmt)
                if result.rowcount == 0:
                    logger.debug(f"No session found with session_id: {session_id}")
                else:
                    logger.debug(f"Successfully deleted session with session_id: {session_id}")
        except Exception as e:
            logger.error(f"Error deleting session: {e}")

    def drop(self) -> None:
        """
        Drop the table from the database if it exists.
        """
        if self.table_exists():
            logger.debug(f"Deleting table: {self.table_name}")
            self.table.drop(self.db_engine)

    def upgrade_schema(self) -> None:
        """
        Upgrade the schema to the latest version.
        This method is currently a placeholder and does not perform any actions.
        """
        pass

    def __deepcopy__(self, memo):
        """
        Create a deep copy of the PostgresStorage instance, handling unpickleable attributes.

        Args:
            memo (dict): A dictionary of objects already copied during the current copying pass.

        Returns:
            PostgresStorage: A deep-copied instance of PostgresStorage.
        """
        from copy import deepcopy

        # Create a new instance without calling __init__
        cls = self.__class__
        copied_obj = cls.__new__(cls)
        memo[id(self)] = copied_obj

        # Deep copy attributes
        for k, v in self.__dict__.items():
            if k in {"metadata", "table", "inspector"}:
                continue
            # Reuse db_engine and Session without copying
            elif k in {"db_engine", "Session"}:
                setattr(copied_obj, k, v)
            else:
                setattr(copied_obj, k, deepcopy(v, memo))

        # Recreate metadata and table for the copied instance
        copied_obj.metadata = MetaData(schema=copied_obj.schema)
        copied_obj.inspector = inspect(copied_obj.db_engine)
        copied_obj.table = copied_obj.get_table()

        return copied_obj
