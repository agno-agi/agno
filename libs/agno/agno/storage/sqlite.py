import time
from pathlib import Path
from typing import List, Literal, Optional

from agno.storage.base import Storage
from agno.storage.session import Session
from agno.storage.session.agent import AgentSession
from agno.storage.session.team import TeamSession
from agno.storage.session.workflow import WorkflowSession
from agno.utils.log import log_debug, log_info, log_warning, logger

try:
    from sqlalchemy.dialects import sqlite
    from sqlalchemy.engine import Engine, create_engine
    from sqlalchemy.inspection import inspect
    from sqlalchemy.orm import Session as SqlSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.schema import Column, MetaData, Table
    from sqlalchemy.sql import text
    from sqlalchemy.sql.expression import select
    from sqlalchemy.types import String
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


class SqliteStorage(Storage):
    def __init__(
        self,
        table_name: str,
        db_url: Optional[str] = None,
        db_file: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        schema_version: int = 1,
        auto_upgrade_schema: bool = False,
        mode: Optional[Literal["agent", "team", "workflow"]] = "agent",
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
        self._schema_up_to_date: bool = False

        # Database session
        self.SqlSession: sessionmaker[SqlSession] = sessionmaker(bind=self.db_engine)
        # Database table for storage
        self.table: Table = self.get_table()

    @property
    def mode(self) -> Optional[Literal["agent", "team", "workflow"]]:
        """Get the mode of the storage."""
        return super().mode

    @mode.setter
    def mode(self, value: Optional[Literal["agent", "team", "workflow"]]) -> None:
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
        common_columns = [
            Column("session_id", String, primary_key=True),
            Column("user_id", String, index=True),
            Column("memory", sqlite.JSON),
            Column("session_data", sqlite.JSON),
            Column("extra_data", sqlite.JSON),
            Column("created_at", sqlite.INTEGER, default=lambda: int(time.time())),
            Column("updated_at", sqlite.INTEGER, onupdate=lambda: int(time.time())),
        ]

        # Mode-specific columns
        specific_columns = []
        if self.mode == "agent":
            specific_columns = [
                Column("agent_id", String, index=True),
                Column("agent_data", sqlite.JSON),
                Column("team_session_id", String, index=True, nullable=True),
            ]
        elif self.mode == "team":
            specific_columns = [
                Column("team_id", String, index=True),
                Column("team_data", sqlite.JSON),
                Column("team_session_id", String, index=True, nullable=True),
            ]
        elif self.mode == "workflow":
            specific_columns = [
                Column("workflow_id", String, index=True),
                Column("workflow_data", sqlite.JSON),
            ]

        # Create table with all columns
        table = Table(
            self.table_name,
            self.metadata,
            *common_columns,
            *specific_columns,
            extend_existing=True,
            sqlite_autoincrement=True,
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
            # For SQLite, we need to check the sqlite_master table
            with self.SqlSession() as sess:
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
        self.table = self.get_table()
        if not self.table_exists():
            log_debug(f"Creating table: {self.table.name}")
            try:
                # First create the table without indexes
                table_without_indexes = Table(
                    self.table_name,
                    MetaData(),
                    *[c.copy() for c in self.table.columns],
                )
                table_without_indexes.create(self.db_engine, checkfirst=True)

                # Then create each index individually with error handling
                for idx in self.table.indexes:
                    try:
                        idx_name = idx.name
                        log_debug(f"Creating index: {idx_name}")

                        # Check if index already exists using SQLite's schema table
                        with self.SqlSession() as sess:
                            exists_query = text("SELECT 1 FROM sqlite_master WHERE type='index' AND name=:index_name")
                            exists = sess.execute(exists_query, {"index_name": idx_name}).scalar() is not None

                        if not exists:
                            idx.create(self.db_engine)
                        else:
                            log_debug(f"Index {idx_name} already exists, skipping creation")

                    except Exception as e:
                        # Log the error but continue with other indexes
                        logger.warning(f"Error creating index {idx.name}: {e}")

            except Exception as e:
                logger.error(f"Error creating table: {e}")
                raise

    def read(self, session_id: str, user_id: Optional[str] = None) -> Optional[Session]:
        """
        Read a Session from the database.

        Args:
            session_id (str): ID of the session to read.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Returns:
            Optional[Session]: Session object if found, None otherwise.
        """
        try:
            with self.SqlSession() as sess:
                stmt = select(self.table).where(self.table.c.session_id == session_id)
                if user_id:
                    stmt = stmt.where(self.table.c.user_id == user_id)
                result = sess.execute(stmt).fetchone()
                if self.mode == "agent":
                    return AgentSession.from_dict(result._mapping) if result is not None else None  # type: ignore
                elif self.mode == "team":
                    return TeamSession.from_dict(result._mapping) if result is not None else None  # type: ignore
                elif self.mode == "workflow":
                    return WorkflowSession.from_dict(result._mapping) if result is not None else None  # type: ignore
        except Exception as e:
            if "no such table" in str(e):
                log_debug(f"Table does not exist: {self.table.name}")
                self.create()
            else:
                log_debug(f"Exception reading from table: {e}")
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
            with self.SqlSession() as sess, sess.begin():
                # get all session_ids
                stmt = select(self.table.c.session_id)
                if user_id is not None:
                    stmt = stmt.where(self.table.c.user_id == user_id)
                if entity_id is not None:
                    if self.mode == "agent":
                        stmt = stmt.where(self.table.c.agent_id == entity_id)
                    elif self.mode == "team":
                        stmt = stmt.where(self.table.c.team_id == entity_id)
                    elif self.mode == "workflow":
                        stmt = stmt.where(self.table.c.workflow_id == entity_id)
                # order by created_at desc
                stmt = stmt.order_by(self.table.c.created_at.desc())
                # execute query
                rows = sess.execute(stmt).fetchall()
                return [row[0] for row in rows] if rows is not None else []
        except Exception as e:
            if "no such table" in str(e):
                log_debug(f"Table does not exist: {self.table.name}")
                self.create()
            else:
                log_debug(f"Exception reading from table: {e}")
        return []

    def get_all_sessions(self, user_id: Optional[str] = None, entity_id: Optional[str] = None) -> List[Session]:
        """
        Get all sessions, optionally filtered by user_id and/or entity_id.

        Args:
            user_id (Optional[str]): The ID of the user to filter by.
            entity_id (Optional[str]): The ID of the agent / workflow to filter by.

        Returns:
            List[Session]: List of Session objects matching the criteria.
        """
        try:
            with self.SqlSession() as sess, sess.begin():
                # get all sessions
                stmt = select(self.table)
                if user_id is not None:
                    stmt = stmt.where(self.table.c.user_id == user_id)
                if entity_id is not None:
                    if self.mode == "agent":
                        stmt = stmt.where(self.table.c.agent_id == entity_id)
                    elif self.mode == "team":
                        stmt = stmt.where(self.table.c.team_id == entity_id)
                    elif self.mode == "workflow":
                        stmt = stmt.where(self.table.c.workflow_id == entity_id)
                # order by created_at desc
                stmt = stmt.order_by(self.table.c.created_at.desc())
                # execute query
                rows = sess.execute(stmt).fetchall()
                if rows is not None:
                    if self.mode == "agent":
                        return [AgentSession.from_dict(row._mapping) for row in rows]  # type: ignore
                    elif self.mode == "team":
                        return [TeamSession.from_dict(row._mapping) for row in rows]  # type: ignore
                    elif self.mode == "workflow":
                        return [WorkflowSession.from_dict(row._mapping) for row in rows]  # type: ignore
                else:
                    return []
        except Exception as e:
            if "no such table" in str(e):
                log_debug(f"Table does not exist: {self.table.name}")
                self.create()
            else:
                log_debug(f"Exception reading from table: {e}")
        return []

    def get_recent_sessions(
        self,
        user_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        limit: Optional[int] = 2,
    ) -> List[Session]:
        """
        Get the last N sessions, ordered by created_at descending.

        Args:
            num_history_sessions: Number of most recent sessions to return
            user_id: Filter by user ID
            entity_id: Filter by entity ID (agent_id, team_id, or workflow_id)

        Returns:
            List[Session]: List of most recent sessions
        """
        try:
            with self.SqlSession() as sess, sess.begin():
                # Build the query
                stmt = select(self.table)
                if user_id is not None:
                    stmt = stmt.where(self.table.c.user_id == user_id)
                if entity_id is not None:
                    if self.mode == "agent":
                        stmt = stmt.where(self.table.c.agent_id == entity_id)
                    elif self.mode == "team":
                        stmt = stmt.where(self.table.c.team_id == entity_id)
                    elif self.mode == "workflow":
                        stmt = stmt.where(self.table.c.workflow_id == entity_id)

                # Order by created_at desc and limit to num_history_sessions
                stmt = stmt.order_by(self.table.c.created_at.desc())
                if limit is not None:
                    stmt = stmt.limit(limit)

                # Execute query
                rows = sess.execute(stmt).fetchall()
                if rows is not None:
                    if self.mode == "agent":
                        return [AgentSession.from_dict(row._mapping) for row in rows]  # type: ignore
                    elif self.mode == "team":
                        return [TeamSession.from_dict(row._mapping) for row in rows]  # type: ignore
                    elif self.mode == "workflow":
                        return [WorkflowSession.from_dict(row._mapping) for row in rows]  # type: ignore
                return []
        except Exception as e:
            if "no such table" in str(e):
                log_debug(f"Table does not exist: {self.table.name}")
                self.create()
            else:
                log_debug(f"Exception reading from table: {e}")
        return []

    def upgrade_schema(self) -> None:
        """
        Upgrade the schema of the storage table.
        Currently handles adding the team_session_id column for agent mode.
        """
        if not self.auto_upgrade_schema:
            log_debug("Auto schema upgrade disabled. Skipping upgrade.")
            return

        try:
            if self.mode == "agent" and self.table_exists():
                with self.SqlSession() as sess:
                    # Check if team_session_id column exists using SQLite PRAGMA
                    column_exists_query = text(f"PRAGMA table_info({self.table_name})")
                    columns = sess.execute(column_exists_query).fetchall()
                    column_exists = any(col[1] == "team_session_id" for col in columns)

                    if not column_exists:
                        log_info(f"Adding 'team_session_id' column to {self.table_name}")
                        alter_table_query = text(f"ALTER TABLE {self.table_name} ADD COLUMN team_session_id TEXT")
                        sess.execute(alter_table_query)
                        sess.commit()
                        self._schema_up_to_date = True
                        log_info("Schema upgrade completed successfully")
        except Exception as e:
            logger.error(f"Error during schema upgrade: {e}")
            raise

    def upsert(self, session: Session, create_and_retry: bool = True) -> Optional[Session]:
        """
        Insert or update a Session in the database.

        Args:
            session (Session): The session data to upsert.
            create_and_retry (bool): Retry upsert if table does not exist.

        Returns:
            Optional[Session]: The upserted Session, or None if operation failed.
        """
        # Perform schema upgrade if auto_upgrade_schema is enabled
        if self.auto_upgrade_schema and not self._schema_up_to_date:
            self.upgrade_schema()

        try:
            with self.SqlSession() as sess, sess.begin():
                if self.mode == "agent":
                    # Create an insert statement
                    stmt = sqlite.insert(self.table).values(
                        session_id=session.session_id,
                        agent_id=session.agent_id,  # type: ignore
                        team_session_id=session.team_session_id,  # type: ignore
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
                            team_session_id=session.team_session_id,  # type: ignore
                            user_id=session.user_id,
                            memory=session.memory,
                            agent_data=session.agent_data,  # type: ignore
                            session_data=session.session_data,
                            extra_data=session.extra_data,
                            updated_at=int(time.time()),
                        ),  # The updated value for each column
                    )
                elif self.mode == "team":
                    # Create an insert statement
                    stmt = sqlite.insert(self.table).values(
                        session_id=session.session_id,
                        team_id=session.team_id,  # type: ignore
                        user_id=session.user_id,
                        team_session_id=session.team_session_id,  # type: ignore
                        memory=session.memory,
                        team_data=session.team_data,  # type: ignore
                        session_data=session.session_data,
                        extra_data=session.extra_data,
                    )

                    # Define the upsert if the session_id already exists
                    # See: https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#insert-on-conflict-upsert
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["session_id"],
                        set_=dict(
                            team_id=session.team_id,  # type: ignore
                            user_id=session.user_id,
                            team_session_id=session.team_session_id,  # type: ignore
                            memory=session.memory,
                            team_data=session.team_data,  # type: ignore
                            session_data=session.session_data,
                            extra_data=session.extra_data,
                            updated_at=int(time.time()),
                        ),  # The updated value for each column
                    )
                elif self.mode == "workflow":
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
                log_debug(f"Table does not exist: {self.table.name}")
                log_debug("Creating table and retrying upsert")
                self.create()
                return self.upsert(session, create_and_retry=False)
            else:
                log_warning(f"Exception upserting into table: {e}")
                log_warning(
                    "A table upgrade might be required, please review these docs for more information: https://agno.link/upgrade-schema"
                )
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
            with self.SqlSession() as sess, sess.begin():
                # Delete the session with the given session_id
                delete_stmt = self.table.delete().where(self.table.c.session_id == session_id)
                result = sess.execute(delete_stmt)
                if result.rowcount == 0:
                    log_debug(f"No session found with session_id: {session_id}")
                else:
                    log_debug(f"Successfully deleted session with session_id: {session_id}")
        except Exception as e:
            logger.error(f"Error deleting session: {e}")

    def drop(self) -> None:
        """
        Drop the table from the database if it exists.
        """
        if self.table_exists():
            log_debug(f"Deleting table: {self.table_name}")
            # Drop with checkfirst=True to avoid errors if the table doesn't exist
            self.table.drop(self.db_engine, checkfirst=True)
            # Clear metadata to ensure indexes are recreated properly
            self.metadata = MetaData()
            self.table = self.get_table()

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
            elif k in {"db_engine", "SqlSession"}:
                setattr(copied_obj, k, v)
            else:
                setattr(copied_obj, k, deepcopy(v, memo))

        # Recreate metadata and table for the copied instance
        copied_obj.metadata = MetaData()
        copied_obj.inspector = inspect(copied_obj.db_engine)
        copied_obj.table = copied_obj.get_table()

        return copied_obj
