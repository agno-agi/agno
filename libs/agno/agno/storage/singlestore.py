import json
from typing import Any, List, Literal, Optional

from agno.storage.base import Storage
from agno.storage.session import Session
from agno.storage.session.agent import AgentSession
from agno.storage.session.team import TeamSession
from agno.storage.session.workflow import WorkflowSession
from agno.utils.log import log_debug, log_info, log_warning, logger

try:
    from sqlalchemy.dialects import mysql
    from sqlalchemy.engine import Engine, create_engine
    from sqlalchemy.engine.row import Row
    from sqlalchemy.inspection import inspect
    from sqlalchemy.orm import Session as SqlSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.schema import Column, MetaData, Table
    from sqlalchemy.sql.expression import select, text
except ImportError:
    raise ImportError("`sqlalchemy` not installed")


class SingleStoreStorage(Storage):
    def __init__(
        self,
        table_name: str,
        schema: Optional[str] = "ai",
        db_url: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        schema_version: int = 1,
        auto_upgrade_schema: bool = False,
        mode: Optional[Literal["agent", "team", "workflow"]] = "agent",
    ):
        """
        This class provides Agent storage using a singlestore table.

        The following order is used to determine the database connection:
            1. Use the db_engine if provided
            2. Use the db_url if provided

        Args:
            table_name (str): The name of the table to store the agent data.
            schema (Optional[str], optional): The schema of the table. Defaults to "ai".
            db_url (Optional[str], optional): The database URL. Defaults to None.
            db_engine (Optional[Engine], optional): The database engine. Defaults to None.
            schema_version (int, optional): The schema version. Defaults to 1.
            auto_upgrade_schema (bool, optional): Automatically upgrade the schema. Defaults to False.
            mode (Optional[Literal["agent", "team", "workflow"]], optional): The mode of the storage. Defaults to "agent".
        """
        super().__init__(mode)
        _engine: Optional[Engine] = db_engine
        if _engine is None and db_url is not None:
            _engine = create_engine(db_url, connect_args={"charset": "utf8mb4"})

        if _engine is None:
            raise ValueError("Must provide either db_url or db_engine")

        # Database attributes
        self.table_name: str = table_name
        self.schema: Optional[str] = schema
        self.db_url: Optional[str] = db_url
        self.db_engine: Engine = _engine
        self.metadata: MetaData = MetaData(schema=self.schema)

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
    def mode(self) -> Literal["agent", "team", "workflow"]:
        """Get the mode of the storage."""
        return super().mode

    @mode.setter
    def mode(self, value: Optional[Literal["agent", "team", "workflow"]]) -> None:
        """Set the mode and refresh the table if mode changes."""
        super(SingleStoreStorage, type(self)).mode.fset(self, value)  # type: ignore
        if value is not None:
            self.table = self.get_table()

    def get_table_v1(self) -> Table:
        common_columns = [
            Column("session_id", mysql.TEXT, primary_key=True),
            Column("user_id", mysql.TEXT),
            Column("memory", mysql.JSON),
            Column("session_data", mysql.JSON),
            Column("extra_data", mysql.JSON),
            Column("created_at", mysql.BIGINT),
            Column("updated_at", mysql.BIGINT),
        ]

        specific_columns = []
        if self.mode == "agent":
            specific_columns = [
                Column("agent_id", mysql.TEXT),
                Column("team_session_id", mysql.TEXT, nullable=True),
                Column("agent_data", mysql.JSON),
            ]
        elif self.mode == "team":
            specific_columns = [
                Column("team_id", mysql.TEXT),
                Column("team_session_id", mysql.TEXT, nullable=True),
                Column("team_data", mysql.JSON),
            ]
        elif self.mode == "workflow":
            specific_columns = [
                Column("workflow_id", mysql.TEXT),
                Column("workflow_data", mysql.JSON),
            ]

        # Create table with all columns
        table = Table(
            self.table_name,
            self.metadata,
            *common_columns,
            *specific_columns,
            extend_existing=True,
            schema=self.schema,  # type: ignore
        )

        return table

    def get_table(self) -> Table:
        if self.schema_version == 1:
            return self.get_table_v1()
        else:
            raise ValueError(f"Unsupported schema version: {self.schema_version}")

    def table_exists(self) -> bool:
        log_debug(f"Checking if table exists: {self.table.name}")
        try:
            return inspect(self.db_engine).has_table(self.table.name, schema=self.schema)
        except Exception as e:
            logger.error(e)
            return False

    def create(self) -> None:
        self.table = self.get_table()
        if not self.table_exists():
            log_info(f"Creating table: {self.table_name}\n")
            self.table.create(self.db_engine)

    def _read(self, session: SqlSession, session_id: str, user_id: Optional[str] = None) -> Optional[Row[Any]]:
        stmt = select(self.table).where(self.table.c.session_id == session_id)
        if user_id is not None:
            stmt = stmt.where(self.table.c.user_id == user_id)
        try:
            return session.execute(stmt).first()
        except Exception as e:
            log_debug(f"Exception reading from table: {e}")
            log_debug(f"Table does not exist: {self.table.name}")
            log_debug(f"Creating table: {self.table_name}")
            self.create()
        return None

    def read(self, session_id: str, user_id: Optional[str] = None) -> Optional[Session]:
        with self.SqlSession.begin() as sess:
            existing_row: Optional[Row[Any]] = self._read(session=sess, session_id=session_id, user_id=user_id)
            if existing_row is not None:
                if self.mode == "agent":
                    return AgentSession.from_dict(existing_row._mapping)  # type: ignore
                elif self.mode == "team":
                    return TeamSession.from_dict(existing_row._mapping)  # type: ignore
                elif self.mode == "workflow":
                    return WorkflowSession.from_dict(existing_row._mapping)  # type: ignore
            return None

    def get_all_session_ids(self, user_id: Optional[str] = None, entity_id: Optional[str] = None) -> List[str]:
        session_ids: List[str] = []
        try:
            with self.SqlSession.begin() as sess:
                # get all session_ids for this user
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
                for row in rows:
                    if row is not None and row.session_id is not None:
                        session_ids.append(row.session_id)
        except Exception as e:
            logger.error(f"An unexpected error occurred: {str(e)}")
        return session_ids

    def get_all_sessions(self, user_id: Optional[str] = None, entity_id: Optional[str] = None) -> List[Session]:
        sessions: List[Session] = []
        try:
            with self.SqlSession.begin() as sess:
                # get all sessions for this user
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
                for row in rows:
                    if row.session_id is not None:
                        if self.mode == "agent":
                            _agent_session = AgentSession.from_dict(row._mapping)  # type: ignore
                            if _agent_session is not None:
                                sessions.append(_agent_session)
                        elif self.mode == "team":
                            _team_session = TeamSession.from_dict(row._mapping)  # type: ignore
                            if _team_session is not None:
                                sessions.append(_team_session)
                        elif self.mode == "workflow":
                            _workflow_session = WorkflowSession.from_dict(row._mapping)  # type: ignore
                            if _workflow_session is not None:
                                sessions.append(_workflow_session)
        except Exception:
            log_debug(f"Table does not exist: {self.table.name}")
        return sessions

    def upgrade_schema(self) -> None:
        """
        Upgrade the schema to the latest version.
        Currently handles adding the team_session_id column for agent mode.
        """
        if not self.auto_upgrade_schema:
            log_debug("Auto schema upgrade disabled. Skipping upgrade.")
            return

        try:
            if self.mode == "agent" and self.table_exists():
                with self.SqlSession() as sess:
                    # Check if team_session_id column exists
                    column_exists_query = text(
                        """
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = :schema AND table_name = :table
                        AND column_name = 'team_session_id'
                        """
                    )
                    column_exists = (
                        sess.execute(column_exists_query, {"schema": self.schema, "table": self.table_name}).scalar()
                        is not None
                    )

                    if not column_exists:
                        log_info(f"Adding 'team_session_id' column to {self.schema}.{self.table_name}")
                        alter_table_query = text(
                            f"ALTER TABLE {self.schema}.{self.table_name} ADD COLUMN team_session_id TEXT"
                        )
                        sess.execute(alter_table_query)
                        sess.commit()
                        self._schema_up_to_date = True
                        log_info("Schema upgrade completed successfully")
        except Exception as e:
            logger.error(f"Error during schema upgrade: {e}")
            raise

    def upsert(self, session: Session) -> Optional[Session]:
        """
        Create a new session if it does not exist, otherwise update the existing session.
        """
        # Perform schema upgrade if auto_upgrade_schema is enabled
        if self.auto_upgrade_schema and not self._schema_up_to_date:
            self.upgrade_schema()

        with self.SqlSession.begin() as sess:
            # Create an insert statement using MySQL's ON DUPLICATE KEY UPDATE syntax
            if self.mode == "agent":
                upsert_sql = text(
                    f"""
                    INSERT INTO {self.schema}.{self.table_name}
                    (session_id, agent_id, team_session_id, user_id, memory, agent_data, session_data, extra_data, created_at, updated_at)
                    VALUES
                    (:session_id, :agent_id, :team_session_id, :user_id, :memory, :agent_data, :session_data, :extra_data, UNIX_TIMESTAMP(), NULL)
                    ON DUPLICATE KEY UPDATE
                        agent_id = VALUES(agent_id),
                        team_session_id = VALUES(team_session_id),
                        user_id = VALUES(user_id),
                        memory = VALUES(memory),
                        agent_data = VALUES(agent_data),
                        session_data = VALUES(session_data),
                        extra_data = VALUES(extra_data),
                        updated_at = UNIX_TIMESTAMP();
                    """
                )
            elif self.mode == "team":
                upsert_sql = text(
                    f"""
                    INSERT INTO {self.schema}.{self.table_name}
                    (session_id, team_id, user_id, team_session_id, memory, team_data, session_data, extra_data, created_at, updated_at)
                    VALUES
                    (:session_id, :team_id, :user_id, :team_session_id, :memory, :team_data, :session_data, :extra_data, UNIX_TIMESTAMP(), NULL)
                    ON DUPLICATE KEY UPDATE
                        team_id = VALUES(team_id),
                        team_session_id = VALUES(team_session_id),
                        user_id = VALUES(user_id),
                        memory = VALUES(memory),
                        team_data = VALUES(team_data),
                        session_data = VALUES(session_data),
                        extra_data = VALUES(extra_data),
                        updated_at = UNIX_TIMESTAMP();
                    """
                )
            elif self.mode == "workflow":
                upsert_sql = text(
                    f"""
                    INSERT INTO {self.schema}.{self.table_name}
                    (session_id, workflow_id, user_id, memory, workflow_data, session_data, extra_data, created_at, updated_at)
                    VALUES
                    (:session_id, :workflow_id, :user_id, :memory, :workflow_data, :session_data, :extra_data, UNIX_TIMESTAMP(), NULL)
                    ON DUPLICATE KEY UPDATE
                        workflow_id = VALUES(workflow_id),
                        user_id = VALUES(user_id),
                        memory = VALUES(memory),
                        workflow_data = VALUES(workflow_data),
                        session_data = VALUES(session_data),
                        extra_data = VALUES(extra_data),
                        updated_at = UNIX_TIMESTAMP();
                    """
                )

            try:
                if self.mode == "agent":
                    sess.execute(
                        upsert_sql,
                        {
                            "session_id": session.session_id,
                            "agent_id": session.agent_id,  # type: ignore
                            "team_session_id": session.team_session_id,  # type: ignore
                            "user_id": session.user_id,
                            "memory": json.dumps(session.memory, ensure_ascii=False)
                            if session.memory is not None
                            else None,
                            "agent_data": json.dumps(session.agent_data, ensure_ascii=False)  # type: ignore
                            if session.agent_data is not None  # type: ignore
                            else None,
                            "session_data": json.dumps(session.session_data, ensure_ascii=False)
                            if session.session_data is not None
                            else None,
                            "extra_data": json.dumps(session.extra_data, ensure_ascii=False)
                            if session.extra_data is not None
                            else None,
                        },
                    )
                elif self.mode == "team":
                    sess.execute(
                        upsert_sql,
                        {
                            "session_id": session.session_id,
                            "team_id": session.team_id,  # type: ignore
                            "user_id": session.user_id,
                            "team_session_id": session.team_session_id,  # type: ignore
                            "memory": json.dumps(session.memory, ensure_ascii=False)
                            if session.memory is not None
                            else None,
                            "team_data": json.dumps(session.team_data, ensure_ascii=False)  # type: ignore
                            if session.team_data is not None  # type: ignore
                            else None,
                            "session_data": json.dumps(session.session_data, ensure_ascii=False)
                            if session.session_data is not None
                            else None,
                            "extra_data": json.dumps(session.extra_data, ensure_ascii=False)
                            if session.extra_data is not None
                            else None,
                        },
                    )
                elif self.mode == "workflow":
                    sess.execute(
                        upsert_sql,
                        {
                            "session_id": session.session_id,
                            "workflow_id": session.workflow_id,  # type: ignore
                            "user_id": session.user_id,
                            "memory": json.dumps(session.memory, ensure_ascii=False)
                            if session.memory is not None
                            else None,
                            "workflow_data": json.dumps(session.workflow_data, ensure_ascii=False)  # type: ignore
                            if session.workflow_data is not None  # type: ignore
                            else None,
                            "session_data": json.dumps(session.session_data, ensure_ascii=False)
                            if session.session_data is not None
                            else None,
                            "extra_data": json.dumps(session.extra_data, ensure_ascii=False)
                            if session.extra_data is not None
                            else None,
                        },
                    )
            except Exception as e:
                # Create table and try again
                if not self.table_exists():
                    log_debug(f"Table does not exist: {self.table.name}")
                    log_debug("Creating table and retrying upsert")
                    self.create()
                    return self.upsert(session)
                else:
                    log_warning(f"Exception upserting into table: {e}")
                    log_warning(
                        "A table upgrade might be required, please review these docs for more information: https://agno.link/upgrade-schema"
                    )
                    return None
        return self.read(session_id=session.session_id)

    def delete_session(self, session_id: Optional[str] = None):
        if session_id is None:
            logger.warning("No session_id provided for deletion.")
            return

        with self.SqlSession() as sess, sess.begin():
            try:
                # Delete the session with the given session_id
                delete_stmt = self.table.delete().where(self.table.c.session_id == session_id)
                result = sess.execute(delete_stmt)

                if result.rowcount == 0:
                    logger.warning(f"No session found with session_id: {session_id}")
                else:
                    log_info(f"Successfully deleted session with session_id: {session_id}")
            except Exception as e:
                logger.error(f"Error deleting session: {e}")
                raise

    def drop(self) -> None:
        if self.table_exists():
            log_info(f"Deleting table: {self.table_name}")
            self.table.drop(self.db_engine)

    def __deepcopy__(self, memo):
        """
        Create a deep copy of the SingleStoreAgentStorage instance, handling unpickleable attributes.

        Args:
            memo (dict): A dictionary of objects already copied during the current copying pass.

        Returns:
            SingleStoreStorage: A deep-copied instance of SingleStoreAgentStorage.
        """
        from copy import deepcopy

        # Create a new instance without calling __init__
        cls = self.__class__
        copied_obj = cls.__new__(cls)
        memo[id(self)] = copied_obj

        # Deep copy attributes
        for k, v in self.__dict__.items():
            if k in {"metadata", "table"}:
                continue
            # Reuse db_engine and Session without copying
            elif k in {"db_engine", "SqlSession"}:
                setattr(copied_obj, k, v)
            else:
                setattr(copied_obj, k, deepcopy(v, memo))

        # Recreate metadata and table for the copied instance
        copied_obj.metadata = MetaData(schema=self.schema)
        copied_obj.table = copied_obj.get_table()

        return copied_obj
