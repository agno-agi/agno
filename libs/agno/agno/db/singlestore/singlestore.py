import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from agno.db.base import BaseDb, SessionType
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.db.singlestore.schemas import get_table_schema_definition
from agno.db.singlestore.utils import (
    apply_sorting,
    bulk_upsert_metrics,
    calculate_date_metrics,
    create_schema,
    fetch_all_sessions_data,
    get_dates_to_calculate_metrics_for,
    is_table_available,
    is_valid_table,
)
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info, log_warning

try:
    from sqlalchemy import Index, UniqueConstraint, and_, func, update
    from sqlalchemy.dialects import mysql
    from sqlalchemy.engine import Engine, create_engine
    from sqlalchemy.orm import scoped_session, sessionmaker
    from sqlalchemy.schema import Column, MetaData, Table
    from sqlalchemy.sql.expression import select, text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


class SingleStoreDb(BaseDb):
    def __init__(
        self,
        id: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        db_schema: Optional[str] = None,
        db_url: Optional[str] = None,
        session_table: Optional[str] = None,
        memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
    ):
        """
        Interface for interacting with a SingleStore database.

        The following order is used to determine the database connection:
            1. Use the db_engine if provided
            2. Use the db_url
            3. Raise an error if neither is provided

        Args:
            id (Optional[str]): The ID of the database.
            db_engine (Optional[Engine]): The SQLAlchemy database engine to use.
            db_schema (Optional[str]): The database schema to use.
            db_url (Optional[str]): The database URL to connect to.
            session_table (Optional[str]): Name of the table to store Agent, Team and Workflow sessions.
            memory_table (Optional[str]): Name of the table to store memories.
            metrics_table (Optional[str]): Name of the table to store metrics.
            eval_table (Optional[str]): Name of the table to store evaluation runs data.
            knowledge_table (Optional[str]): Name of the table to store knowledge content.

        Raises:
            ValueError: If neither db_url nor db_engine is provided.
            ValueError: If none of the tables are provided.
        """
        super().__init__(
            id=id,
            session_table=session_table,
            memory_table=memory_table,
            metrics_table=metrics_table,
            eval_table=eval_table,
            knowledge_table=knowledge_table,
        )

        _engine: Optional[Engine] = db_engine
        if _engine is None and db_url is not None:
            _engine = create_engine(
                db_url,
                connect_args={
                    "charset": "utf8mb4",
                    "ssl": {"ssl_disabled": False, "ssl_ca": None, "ssl_check_hostname": False},
                },
            )
        if _engine is None:
            raise ValueError("One of db_url or db_engine must be provided")

        self.db_url: Optional[str] = db_url
        self.db_engine: Engine = _engine
        self.db_schema: Optional[str] = db_schema
        self.metadata: MetaData = MetaData()

        # Initialize database session
        self.Session: scoped_session = scoped_session(sessionmaker(bind=self.db_engine))

    # -- DB methods --

    def _create_table_structure_only(self, table_name: str, table_type: str, db_schema: Optional[str]) -> Table:
        """
        Create a table structure definition without actually creating the table in the database.
        Used to avoid autoload issues with SingleStore JSON types.

        Args:
            table_name (str): Name of the table
            table_type (str): Type of table (used to get schema definition)
            db_schema (Optional[str]): Database schema name

        Returns:
            Table: SQLAlchemy Table object with column definitions
        """
        try:
            table_schema = get_table_schema_definition(table_type)

            columns: List[Column] = []
            # Get the columns from the table schema
            for col_name, col_config in table_schema.items():
                # Skip constraint definitions
                if col_name.startswith("_"):
                    continue

                column_args = [col_name, col_config["type"]()]
                column_kwargs: Dict[str, Any] = {}
                if col_config.get("primary_key", False):
                    column_kwargs["primary_key"] = True
                if "nullable" in col_config:
                    column_kwargs["nullable"] = col_config["nullable"]
                if col_config.get("unique", False):
                    column_kwargs["unique"] = True
                columns.append(Column(*column_args, **column_kwargs))

            # Create the table object without constraints to avoid autoload issues
            table_metadata = MetaData(schema=db_schema)
            table = Table(table_name, table_metadata, *columns, schema=db_schema)

            return table

        except Exception as e:
            table_ref = f"{db_schema}.{table_name}" if db_schema else table_name
            log_error(f"Could not create table structure for {table_ref}: {e}")
            raise

    def _create_table(self, table_name: str, table_type: str, db_schema: Optional[str]) -> Table:
        """
        Create a table with the appropriate schema based on the table type.

        Args:
            table_name (str): Name of the table to create
            table_type (str): Type of table (used to get schema definition)
            db_schema (Optional[str]): Database schema name

        Returns:
            Table: SQLAlchemy Table object
        """
        try:
            table_schema = get_table_schema_definition(table_type)

            table_ref = f"{db_schema}.{table_name}" if db_schema else table_name
            log_debug(f"Creating table {table_ref} with schema: {table_schema}")

            columns: List[Column] = []
            indexes: List[str] = []
            unique_constraints: List[str] = []
            schema_unique_constraints = table_schema.pop("_unique_constraints", [])

            # Get the columns, indexes, and unique constraints from the table schema
            for col_name, col_config in table_schema.items():
                column_args = [col_name, col_config["type"]()]
                column_kwargs: Dict[str, Any] = {}
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

            # Add multi-column unique constraints with table-specific names
            for constraint in schema_unique_constraints:
                constraint_name = f"{table_name}_{constraint['name']}"
                constraint_columns = constraint["columns"]
                table.append_constraint(UniqueConstraint(*constraint_columns, name=constraint_name))

            # Add indexes to the table definition
            for idx_col in indexes:
                idx_name = f"idx_{table_name}_{idx_col}"
                table.append_constraint(Index(idx_name, idx_col))

            # Create schema if one is specified
            if db_schema is not None:
                with self.Session() as sess, sess.begin():
                    create_schema(session=sess, db_schema=db_schema)

            # SingleStore has a limitation on the number of unique multi-field constraints per table.
            # We need to work around that limitation for the sessions table.
            if table_type == "sessions":
                with self.Session() as sess, sess.begin():
                    # Build column definitions
                    columns_sql = []
                    for col in table.columns:
                        col_sql = f"{col.name} {col.type.compile(self.db_engine.dialect)}"
                        if not col.nullable:
                            col_sql += " NOT NULL"
                        columns_sql.append(col_sql)

                    columns_def = ", ".join(columns_sql)

                    # Add shard key and single unique constraint
                    table_sql = f"""CREATE TABLE IF NOT EXISTS {table_ref} (
                        {columns_def},
                        SHARD KEY (session_id),
                        UNIQUE KEY uq_session_type (session_id, session_type)
                    )"""

                    sess.execute(text(table_sql))
            else:
                table.create(self.db_engine, checkfirst=True)

            # Create indexes
            for idx in table.indexes:
                try:
                    log_debug(f"Creating index: {idx.name}")

                    # Check if index already exists
                    with self.Session() as sess:
                        if db_schema is not None:
                            exists_query = text(
                                "SELECT 1 FROM information_schema.statistics WHERE table_schema = :schema AND index_name = :index_name"
                            )
                            exists = (
                                sess.execute(exists_query, {"schema": db_schema, "index_name": idx.name}).scalar()
                                is not None
                            )
                        else:
                            exists_query = text(
                                "SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() AND index_name = :index_name"
                            )
                            exists = sess.execute(exists_query, {"index_name": idx.name}).scalar() is not None
                        if exists:
                            log_debug(f"Index {idx.name} already exists in {table_ref}, skipping creation")
                            continue

                    idx.create(self.db_engine)

                except Exception as e:
                    log_error(f"Error creating index {idx.name}: {e}")

            log_debug(f"Successfully created table {table_ref}")
            return table

        except Exception as e:
            log_error(f"Could not create table {table_ref}: {e}")
            raise

    def _get_table(self, table_type: str, create_table_if_not_found: Optional[bool] = False) -> Optional[Table]:
        if table_type == "sessions":
            self.session_table = self._get_or_create_table(
                table_name=self.session_table_name,
                table_type="sessions",
                db_schema=self.db_schema,
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.session_table

        if table_type == "memories":
            self.memory_table = self._get_or_create_table(
                table_name=self.memory_table_name,
                table_type="memories",
                db_schema=self.db_schema,
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.memory_table

        if table_type == "metrics":
            self.metrics_table = self._get_or_create_table(
                table_name=self.metrics_table_name,
                table_type="metrics",
                db_schema=self.db_schema,
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.metrics_table

        if table_type == "evals":
            self.eval_table = self._get_or_create_table(
                table_name=self.eval_table_name,
                table_type="evals",
                db_schema=self.db_schema,
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.eval_table

        if table_type == "knowledge":
            self.knowledge_table = self._get_or_create_table(
                table_name=self.knowledge_table_name,
                table_type="knowledge",
                db_schema=self.db_schema,
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.knowledge_table

        raise ValueError(f"Unknown table type: {table_type}")

    def _get_or_create_table(
        self,
        table_name: str,
        table_type: str,
        db_schema: Optional[str],
        create_table_if_not_found: Optional[bool] = False,
    ) -> Optional[Table]:
        """
        Check if the table exists and is valid, else create it.

        Args:
            table_name (str): Name of the table to get or create
            table_type (str): Type of table (used to get schema definition)
            db_schema (Optional[str]): Database schema name

        Returns:
            Table: SQLAlchemy Table object representing the schema.
        """

        with self.Session() as sess, sess.begin():
            table_is_available = is_table_available(session=sess, table_name=table_name, db_schema=db_schema)

        if not table_is_available:
            if not create_table_if_not_found:
                return None
            return self._create_table(table_name=table_name, table_type=table_type, db_schema=db_schema)

        if not is_valid_table(
            db_engine=self.db_engine,
            table_name=table_name,
            table_type=table_type,
            db_schema=db_schema,
        ):
            table_ref = f"{db_schema}.{table_name}" if db_schema else table_name
            raise ValueError(f"Table {table_ref} has an invalid schema")

        try:
            return self._create_table_structure_only(table_name=table_name, table_type=table_type, db_schema=db_schema)

        except Exception as e:
            table_ref = f"{db_schema}.{table_name}" if db_schema else table_name
            log_error(f"Error loading existing table {table_ref}: {e}")
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
            if table is None:
                return False

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
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.session_id.in_(session_ids))
                result = sess.execute(delete_stmt)

            log_debug(f"Successfully deleted {result.rowcount} sessions")

        except Exception as e:
            log_error(f"Error deleting sessions: {e}")

    def get_session(
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
            if table is None:
                return None

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

                session = dict(result._mapping)

            if not deserialize:
                return session

            if session_type == SessionType.AGENT:
                return AgentSession.from_dict(session)
            elif session_type == SessionType.TEAM:
                return TeamSession.from_dict(session)
            elif session_type == SessionType.WORKFLOW:
                return WorkflowSession.from_dict(session)
            else:
                raise ValueError(f"Invalid session type: {session_type}")

        except Exception as e:
            log_error(f"Exception reading from session table: {e}")
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
    ) -> Union[List[Session], Tuple[List[Dict[str, Any]], int]]:
        """
        Get all sessions in the given table. Can filter by user_id and entity_id.

        Args:
            session_type (Optional[SessionType]): The type of session to filter by. Defaults to None.
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
            create_table_if_not_found (Optional[bool]): Whether to create the table if it doesn't exist.

        Returns:
            Union[List[Session], Tuple[List[Dict], int]]:
                - When deserialize=True: List of Session objects
                - When deserialize=False: Tuple of (session dictionaries, total count)

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table = self._get_table(table_type="sessions")
            if table is None:
                return [] if deserialize else ([], 0)

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
                    # SingleStore JSON extraction syntax
                    stmt = stmt.where(
                        func.coalesce(func.JSON_EXTRACT_STRING(table.c.session_data, "session_name"), "").like(
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
                    return [] if deserialize else ([], 0)

                session = [dict(record._mapping) for record in records]
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
            if table is None:
                return None

            with self.Session() as sess, sess.begin():
                stmt = (
                    update(table)
                    .where(table.c.session_id == session_id)
                    .where(table.c.session_type == session_type.value)
                    .values(session_data=func.JSON_SET_STRING(table.c.session_data, "session_name", session_name))
                )
                result = sess.execute(stmt)
                if result.rowcount == 0:
                    return None

                # Fetch the updated record
                select_stmt = select(table).where(table.c.session_id == session_id)
                row = sess.execute(select_stmt).fetchone()
                if not row:
                    return None

            session = dict(row._mapping)

            log_debug(f"Renamed session with id '{session_id}' to '{session_name}'")

            if not deserialize:
                return session

            if session_type == SessionType.AGENT:
                return AgentSession.from_dict(session)
            elif session_type == SessionType.TEAM:
                return TeamSession.from_dict(session)
            elif session_type == SessionType.WORKFLOW:
                return WorkflowSession.from_dict(session)
            else:
                raise ValueError(f"Invalid session type: {session_type}")

        except Exception as e:
            log_error(f"Error renaming session: {e}")
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
            table = self._get_table(table_type="sessions", create_table_if_not_found=True)
            if table is None:
                return None

            session_dict = session.to_dict()

            if isinstance(session, AgentSession):
                with self.Session() as sess, sess.begin():
                    stmt = mysql.insert(table).values(
                        session_id=session_dict.get("session_id"),
                        session_type=SessionType.AGENT.value,
                        agent_id=session_dict.get("agent_id"),
                        user_id=session_dict.get("user_id"),
                        runs=session_dict.get("runs"),
                        agent_data=session_dict.get("agent_data"),
                        session_data=session_dict.get("session_data"),
                        summary=session_dict.get("summary"),
                        metadata=session_dict.get("metadata"),
                        created_at=session_dict.get("created_at"),
                        updated_at=session_dict.get("created_at"),
                    )
                    stmt = stmt.on_duplicate_key_update(
                        agent_id=stmt.inserted.agent_id,
                        user_id=stmt.inserted.user_id,
                        agent_data=stmt.inserted.agent_data,
                        session_data=stmt.inserted.session_data,
                        summary=stmt.inserted.summary,
                        metadata=stmt.inserted.metadata,
                        runs=stmt.inserted.runs,
                        updated_at=int(time.time()),
                    )
                    sess.execute(stmt)

                    # Fetch the result
                    select_stmt = select(table).where(
                        (table.c.session_id == session_dict.get("session_id"))
                        & (table.c.agent_id == session_dict.get("agent_id"))
                    )
                    row = sess.execute(select_stmt).fetchone()
                    if row is None:
                        return None

                    log_debug(f"Upserted session with id '{session_dict.get('session_id')}'")

                    if not deserialize:
                        return row._mapping

                    return AgentSession.from_dict(row._mapping)

            elif isinstance(session, TeamSession):
                with self.Session() as sess, sess.begin():
                    stmt = mysql.insert(table).values(
                        session_id=session_dict.get("session_id"),
                        session_type=SessionType.TEAM.value,
                        team_id=session_dict.get("team_id"),
                        user_id=session_dict.get("user_id"),
                        runs=session_dict.get("runs"),
                        team_data=session_dict.get("team_data"),
                        session_data=session_dict.get("session_data"),
                        summary=session_dict.get("summary"),
                        metadata=session_dict.get("metadata"),
                        created_at=session_dict.get("created_at"),
                        updated_at=session_dict.get("created_at"),
                    )
                    stmt = stmt.on_duplicate_key_update(
                        team_id=stmt.inserted.team_id,
                        user_id=stmt.inserted.user_id,
                        team_data=stmt.inserted.team_data,
                        session_data=stmt.inserted.session_data,
                        summary=stmt.inserted.summary,
                        metadata=stmt.inserted.metadata,
                        runs=stmt.inserted.runs,
                        updated_at=int(time.time()),
                    )
                    sess.execute(stmt)

                    # Fetch the result
                    select_stmt = select(table).where(
                        (table.c.session_id == session_dict.get("session_id"))
                        & (table.c.team_id == session_dict.get("team_id"))
                    )
                    row = sess.execute(select_stmt).fetchone()
                    if row is None:
                        return None

                    log_debug(f"Upserted session with id '{session_dict.get('session_id')}'")

                    if not deserialize:
                        return row._mapping

                    return TeamSession.from_dict(row._mapping)

            else:
                with self.Session() as sess, sess.begin():
                    stmt = mysql.insert(table).values(
                        session_id=session_dict.get("session_id"),
                        session_type=SessionType.WORKFLOW.value,
                        workflow_id=session_dict.get("workflow_id"),
                        user_id=session_dict.get("user_id"),
                        runs=session_dict.get("runs"),
                        workflow_data=session_dict.get("workflow_data"),
                        session_data=session_dict.get("session_data"),
                        summary=session_dict.get("summary"),
                        metadata=session_dict.get("metadata"),
                        created_at=session_dict.get("created_at"),
                        updated_at=session_dict.get("created_at"),
                    )
                    stmt = stmt.on_duplicate_key_update(
                        workflow_id=stmt.inserted.workflow_id,
                        user_id=stmt.inserted.user_id,
                        workflow_data=stmt.inserted.workflow_data,
                        session_data=stmt.inserted.session_data,
                        summary=stmt.inserted.summary,
                        metadata=stmt.inserted.metadata,
                        runs=stmt.inserted.runs,
                        updated_at=int(time.time()),
                    )
                    sess.execute(stmt)

                    # Fetch the result
                    select_stmt = select(table).where(
                        (table.c.session_id == session_dict.get("session_id"))
                        & (table.c.workflow_id == session_dict.get("workflow_id"))
                    )
                    row = sess.execute(select_stmt).fetchone()
                    if row is None:
                        return None

                    log_debug(f"Upserted session with id '{session_dict.get('session_id')}'")

                    if not deserialize:
                        return row._mapping

                    return WorkflowSession.from_dict(row._mapping)

        except Exception as e:
            log_error(f"Error upserting into sessions table: {e}")
            return None

    # -- Memory methods --
    def delete_user_memory(self, memory_id: str):
        """Delete a user memory from the database.

        Args:
            memory_id (str): The ID of the memory to delete.

        Returns:
            bool: True if deletion was successful, False otherwise.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = self._get_table(table_type="memories")
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.memory_id == memory_id)
                result = sess.execute(delete_stmt)

                success = result.rowcount > 0
                if success:
                    log_debug(f"Successfully deleted memory id: {memory_id}")
                else:
                    log_debug(f"No memory found with id: {memory_id}")

        except Exception as e:
            log_error(f"Error deleting memory: {e}")

    def delete_user_memories(self, memory_ids: List[str]) -> None:
        """Delete user memories from the database.

        Args:
            memory_ids (List[str]): The IDs of the memories to delete.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = self._get_table(table_type="memories")
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.memory_id.in_(memory_ids))
                result = sess.execute(delete_stmt)
                if result.rowcount == 0:
                    log_debug(f"No memories found with ids: {memory_ids}")

        except Exception as e:
            log_error(f"Error deleting memories: {e}")

    def get_all_memory_topics(self) -> List[str]:
        """Get all memory topics from the database.

        Returns:
            List[str]: List of memory topics.
        """
        try:
            table = self._get_table(table_type="memories")
            if table is None:
                return []

            with self.Session() as sess, sess.begin():
                stmt = select(table.c.topics)
                result = sess.execute(stmt).fetchall()

                topics = []
                for record in result:
                    if record is not None and record[0] is not None:
                        topic_list = json.loads(record[0]) if isinstance(record[0], str) else record[0]
                        if isinstance(topic_list, list):
                            topics.extend(topic_list)

                return list(set(topics))

        except Exception as e:
            log_error(f"Exception reading from memory table: {e}")
            return []

    def get_user_memory(self, memory_id: str, deserialize: Optional[bool] = True) -> Optional[UserMemory]:
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
            table = self._get_table(table_type="memories")
            if table is None:
                return None

            with self.Session() as sess, sess.begin():
                stmt = select(table).where(table.c.memory_id == memory_id)

                result = sess.execute(stmt).fetchone()
                if not result:
                    return None

                memory_raw = result._mapping
                if not deserialize:
                    return memory_raw
            return UserMemory.from_dict(memory_raw)

        except Exception as e:
            log_error(f"Exception reading from memory table: {e}")
            return None

    def get_user_memories(
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
        try:
            table = self._get_table(table_type="memories")
            if table is None:
                return [] if deserialize else ([], 0)

            with self.Session() as sess, sess.begin():
                stmt = select(table)
                # Filtering
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                if agent_id is not None:
                    stmt = stmt.where(table.c.agent_id == agent_id)
                if team_id is not None:
                    stmt = stmt.where(table.c.team_id == team_id)
                if topics is not None:
                    topic_conditions = [func.JSON_ARRAY_CONTAINS_STRING(table.c.topics, topic) for topic in topics]
                    if topic_conditions:
                        stmt = stmt.where(and_(*topic_conditions))
                if search_content is not None:
                    stmt = stmt.where(table.c.memory.like(f"%{search_content}%"))

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

                memories_raw = [record._mapping for record in result]
                if not deserialize:
                    return memories_raw, total_count

            return [UserMemory.from_dict(record) for record in memories_raw]

        except Exception as e:
            log_error(f"Exception reading from memory table: {e}")
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
            table = self._get_table(table_type="memories")
            if table is None:
                return [], 0

            with self.Session() as sess, sess.begin():
                stmt = (
                    select(
                        table.c.user_id,
                        func.count(table.c.memory_id).label("total_memories"),
                        func.max(table.c.updated_at).label("last_memory_updated_at"),
                    )
                    .where(table.c.user_id.is_not(None))
                    .group_by(table.c.user_id)
                    .order_by(func.max(table.c.updated_at).desc())
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
            log_error(f"Exception getting user memory stats: {e}")
            return [], 0

    def upsert_user_memory(
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
            table = self._get_table(table_type="memories", create_table_if_not_found=True)
            if table is None:
                return None

            with self.Session() as sess, sess.begin():
                if memory.memory_id is None:
                    memory.memory_id = str(uuid4())

                stmt = mysql.insert(table).values(
                    memory_id=memory.memory_id,
                    memory=memory.memory,
                    input=memory.input,
                    user_id=memory.user_id,
                    agent_id=memory.agent_id,
                    team_id=memory.team_id,
                    topics=memory.topics,
                    updated_at=int(time.time()),
                )
                stmt = stmt.on_duplicate_key_update(
                    memory=stmt.inserted.memory,
                    topics=stmt.inserted.topics,
                    input=stmt.inserted.input,
                    user_id=stmt.inserted.user_id,
                    agent_id=stmt.inserted.agent_id,
                    team_id=stmt.inserted.team_id,
                    updated_at=int(time.time()),
                )

                sess.execute(stmt)

                # Fetch the result
                select_stmt = select(table).where(table.c.memory_id == memory.memory_id)
                row = sess.execute(select_stmt).fetchone()
                if row is None:
                    return None

            log_debug(f"Upserted user memory with id '{memory.memory_id}'")

            memory_raw = row._mapping
            if not memory_raw or not deserialize:
                return memory_raw

            return UserMemory.from_dict(memory_raw)

        except Exception as e:
            log_error(f"Error upserting user memory: {e}")
            return None

    def clear_memories(self) -> None:
        """Delete all memories from the database.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = self._get_table(table_type="memories")
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                sess.execute(table.delete())

        except Exception as e:
            log_warning(f"Exception deleting all memories: {e}")

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

            with self.Session() as sess:
                result = sess.execute(stmt).fetchall()
                return [record._mapping for record in result]

        except Exception as e:
            log_error(f"Exception reading from sessions table: {e}")
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
        sessions_result, _ = self.get_sessions(sort_by="created_at", sort_order="asc", limit=1, deserialize=False)
        if not isinstance(sessions_result, list):
            raise ValueError("Error obtaining session list to calculate metrics")

        first_session_date = sessions_result[0]["created_at"] if sessions_result and len(sessions_result) > 0 else None  # type: ignore

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
            table = self._get_table(table_type="metrics", create_table_if_not_found=True)
            if table is None:
                return None

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
                    bulk_upsert_metrics(session=sess, table=table, metrics_records=metrics_records)

            log_debug("Updated metrics calculations")

            return metrics_records

        except Exception as e:
            log_error(f"Error refreshing metrics: {e}")
            raise e

    def get_metrics(
        self,
        starting_date: Optional[date] = None,
        ending_date: Optional[date] = None,
    ) -> Tuple[List[dict], Optional[int]]:
        """Get all metrics matching the given date range.

        Args:
            starting_date (Optional[date]): The starting date to filter metrics by.
            ending_date (Optional[date]): The ending date to filter metrics by.

        Returns:
            Tuple[List[dict], int]: A tuple containing the metrics and the timestamp of the latest update.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table = self._get_table(table_type="metrics", create_table_if_not_found=True)
            if table is None:
                return [], 0

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
            log_error(f"Error getting metrics: {e}")
            return [], None

    # -- Knowledge methods --

    def delete_knowledge_content(self, id: str):
        """Delete a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to delete.
        """
        table = self._get_table(table_type="knowledge")
        if table is None:
            return

        with self.Session() as sess, sess.begin():
            stmt = table.delete().where(table.c.id == id)
            sess.execute(stmt)

        log_debug(f"Deleted knowledge content with id '{id}'")

    def get_knowledge_content(self, id: str) -> Optional[KnowledgeRow]:
        """Get a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to get.

        Returns:
            Optional[KnowledgeRow]: The knowledge row, or None if it doesn't exist.
        """
        table = self._get_table(table_type="knowledge")
        if table is None:
            return None

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
            Tuple[List[KnowledgeRow], int]: The knowledge contents and total count.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        table = self._get_table(table_type="knowledge")
        if table is None:
            return [], 0

        try:
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
                if result is None:
                    return [], 0

                return [KnowledgeRow.model_validate(record._mapping) for record in result], total_count

        except Exception as e:
            log_error(f"Error getting knowledge contents: {e}")
            return [], 0

    def upsert_knowledge_content(self, knowledge_row: KnowledgeRow):
        """Upsert knowledge content in the database.

        Args:
            knowledge_row (KnowledgeRow): The knowledge row to upsert.

        Returns:
            Optional[KnowledgeRow]: The upserted knowledge row, or None if the operation fails.
        """
        try:
            table = self._get_table(table_type="knowledge", create_table_if_not_found=True)
            if table is None:
                return None

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
                        "external_id": knowledge_row.external_id,
                    }.items()
                    if v is not None
                }

                stmt = mysql.insert(table).values(knowledge_row.model_dump())
                stmt = stmt.on_duplicate_key_update(**update_fields)
                sess.execute(stmt)

            log_debug(f"Upserted knowledge source with id '{knowledge_row.id}'")

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
            table = self._get_table(table_type="evals", create_table_if_not_found=True)
            if table is None:
                return None

            with self.Session() as sess, sess.begin():
                current_time = int(time.time())
                stmt = mysql.insert(table).values(
                    {"created_at": current_time, "updated_at": current_time, **eval_run.model_dump()}
                )
                sess.execute(stmt)

            log_debug(f"Created eval run with id '{eval_run.run_id}'")

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
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                stmt = table.delete().where(table.c.run_id == eval_run_id)
                result = sess.execute(stmt)
                if result.rowcount == 0:
                    log_warning(f"No eval run found with ID: {eval_run_id}")
                else:
                    log_debug(f"Deleted eval run with ID: {eval_run_id}")

        except Exception as e:
            log_error(f"Error deleting eval run {eval_run_id}: {e}")
            raise

    def delete_eval_runs(self, eval_run_ids: List[str]) -> None:
        """Delete multiple eval runs from the database.

        Args:
            eval_run_ids (List[str]): List of eval run IDs to delete.
        """
        try:
            table = self._get_table(table_type="evals")
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                stmt = table.delete().where(table.c.run_id.in_(eval_run_ids))
                result = sess.execute(stmt)
                if result.rowcount == 0:
                    log_debug(f"No eval runs found with IDs: {eval_run_ids}")
                else:
                    log_debug(f"Deleted {result.rowcount} eval runs")

        except Exception as e:
            log_error(f"Error deleting eval runs {eval_run_ids}: {e}")
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
            if table is None:
                return None

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
            log_error(f"Exception getting eval run {eval_run_id}: {e}")
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
                - When deserialize=False: List of dictionaries

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table = self._get_table(table_type="evals")
            if table is None:
                return [] if deserialize else ([], 0)

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
                    return [] if deserialize else ([], 0)

                eval_runs_raw = [row._mapping for row in result]
                if not deserialize:
                    return eval_runs_raw, total_count

                return [EvalRunRecord.model_validate(row) for row in eval_runs_raw]

        except Exception as e:
            log_error(f"Exception getting eval runs: {e}")
            return [] if deserialize else ([], 0)

    def rename_eval_run(
        self, eval_run_id: str, name: str, deserialize: Optional[bool] = True
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
            if table is None:
                return None

            with self.Session() as sess, sess.begin():
                stmt = (
                    table.update().where(table.c.run_id == eval_run_id).values(name=name, updated_at=int(time.time()))
                )
                sess.execute(stmt)

            eval_run_raw = self.get_eval_run(eval_run_id=eval_run_id, deserialize=deserialize)

            log_debug(f"Renamed eval run with id '{eval_run_id}' to '{name}'")

            if not eval_run_raw or not deserialize:
                return eval_run_raw

            return EvalRunRecord.model_validate(eval_run_raw)

        except Exception as e:
            log_error(f"Error renaming eval run {eval_run_id}: {e}")
            raise
