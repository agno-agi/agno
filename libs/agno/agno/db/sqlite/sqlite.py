import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple, Union, cast
from uuid import uuid4

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace

from agno.db.base import BaseDb, SessionType
from agno.db.migrations.manager import MigrationManager
from agno.db.schemas.culture import CulturalKnowledge
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.db.sqlite.schemas import get_table_schema_definition
from agno.db.sqlite.utils import (
    apply_sorting,
    bulk_upsert_metrics,
    calculate_date_metrics,
    deserialize_cultural_knowledge_from_db,
    fetch_all_sessions_data,
    get_dates_to_calculate_metrics_for,
    is_table_available,
    is_valid_table,
    serialize_cultural_knowledge_for_db,
)
from agno.db.utils import deserialize_session_json_fields, serialize_session_json_fields
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.string import generate_id

try:
    from sqlalchemy import Column, MetaData, String, Table, func, select, text
    from sqlalchemy.dialects import sqlite
    from sqlalchemy.engine import Engine, create_engine
    from sqlalchemy.orm import scoped_session, sessionmaker
    from sqlalchemy.schema import ForeignKey, Index, UniqueConstraint
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


class SqliteDb(BaseDb):
    def __init__(
        self,
        db_file: Optional[str] = None,
        db_engine: Optional[Engine] = None,
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
        id: Optional[str] = None,
    ):
        """
        Interface for interacting with a SQLite database.

        The following order is used to determine the database connection:
            1. Use the db_engine
            2. Use the db_url
            3. Use the db_file
            4. Create a new database in the current directory

        Args:
            db_file (Optional[str]): The database file to connect to.
            db_engine (Optional[Engine]): The SQLAlchemy database engine to use.
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
            id (Optional[str]): ID of the database.

        Raises:
            ValueError: If none of the tables are provided.
        """
        if id is None:
            seed = db_url or db_file or str(db_engine.url) if db_engine else "sqlite:///agno.db"
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
        )

        _engine: Optional[Engine] = db_engine
        if _engine is None:
            if db_url is not None:
                _engine = create_engine(db_url)
            elif db_file is not None:
                db_path = Path(db_file).resolve()
                db_path.parent.mkdir(parents=True, exist_ok=True)
                db_file = str(db_path)
                _engine = create_engine(f"sqlite:///{db_path}")
            else:
                # If none of db_engine, db_url, or db_file are provided, create a db in the current directory
                default_db_path = Path("./agno.db").resolve()
                _engine = create_engine(f"sqlite:///{default_db_path}")
                db_file = str(default_db_path)
                log_debug(f"Created SQLite database: {default_db_path}")

        self.db_engine: Engine = _engine
        self.db_url: Optional[str] = db_url
        self.db_file: Optional[str] = db_file
        self.metadata: MetaData = MetaData()

        # Initialize database session
        self.Session: scoped_session = scoped_session(sessionmaker(bind=self.db_engine))

    def close(self) -> None:
        """Close database connections and dispose of the connection pool.

        Should be called during application shutdown to properly release
        all database connections.
        """
        if self.db_engine is not None:
            self.db_engine.dispose()

    # -- DB methods --
    def table_exists(self, table_name: str) -> bool:
        """Check if a table with the given name exists in the SQLite database.

        Args:
            table_name: Name of the table to check

        Returns:
            bool: True if the table exists in the database, False otherwise
        """
        with self.Session() as sess:
            return is_table_available(session=sess, table_name=table_name)

    def _create_all_tables(self):
        """Create all tables for the database."""
        tables_to_create = [
            (self.session_table_name, "sessions"),
            (self.memory_table_name, "memories"),
            (self.metrics_table_name, "metrics"),
            (self.eval_table_name, "evals"),
            (self.knowledge_table_name, "knowledge"),
            (self.versions_table_name, "versions"),
        ]

        for table_name, table_type in tables_to_create:
            self._get_or_create_table(table_name=table_name, table_type=table_type, create_table_if_not_found=True)

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
            table_schema = get_table_schema_definition(table_type).copy()

            columns: List[Column] = []
            indexes: List[str] = []
            unique_constraints: List[str] = []
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

                # Handle foreign key constraint
                if "foreign_key" in col_config:
                    fk_ref = col_config["foreign_key"]
                    # For spans table, dynamically replace the traces table reference
                    # with the actual trace table name configured for this db instance
                    if table_type == "spans" and "trace_id" in fk_ref:
                        fk_ref = f"{self.trace_table_name}.trace_id"
                    column_args.append(ForeignKey(fk_ref))

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

            # Create table
            table_created = False
            if not self.table_exists(table_name):
                table.create(self.db_engine, checkfirst=True)
                log_debug(f"Successfully created table '{table_name}'")
                table_created = True
            else:
                log_debug(f"Table '{table_name}' already exists, skipping creation")

            # Create indexes
            for idx in table.indexes:
                try:
                    # Check if index already exists
                    with self.Session() as sess:
                        exists_query = text("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = :index_name")
                        exists = sess.execute(exists_query, {"index_name": idx.name}).scalar() is not None
                        if exists:
                            log_debug(f"Index {idx.name} already exists in table {table_name}, skipping creation")
                            continue

                    idx.create(self.db_engine)

                    log_debug(f"Created index: {idx.name} for table {table_name}")
                except Exception as e:
                    log_warning(f"Error creating index {idx.name}: {e}")

            # Store the schema version for the created table
            if table_name != self.versions_table_name and table_created:
                latest_schema_version = MigrationManager(self).latest_schema_version
                self.upsert_schema_version(table_name=table_name, version=latest_schema_version.public)

            return table

        except Exception as e:
            from traceback import print_exc

            print_exc()
            log_error(f"Could not create table '{table_name}': {e}")
            raise e

    def _get_table(self, table_type: str, create_table_if_not_found: Optional[bool] = False) -> Optional[Table]:
        if table_type == "sessions":
            self.session_table = self._get_or_create_table(
                table_name=self.session_table_name,
                table_type=table_type,
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.session_table

        elif table_type == "memories":
            self.memory_table = self._get_or_create_table(
                table_name=self.memory_table_name,
                table_type="memories",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.memory_table

        elif table_type == "metrics":
            self.metrics_table = self._get_or_create_table(
                table_name=self.metrics_table_name,
                table_type="metrics",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.metrics_table

        elif table_type == "evals":
            self.eval_table = self._get_or_create_table(
                table_name=self.eval_table_name,
                table_type="evals",
                create_table_if_not_found=create_table_if_not_found,
            )

            return self.eval_table

        elif table_type == "knowledge":
            self.knowledge_table = self._get_or_create_table(
                table_name=self.knowledge_table_name,
                table_type="knowledge",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.knowledge_table

        elif table_type == "traces":
            self.traces_table = self._get_or_create_table(
                table_name=self.trace_table_name,
                table_type="traces",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.traces_table

        elif table_type == "spans":
            # Ensure traces table exists first (spans has FK to traces)
            if create_table_if_not_found:
                self._get_table(table_type="traces", create_table_if_not_found=True)

            self.spans_table = self._get_or_create_table(
                table_name=self.span_table_name,
                table_type="spans",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.spans_table

        elif table_type == "culture":
            self.culture_table = self._get_or_create_table(
                table_name=self.culture_table_name,
                table_type="culture",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.culture_table

        elif table_type == "versions":
            self.versions_table = self._get_or_create_table(
                table_name=self.versions_table_name,
                table_type="versions",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.versions_table

        else:
            raise ValueError(f"Unknown table type: '{table_type}'")

    def _get_or_create_table(
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
        with self.Session() as sess, sess.begin():
            table_is_available = is_table_available(session=sess, table_name=table_name)

        if not table_is_available:
            if not create_table_if_not_found:
                return None
            return self._create_table(table_name=table_name, table_type=table_type)

        # SQLite version of table validation (no schema)
        if not is_valid_table(db_engine=self.db_engine, table_name=table_name, table_type=table_type):
            raise ValueError(f"Table {table_name} has an invalid schema")

        try:
            table = Table(table_name, self.metadata, autoload_with=self.db_engine)
            return table

        except Exception as e:
            log_error(f"Error loading existing table {table_name}: {e}")
            raise e

    def get_latest_schema_version(self, table_name: str):
        """Get the latest version of the database schema."""
        table = self._get_table(table_type="versions", create_table_if_not_found=True)
        if table is None:
            return "2.0.0"
        with self.Session() as sess:
            stmt = select(table)
            # Latest version for the given table
            stmt = stmt.where(table.c.table_name == table_name)
            stmt = stmt.order_by(table.c.version.desc()).limit(1)
            result = sess.execute(stmt).fetchone()
            if result is None:
                return "2.0.0"
            version_dict = dict(result._mapping)
            return version_dict.get("version") or "2.0.0"

    def upsert_schema_version(self, table_name: str, version: str) -> None:
        """Upsert the schema version into the database."""
        table = self._get_table(table_type="versions", create_table_if_not_found=True)
        if table is None:
            return
        current_datetime = datetime.now().isoformat()
        with self.Session() as sess, sess.begin():
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
            sess.execute(stmt)

    # -- Session methods --

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session from the database.

        Args:
            session_id (str): ID of the session to delete

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
                    log_debug(f"No session found to deletewith session_id: {session_id}")
                    return False
                else:
                    log_debug(f"Successfully deleted session with session_id: {session_id}")
                    return True

        except Exception as e:
            log_error(f"Error deleting session: {e}")
            raise e

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
            raise e

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
            table = self._get_table(table_type="sessions")
            if table is None:
                return None

            with self.Session() as sess, sess.begin():
                stmt = select(table).where(table.c.session_id == session_id)

                # Filtering
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)

                result = sess.execute(stmt).fetchone()
                if result is None:
                    return None

                session_raw = deserialize_session_json_fields(dict(result._mapping))
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
            create_table_if_not_found (Optional[bool]): Whether to create the table if it doesn't exist.

        Returns:
            List[Session]:
                - When deserialize=True: List of Session objects matching the criteria.
                - When deserialize=False: List of Session dictionaries matching the criteria.

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
                    stmt = stmt.where(table.c.session_data.like(f"%{session_name}%"))
                if session_type is not None:
                    stmt = stmt.where(table.c.session_type == session_type.value)

                # Getting total count
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

    def rename_session(
        self,
        session_id: str,
        session_type: SessionType,
        session_name: str,
        deserialize: Optional[bool] = True,
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
            # Get the current session as a deserialized object
            # Get the session record
            session = self.get_session(session_id, session_type, deserialize=True)
            if session is None:
                return None

            session = cast(Session, session)
            # Update the session name
            if session.session_data is None:
                session.session_data = {}
            session.session_data["session_name"] = session_name

            # Upsert the updated session back to the database
            return self.upsert_session(session, deserialize=deserialize)

        except Exception as e:
            log_error(f"Exception renaming session: {e}")
            raise e

    def upsert_session(
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
            table = self._get_table(table_type="sessions", create_table_if_not_found=True)
            if table is None:
                return None

            serialized_session = serialize_session_json_fields(session.to_dict())

            if isinstance(session, AgentSession):
                with self.Session() as sess, sess.begin():
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
                    )
                    stmt = stmt.returning(*table.columns)  # type: ignore
                    result = sess.execute(stmt)
                    row = result.fetchone()

                    session_raw = deserialize_session_json_fields(dict(row._mapping)) if row else None
                    if session_raw is None or not deserialize:
                        return session_raw
                    return AgentSession.from_dict(session_raw)

            elif isinstance(session, TeamSession):
                with self.Session() as sess, sess.begin():
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
                    )
                    stmt = stmt.returning(*table.columns)  # type: ignore
                    result = sess.execute(stmt)
                    row = result.fetchone()

                    session_raw = deserialize_session_json_fields(dict(row._mapping)) if row else None
                    if session_raw is None or not deserialize:
                        return session_raw
                    return TeamSession.from_dict(session_raw)

            else:
                with self.Session() as sess, sess.begin():
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
                    )
                    stmt = stmt.returning(*table.columns)  # type: ignore
                    result = sess.execute(stmt)
                    row = result.fetchone()

                    session_raw = deserialize_session_json_fields(dict(row._mapping)) if row else None
                    if session_raw is None or not deserialize:
                        return session_raw
                    return WorkflowSession.from_dict(session_raw)

        except Exception as e:
            log_warning(f"Exception upserting into table: {e}")
            raise e

    def upsert_sessions(
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
            table = self._get_table(table_type="sessions", create_table_if_not_found=True)
            if table is None:
                log_info("Sessions table not available, falling back to individual upserts")
                return [
                    result
                    for session in sessions
                    if session is not None
                    for result in [self.upsert_session(session, deserialize=deserialize)]
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

            with self.Session() as sess, sess.begin():
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
                        sess.execute(stmt, agent_data)

                        # Fetch the results for agent sessions
                        agent_ids = [session.session_id for session in agent_sessions]
                        select_stmt = select(table).where(table.c.session_id.in_(agent_ids))
                        result = sess.execute(select_stmt).fetchall()

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
                        sess.execute(stmt, team_data)

                        # Fetch the results for team sessions
                        team_ids = [session.session_id for session in team_sessions]
                        select_stmt = select(table).where(table.c.session_id.in_(team_ids))
                        result = sess.execute(select_stmt).fetchall()

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
                        sess.execute(stmt, workflow_data)

                        # Fetch the results for workflow sessions
                        workflow_ids = [session.session_id for session in workflow_sessions]
                        select_stmt = select(table).where(table.c.session_id.in_(workflow_ids))
                        result = sess.execute(select_stmt).fetchall()

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
                for result in [self.upsert_session(session, deserialize=deserialize)]
                if result is not None
            ]

    # -- Memory methods --

    def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None):
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
            table = self._get_table(table_type="memories")
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.memory_id == memory_id)
                if user_id is not None:
                    delete_stmt = delete_stmt.where(table.c.user_id == user_id)
                result = sess.execute(delete_stmt)

                success = result.rowcount > 0
                if success:
                    log_debug(f"Successfully deleted user memory id: {memory_id}")
                else:
                    log_debug(f"No user memory found with id: {memory_id}")

        except Exception as e:
            log_error(f"Error deleting user memory: {e}")
            raise e

    def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete user memories from the database.

        Args:
            memory_ids (List[str]): The IDs of the memories to delete.
            user_id (Optional[str]): The user ID to filter by. Defaults to None.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = self._get_table(table_type="memories")
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.memory_id.in_(memory_ids))
                if user_id is not None:
                    delete_stmt = delete_stmt.where(table.c.user_id == user_id)
                result = sess.execute(delete_stmt)
                if result.rowcount == 0:
                    log_debug(f"No user memories found with ids: {memory_ids}")

        except Exception as e:
            log_error(f"Error deleting user memories: {e}")
            raise e

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
                # Select topics from all results
                stmt = select(table.c.topics)
                result = sess.execute(stmt).fetchall()
                return list(set([record[0] for record in result]))

        except Exception as e:
            log_debug(f"Exception reading from memory table: {e}")
            raise e

    def get_user_memory(
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
            table = self._get_table(table_type="memories")
            if table is None:
                return None

            with self.Session() as sess, sess.begin():
                stmt = select(table).where(table.c.memory_id == memory_id)
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                result = sess.execute(stmt).fetchone()
                if result is None:
                    return None

                memory_raw = dict(result._mapping)
                if not memory_raw or not deserialize:
                    return memory_raw

            return UserMemory.from_dict(memory_raw)

        except Exception as e:
            log_debug(f"Exception reading from memorytable: {e}")
            raise e

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
                - When deserialize=False: List of UserMemory dictionaries and total count

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
                    for topic in topics:
                        stmt = stmt.where(func.cast(table.c.topics, String).like(f'%"{topic}"%'))
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

                memories_raw = [record._mapping for record in result]

                if not deserialize:
                    return memories_raw, total_count

            return [UserMemory.from_dict(record) for record in memories_raw]

        except Exception as e:
            log_error(f"Error reading from memory table: {e}")
            raise e

    def get_user_memory_stats(
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
            table = self._get_table(table_type="memories")
            if table is None:
                return [], 0

            with self.Session() as sess, sess.begin():
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
                total_count = sess.execute(count_stmt).scalar() or 0

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
            log_error(f"Error getting user memory stats: {e}")
            raise e

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

            if memory.memory_id is None:
                memory.memory_id = str(uuid4())

            current_time = int(time.time())

            with self.Session() as sess, sess.begin():
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

                result = sess.execute(stmt)
                row = result.fetchone()

                if row is None:
                    return None

            memory_raw = row._mapping
            if not memory_raw or not deserialize:
                return memory_raw

            return UserMemory.from_dict(memory_raw)

        except Exception as e:
            log_error(f"Error upserting user memory: {e}")
            raise e

    def upsert_memories(
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
            table = self._get_table(table_type="memories", create_table_if_not_found=True)
            if table is None:
                log_info("Memories table not available, falling back to individual upserts")
                return [
                    result
                    for memory in memories
                    if memory is not None
                    for result in [self.upsert_user_memory(memory, deserialize=deserialize)]
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

            with self.Session() as sess, sess.begin():
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
                sess.execute(stmt, bulk_data)

                # Fetch results
                memory_ids = [memory.memory_id for memory in memories if memory.memory_id]
                select_stmt = select(table).where(table.c.memory_id.in_(memory_ids))
                result = sess.execute(select_stmt).fetchall()

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
                for result in [self.upsert_user_memory(memory, deserialize=deserialize)]
                if result is not None
            ]

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
            from agno.utils.log import log_warning

            log_warning(f"Exception deleting all memories: {e}")
            raise e

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
            log_error(f"Error reading from sessions table: {e}")
            raise e

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
        first_session_date = first_session[0]["created_at"] if first_session else None  # type: ignore

        # 3. No metrics records and no sessions records. Return None.
        if not first_session_date:
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

            start_timestamp = int(
                datetime.combine(dates_to_process[0], datetime.min.time()).replace(tzinfo=timezone.utc).timestamp()
            )
            end_timestamp = int(
                datetime.combine(dates_to_process[-1] + timedelta(days=1), datetime.min.time())
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )

            sessions = self._get_all_sessions_for_metrics_calculation(
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
                with self.Session() as sess, sess.begin():
                    results = bulk_upsert_metrics(session=sess, table=table, metrics_records=metrics_records)

            log_debug("Updated metrics calculations")

            return results

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
            Tuple[List[dict], Optional[int]]: A tuple containing the metrics and the timestamp of the latest update.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table = self._get_table(table_type="metrics", create_table_if_not_found=True)
            if table is None:
                return [], None

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
            raise e

    # -- Knowledge methods --

    def delete_knowledge_content(self, id: str):
        """Delete a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to delete.

        Raises:
            Exception: If an error occurs during deletion.
        """
        table = self._get_table(table_type="knowledge")
        if table is None:
            return

        try:
            with self.Session() as sess, sess.begin():
                stmt = table.delete().where(table.c.id == id)
                sess.execute(stmt)

        except Exception as e:
            log_error(f"Error deleting knowledge content: {e}")
            raise e

    def get_knowledge_content(self, id: str) -> Optional[KnowledgeRow]:
        """Get a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to get.

        Returns:
            Optional[KnowledgeRow]: The knowledge row, or None if it doesn't exist.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        table = self._get_table(table_type="knowledge")
        if table is None:
            return None

        try:
            with self.Session() as sess, sess.begin():
                stmt = select(table).where(table.c.id == id)
                result = sess.execute(stmt).fetchone()
                if result is None:
                    return None

                return KnowledgeRow.model_validate(result._mapping)

        except Exception as e:
            log_error(f"Error getting knowledge content: {e}")
            raise e

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
                return [KnowledgeRow.model_validate(record._mapping) for record in result], total_count

        except Exception as e:
            log_error(f"Error getting knowledge contents: {e}")
            raise e

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
                sess.execute(stmt)

            return knowledge_row

        except Exception as e:
            log_error(f"Error upserting knowledge content: {e}")
            raise e

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
                stmt = sqlite.insert(table).values(
                    {
                        "created_at": current_time,
                        "updated_at": current_time,
                        **eval_run.model_dump(),
                    }
                )
                sess.execute(stmt)
                sess.commit()

            log_debug(f"Created eval run with id '{eval_run.run_id}'")

            return eval_run

        except Exception as e:
            log_error(f"Error creating eval run: {e}")
            raise e

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
            raise e

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
            raise e

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
                if not eval_run_raw or not deserialize:
                    return eval_run_raw

            return EvalRunRecord.model_validate(eval_run_raw)

        except Exception as e:
            log_error(f"Exception getting eval run {eval_run_id}: {e}")
            raise e

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
                - When deserialize=False: List of EvalRun dictionaries and total count

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

                result = sess.execute(stmt).fetchall()
                if not result:
                    return [] if deserialize else ([], 0)

                eval_runs_raw = [row._mapping for row in result]
                if not deserialize:
                    return eval_runs_raw, total_count

            return [EvalRunRecord.model_validate(row) for row in eval_runs_raw]

        except Exception as e:
            log_error(f"Exception getting eval runs: {e}")
            raise e

    def rename_eval_run(
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
            raise e

    # -- Trace methods --

    def _get_traces_base_query(self, table: Table, spans_table: Optional[Table] = None):
        """Build base query for traces with aggregated span counts.

        Args:
            table: The traces table.
            spans_table: The spans table (optional).

        Returns:
            SQLAlchemy select statement with total_spans and error_count calculated dynamically.
        """
        from sqlalchemy import case, func, literal

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

    def upsert_trace(self, trace: "Trace") -> None:
        """Create or update a single trace record in the database.

        Uses INSERT ... ON CONFLICT DO UPDATE (upsert) to handle concurrent inserts
        atomically and avoid race conditions.

        Args:
            trace: The Trace object to store (one per trace_id).
        """
        from sqlalchemy import case

        try:
            table = self._get_table(table_type="traces", create_table_if_not_found=True)
            if table is None:
                return

            trace_dict = trace.to_dict()
            trace_dict.pop("total_spans", None)
            trace_dict.pop("error_count", None)

            with self.Session() as sess, sess.begin():
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
                sess.execute(upsert_stmt)

        except Exception as e:
            log_error(f"Error creating trace: {e}")
            # Don't raise - tracing should not break the main application flow

    def get_trace(
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

            table = self._get_table(table_type="traces")
            if table is None:
                return None

            # Get spans table for JOIN
            spans_table = self._get_table(table_type="spans")

            with self.Session() as sess:
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
                result = sess.execute(stmt).fetchone()

                if result:
                    return Trace.from_dict(dict(result._mapping))
                return None

        except Exception as e:
            log_error(f"Error getting trace: {e}")
            return None

    def get_traces(
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
            from sqlalchemy import func

            from agno.tracing.schemas import Trace

            log_debug(
                f"get_traces called with filters: run_id={run_id}, session_id={session_id}, user_id={user_id}, agent_id={agent_id}, page={page}, limit={limit}"
            )

            table = self._get_table(table_type="traces")
            if table is None:
                log_debug(" Traces table not found")
                return [], 0

            # Get spans table for JOIN
            spans_table = self._get_table(table_type="spans")

            with self.Session() as sess:
                # Build base query with aggregated span counts
                base_stmt = self._get_traces_base_query(table, spans_table)

                # Apply filters
                if run_id:
                    base_stmt = base_stmt.where(table.c.run_id == run_id)
                if session_id:
                    base_stmt = base_stmt.where(table.c.session_id == session_id)
                if user_id:
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
                total_count = sess.execute(count_stmt).scalar() or 0

                # Apply pagination
                offset = (page - 1) * limit if page and limit else 0
                paginated_stmt = base_stmt.order_by(table.c.start_time.desc()).limit(limit).offset(offset)

                results = sess.execute(paginated_stmt).fetchall()

                traces = [Trace.from_dict(dict(row._mapping)) for row in results]
                return traces, total_count

        except Exception as e:
            log_error(f"Error getting traces: {e}")
            return [], 0

    def get_trace_stats(
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
        """
        try:
            from sqlalchemy import func

            table = self._get_table(table_type="traces")
            if table is None:
                log_debug("Traces table not found")
                return [], 0

            with self.Session() as sess:
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
                if user_id:
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
                total_count = sess.execute(count_stmt).scalar() or 0

                # Apply pagination and ordering
                offset = (page - 1) * limit if page and limit else 0
                paginated_stmt = base_stmt.order_by(func.max(table.c.created_at).desc()).limit(limit).offset(offset)

                results = sess.execute(paginated_stmt).fetchall()

                # Convert to list of dicts with datetime objects
                from datetime import datetime

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

    # -- Span methods --

    def create_span(self, span: "Span") -> None:
        """Create a single span in the database.

        Args:
            span: The Span object to store.
        """
        try:
            table = self._get_table(table_type="spans", create_table_if_not_found=True)
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                stmt = sqlite.insert(table).values(span.to_dict())
                sess.execute(stmt)

        except Exception as e:
            log_error(f"Error creating span: {e}")

    def create_spans(self, spans: List) -> None:
        """Create multiple spans in the database as a batch.

        Args:
            spans: List of Span objects to store.
        """
        if not spans:
            return

        try:
            table = self._get_table(table_type="spans", create_table_if_not_found=True)
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                for span in spans:
                    stmt = sqlite.insert(table).values(span.to_dict())
                    sess.execute(stmt)

        except Exception as e:
            log_error(f"Error creating spans batch: {e}")

    def get_span(self, span_id: str):
        """Get a single span by its span_id.

        Args:
            span_id: The unique span identifier.

        Returns:
            Optional[Span]: The span if found, None otherwise.
        """
        try:
            from agno.tracing.schemas import Span

            table = self._get_table(table_type="spans")
            if table is None:
                return None

            with self.Session() as sess:
                stmt = table.select().where(table.c.span_id == span_id)
                result = sess.execute(stmt).fetchone()
                if result:
                    return Span.from_dict(dict(result._mapping))
                return None

        except Exception as e:
            log_error(f"Error getting span: {e}")
            return None

    def get_spans(
        self,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
    ) -> List:
        """Get spans matching the provided filters.

        Args:
            trace_id: Filter by trace ID.
            parent_span_id: Filter by parent span ID.

        Returns:
            List[Span]: List of matching spans.
        """
        try:
            from agno.tracing.schemas import Span

            table = self._get_table(table_type="spans")
            if table is None:
                return []

            with self.Session() as sess:
                stmt = table.select()

                # Apply filters
                if trace_id:
                    stmt = stmt.where(table.c.trace_id == trace_id)
                if parent_span_id:
                    stmt = stmt.where(table.c.parent_span_id == parent_span_id)

                results = sess.execute(stmt).fetchall()
                return [Span.from_dict(dict(row._mapping)) for row in results]

        except Exception as e:
            log_error(f"Error getting spans: {e}")
            return []

    # -- Migrations --

    def migrate_table_from_v1_to_v2(self, v1_db_schema: str, v1_table_name: str, v1_table_type: str):
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
                self.upsert_session(session)
            log_info(f"Migrated {len(sessions)} Agent sessions to table: {self.session_table_name}")

        elif v1_table_type == "team_sessions":
            for session in sessions:
                self.upsert_session(session)
            log_info(f"Migrated {len(sessions)} Team sessions to table: {self.session_table_name}")

        elif v1_table_type == "workflow_sessions":
            for session in sessions:
                self.upsert_session(session)
            log_info(f"Migrated {len(sessions)} Workflow sessions to table: {self.session_table_name}")

        elif v1_table_type == "memories":
            for memory in memories:
                self.upsert_user_memory(memory)
            log_info(f"Migrated {len(memories)} memories to table: {self.memory_table}")

    # -- Culture methods --

    def clear_cultural_knowledge(self) -> None:
        """Delete all cultural artifacts from the database.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = self._get_table(table_type="culture")
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                sess.execute(table.delete())

        except Exception as e:
            from agno.utils.log import log_warning

            log_warning(f"Exception deleting all cultural artifacts: {e}")
            raise e

    def delete_cultural_knowledge(self, id: str) -> None:
        """Delete a cultural artifact from the database.

        Args:
            id (str): The ID of the cultural artifact to delete.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = self._get_table(table_type="culture")
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.id == id)
                result = sess.execute(delete_stmt)

                success = result.rowcount > 0
                if success:
                    log_debug(f"Successfully deleted cultural artifact id: {id}")
                else:
                    log_debug(f"No cultural artifact found with id: {id}")

        except Exception as e:
            log_error(f"Error deleting cultural artifact: {e}")
            raise e

    def get_cultural_knowledge(
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
            table = self._get_table(table_type="culture")
            if table is None:
                return None

            with self.Session() as sess, sess.begin():
                stmt = select(table).where(table.c.id == id)
                result = sess.execute(stmt).fetchone()
                if result is None:
                    return None

                db_row = dict(result._mapping)
                if not db_row or not deserialize:
                    return db_row

            return deserialize_cultural_knowledge_from_db(db_row)

        except Exception as e:
            log_error(f"Exception reading from cultural artifacts table: {e}")
            raise e

    def get_all_cultural_knowledge(
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
            table = self._get_table(table_type="culture")
            if table is None:
                return [] if deserialize else ([], 0)

            with self.Session() as sess, sess.begin():
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

                db_rows = [dict(record._mapping) for record in result]

                if not deserialize:
                    return db_rows, total_count

            return [deserialize_cultural_knowledge_from_db(row) for row in db_rows]

        except Exception as e:
            log_error(f"Error reading from cultural artifacts table: {e}")
            raise e

    def upsert_cultural_knowledge(
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
            table = self._get_table(table_type="culture", create_table_if_not_found=True)
            if table is None:
                return None

            if cultural_knowledge.id is None:
                cultural_knowledge.id = str(uuid4())

            # Serialize content, categories, and notes into a JSON string for DB storage (SQLite requires strings)
            content_json_str = serialize_cultural_knowledge_for_db(cultural_knowledge)

            with self.Session() as sess, sess.begin():
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

                result = sess.execute(stmt)
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
