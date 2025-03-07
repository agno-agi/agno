import time
from pathlib import Path
from typing import List, Literal, Optional, Union

try:
    from sqlalchemy.dialects import sqlite
    from sqlalchemy.engine import Engine, create_engine
    from sqlalchemy.inspection import inspect
    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.schema import Column, MetaData, Table
    from sqlalchemy.sql import text
    from sqlalchemy.sql.expression import select
    from sqlalchemy.types import String
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")

from agno.storage.base import Storage
from agno.storage.session.agent import AgentSession
from agno.storage.session.workflow import WorkflowSession
from agno.utils.log import logger


class SqliteStorage(Storage):
    def __init__(
        self,
        table_name: str,
        db_url: Optional[str] = None,
        db_file: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        schema_version: int = 1,
        auto_upgrade_schema: bool = False,
        mode: Optional[Literal["agent", "workflow"]] = "agent",
    ):
        """
        This class provides agent storage using a sqlite database.

        The following order is used to determine the database connection:
            1. Use the db_engine if provided
            2. Use the db_url
            3. Use the db_file
            4. Create a new in-memory database

        Args:
            table_name: The name of the table to store Agent sessions.
            db_url: The database URL to connect to.
            db_file: The database file to connect to.
            db_engine: The SQLAlchemy database engine to use.
        """
        super().__init__(mode)
        _engine: Optional[Engine] = db_engine
        if _engine is None and db_url is not None:
            _engine = create_engine(db_url)
        elif _engine is None and db_file is not None:
            # Use the db_file to create the engine
            db_path = Path(db_file).resolve()
            # Ensure the directory exists
            db_path.parent.mkdir(parents=True, exist_ok=True)
            _engine = create_engine(f"sqlite:///{db_path}")
        else:
            _engine = create_engine("sqlite://")

        if _engine is None:
            raise ValueError("Must provide either db_url, db_file or db_engine")

        # Database attributes
        self.table_name: str = table_name
        self.db_url: Optional[str] = db_url
        self.db_engine: Engine = _engine
        self.metadata: MetaData = MetaData()
        self.inspector = inspect(self.db_engine)

        # Table schema version
        self.schema_version: int = schema_version
        # Automatically upgrade schema if True
        self.auto_upgrade_schema: bool = auto_upgrade_schema

        # Database session
        self.Session: sessionmaker[Session] = sessionmaker(bind=self.db_engine)
        # Database table for storage
        self.table: Table = self.get_table()

    @property
    def mode(self) -> Optional[Literal["agent", "workflow"]]:
        """Get the mode of the storage."""
        return super().mode

    @mode.setter
    def mode(self, value: Optional[Literal["agent", "workflow"]]) -> None:
        """Set the mode and refresh the table if mode changes."""
        super(SqliteStorage, type(self)).mode.fset(self, value)  # type: ignore
        if value is not None:
            self.table = self.get_table()

    def get_table_v1(self) -> Table:
        """
        Define the table schema for version 1.

        Returns:
            Table: SQLAlchemy Table object representing the schema.
        """
        if self.mode == "agent":
            return Table(
                self.table_name,
                self.metadata,
                # Session UUID: Primary Key
                Column("session_id", String, primary_key=True),
                # ID of the agent that this session is associated with
                Column("agent_id", String, index=True),
                # ID of the user interacting with this agent
                Column("user_id", String, index=True),
                # Agent Memory
                Column("memory", sqlite.JSON),
                # Agent Data
                Column("agent_data", sqlite.JSON),
                # Session Data
                Column("session_data", sqlite.JSON),
                # Extra Data stored with this agent
                Column("extra_data", sqlite.JSON),
                # The Unix timestamp of when this session was created.
                Column("created_at", sqlite.INTEGER, default=lambda: int(time.time())),
                # The Unix timestamp of when this session was last updated.
                Column("updated_at", sqlite.INTEGER, onupdate=lambda: int(time.time())),
                extend_existing=True,
                sqlite_autoincrement=True,
            )
        else:
            return Table(
                self.table_name,
                self.metadata,
                # Session UUID: Primary Key
                Column("session_id", String, primary_key=True),
                # ID of the workflow that this session is associated with
                Column("workflow_id", String, index=True),
                # ID of the user interacting with this workflow
                Column("user_id", String, index=True),
                # Workflow Memory
                Column("memory", sqlite.JSON),
                # Workflow Data
                Column("workflow_data", sqlite.JSON),
                # Session Data
                Column("session_data", sqlite.JSON),
                # Extra Data stored with this workflow
                Column("extra_data", sqlite.JSON),
                # The Unix timestamp of when this session was created.
                Column("created_at", sqlite.INTEGER, default=lambda: int(time.time())),
                # The Unix timestamp of when this session was last updated.
                Column("updated_at", sqlite.INTEGER, onupdate=lambda: int(time.time())),
                extend_existing=True,
                sqlite_autoincrement=True,
            )

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
            # For SQLite, we need to check the sqlite_master table
            with self.Session() as sess:
                result = sess.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"),
                    {"table_name": self.table_name},
                ).scalar()
                return result is not None
        except Exception as e:
            logger.error(f"Error checking if table exists: {e}")
            return False

    def create(self) -> None:
        """
        Create the table if it doesn't exist.
        """
        if not self.table_exists():
            logger.debug(f"Creating table: {self.table.name}")
            try:
                # Create schema if it doesn't exist
                with self.Session() as sess, sess.begin():
                    # SQLite doesn't support schemas, so we'll just create the table
                    self.table.create(self.db_engine, checkfirst=True)
                    sess.commit()
            except Exception as e:
                logger.error(f"Error creating table: {e}")
                raise

    def read(self, session_id: str, user_id: Optional[str] = None) -> Optional[Union[AgentSession, WorkflowSession]]:
        """
        Read a Session from the database.

        Args:
            session_id (str): ID of the session to read.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Returns:
            Optional[Union[AgentSession, WorkflowSession]]: Session object if found, None otherwise.
        """
        try:
            with self.Session() as sess:
                stmt = select(self.table).where(self.table.c.session_id == session_id)
                if user_id:
                    stmt = stmt.where(self.table.c.user_id == user_id)
                result = sess.execute(stmt).fetchone()
                if self.mode == "agent":
                    return AgentSession.from_dict(result._mapping) if result is not None else None  # type: ignore
                else:
                    return WorkflowSession.from_dict(result._mapping) if result is not None else None  # type: ignore
        except Exception as e:
            if "no such table" in str(e):
                logger.debug(f"Table does not exist: {self.table.name}")
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
            if "no such table" in str(e):
                logger.debug(f"Table does not exist: {self.table.name}")
                self.create()
            else:
                logger.debug(f"Exception reading from table: {e}")
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
            if "no such table" in str(e):
                logger.debug(f"Table does not exist: {self.table.name}")
                self.create()
            else:
                logger.debug(f"Exception reading from table: {e}")
        return []

    def upsert(
        self, session: Union[AgentSession, WorkflowSession], create_and_retry: bool = True
    ) -> Optional[Union[AgentSession, WorkflowSession]]:
        """
        Insert or update a Session in the database.

        Args:
            session (Union[AgentSession, WorkflowSession]): The session data to upsert.
            create_and_retry (bool): Retry upsert if table does not exist.

        Returns:
            Optional[Union[AgentSession, WorkflowSession]]: The upserted Session, or None if operation failed.
        """
        try:
            with self.Session() as sess, sess.begin():
                if self.mode == "agent":
                    # Create an insert statement
                    stmt = sqlite.insert(self.table).values(
                        session_id=session.session_id,
                        agent_id=session.agent_id,  # type: ignore
                        user_id=session.user_id,
                        memory=session.memory,
                        agent_data=session.agent_data,  # type: ignore
                        session_data=session.session_data,
                        extra_data=session.extra_data,
                    )

                    # Define the upsert if the session_id already exists
                    # See: https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#insert-on-conflict-upsert
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
                    # Create an insert statement
                    stmt = sqlite.insert(self.table).values(
                        session_id=session.session_id,
                        workflow_id=session.workflow_id,  # type: ignore
                        user_id=session.user_id,
                        memory=session.memory,
                        workflow_data=session.workflow_data,  # type: ignore
                        session_data=session.session_data,
                        extra_data=session.extra_data,
                    )

                    # Define the upsert if the session_id already exists
                    # See: https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#insert-on-conflict-upsert
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
            if create_and_retry and not self.table_exists():
                logger.debug(f"Table does not exist: {self.table.name}")
                logger.debug("Creating table and retrying upsert")
                self.create()
                return self.upsert(session, create_and_retry=False)
            else:
                logger.debug(f"Exception upserting into table: {e}")
                return None
        return self.read(session_id=session.session_id)

    def delete_session(self, session_id: Optional[str] = None):
        """
        Delete a workflow session from the database.

        Args:
            session_id (Optional[str]): The ID of the session to delete.

        Raises:
            ValueError: If session_id is not provided.
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
        Upgrade the schema of the workflow storage table.
        This method is currently a placeholder and does not perform any actions.
        """
        pass

    def __deepcopy__(self, memo):
        """
        Create a deep copy of the SqliteAgentStorage instance, handling unpickleable attributes.

        Args:
            memo (dict): A dictionary of objects already copied during the current copying pass.

        Returns:
            SqliteStorage: A deep-copied instance of SqliteAgentStorage.
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
        copied_obj.metadata = MetaData()
        copied_obj.inspector = inspect(copied_obj.db_engine)
        copied_obj.table = copied_obj.get_table()

        return copied_obj
