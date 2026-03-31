import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace

from agno.db.base import BaseDb, SessionType
from agno.db.migrations.manager import MigrationManager
from agno.db.schemas.culture import CulturalKnowledge
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.db.singlestore.schemas import get_table_schema_definition
from agno.db.singlestore.utils import (
    apply_sorting,
    bulk_upsert_metrics,
    calculate_date_metrics,
    create_schema,
    deserialize_cultural_knowledge_from_db,
    fetch_all_sessions_data,
    get_dates_to_calculate_metrics_for,
    is_table_available,
    is_valid_table,
    serialize_cultural_knowledge_for_db,
)
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.string import generate_id

try:
    from sqlalchemy import ForeignKey, Index, UniqueConstraint, and_, func, select, update
    from sqlalchemy.dialects import mysql
    from sqlalchemy.engine import Engine, create_engine
    from sqlalchemy.orm import scoped_session, sessionmaker
    from sqlalchemy.schema import Column, MetaData, Table
    from sqlalchemy.sql.expression import text
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
        culture_table: Optional[str] = None,
        memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
        versions_table: Optional[str] = None,
        traces_table: Optional[str] = None,
        spans_table: Optional[str] = None,
        create_schema: bool = True,
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
            culture_table (Optional[str]): Name of the table to store cultural knowledge.
            memory_table (Optional[str]): Name of the table to store memories.
            metrics_table (Optional[str]): Name of the table to store metrics.
            eval_table (Optional[str]): Name of the table to store evaluation runs data.
            knowledge_table (Optional[str]): Name of the table to store knowledge content.
            versions_table (Optional[str]): Name of the table to store schema versions.
            create_schema (bool): Whether to automatically create the database schema if it doesn't exist.
                Set to False if schema is managed externally (e.g., via migrations). Defaults to True.
        Raises:
            ValueError: If neither db_url nor db_engine is provided.
            ValueError: If none of the tables are provided.
        """
        if id is None:
            base_seed = db_url or str(db_engine.url) if db_engine else "singlestore"  # type: ignore
            schema_suffix = db_schema if db_schema is not None else "ai"
            seed = f"{base_seed}#{schema_suffix}"
            id = generate_id(seed)

        super().__init__(
            id=id,
            session_table=session_table,
            culture_table=culture_table,
            memory_table=memory_table,
            metrics_table=metrics_table,
            eval_table=eval_table,
            knowledge_table=knowledge_table,
            versions_table=versions_table,
            traces_table=traces_table,
            spans_table=spans_table,
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
        self.metadata: MetaData = MetaData(schema=self.db_schema)
        self.create_schema: bool = create_schema

        # Initialize database session
        self.Session: scoped_session = scoped_session(sessionmaker(bind=self.db_engine))

    # -- DB methods --
    def table_exists(self, table_name: str) -> bool:
        """Check if a table with the given name exists in the SingleStore database.

        Args:
            table_name: Name of the table to check

        Returns:
            bool: True if the table exists in the database, False otherwise
        """
        with self.Session() as sess:
            return is_table_available(session=sess, table_name=table_name, db_schema=self.db_schema)

    def _create_table_structure_only(self, table_name: str, table_type: str) -> Table:
        """
        Create a table structure definition without actually creating the table in the database.
        Used to avoid autoload issues with SingleStore JSON types.

        Args:
            table_name (str): Name of the table
            table_type (str): Type of table (used to get schema definition)

        Returns:
            Table: SQLAlchemy Table object with column definitions
        """
        try:
            # Pass traces_table_name and db_schema for spans table foreign key resolution
            table_schema = get_table_schema_definition(
                table_type, traces_table_name=self.trace_table_name, db_schema=self.db_schema or "agno"
            )

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

            table = Table(table_name, self.metadata, *columns, schema=self.db_schema, extend_existing=True)

            return table

        except Exception as e:
            table_ref = f"{self.db_schema}.{table_name}" if self.db_schema else table_name
            log_error(f"Could not create table structure for {table_ref}: {e}")
            raise

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
        table_ref = f"{self.db_schema}.{table_name}" if self.db_schema else table_name
        try:
            # Pass traces_table_name and db_schema for spans table foreign key resolution
            table_schema = get_table_schema_definition(
                table_type, traces_table_name=self.trace_table_name, db_schema=self.db_schema or "agno"
            ).copy()

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

                # Handle foreign key constraint
                if "foreign_key" in col_config:
                    column_args.append(ForeignKey(col_config["foreign_key"]))

                columns.append(Column(*column_args, **column_kwargs))

            table = Table(table_name, self.metadata, *columns, schema=self.db_schema, extend_existing=True)

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
            if self.create_schema and self.db_schema is not None:
                with self.Session() as sess, sess.begin():
                    create_schema(session=sess, db_schema=self.db_schema)

            # SingleStore has a limitation on the number of unique multi-field constraints per table.
            # We need to work around that limitation for the sessions table.
            table_created = False
            if not self.table_exists(table_name):
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

                        # Add primary key, shard key and unique constraint
                        table_sql = f"""CREATE TABLE IF NOT EXISTS {table_ref} (
                            {columns_def},
                            PRIMARY KEY (session_id),
                            SHARD KEY (session_id),
                            UNIQUE KEY uq_session_type (session_id, session_type)
                        )"""

                        sess.execute(text(table_sql))
                else:
                    table.create(self.db_engine, checkfirst=True)
                log_debug(f"Successfully created table '{table_ref}'")
                table_created = True
            else:
                log_debug(f"Table '{table_ref}' already exists, skipping creation")

            # Create indexes
            for idx in table.indexes:
                try:
                    # Check if index already exists
                    with self.Session() as sess:
                        if self.db_schema is not None:
                            exists_query = text(
                                "SELECT 1 FROM information_schema.statistics WHERE table_schema = :schema AND index_name = :index_name"
                            )
                            exists = (
                                sess.execute(exists_query, {"schema": self.db_schema, "index_name": idx.name}).scalar()
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

                    log_debug(f"Created index: {idx.name} for table {table_ref}")
                except Exception as e:
                    log_error(f"Error creating index {idx.name}: {e}")

            # Store the schema version for the created table
            if table_name != self.versions_table_name and table_created:
                latest_schema_version = MigrationManager(self).latest_schema_version
                self.upsert_schema_version(table_name=table_name, version=latest_schema_version.public)

            return table

        except Exception as e:
            log_error(f"Could not create table {table_ref}: {e}")
            raise

    def _get_table(self, table_type: str, create_table_if_not_found: Optional[bool] = False) -> Optional[Table]:
        if table_type == "sessions":
            self.session_table = self._get_or_create_table(
                table_name=self.session_table_name,
                table_type="sessions",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.session_table

        if table_type == "memories":
            self.memory_table = self._get_or_create_table(
                table_name=self.memory_table_name,
                table_type="memories",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.memory_table

        if table_type == "metrics":
            self.metrics_table = self._get_or_create_table(
                table_name=self.metrics_table_name,
                table_type="metrics",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.metrics_table

        if table_type == "evals":
            self.eval_table = self._get_or_create_table(
                table_name=self.eval_table_name,
                table_type="evals",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.eval_table

        if table_type == "knowledge":
            self.knowledge_table = self._get_or_create_table(
                table_name=self.knowledge_table_name,
                table_type="knowledge",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.knowledge_table

        if table_type == "culture":
            self.culture_table = self._get_or_create_table(
                table_name=self.culture_table_name,
                table_type="culture",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.culture_table

        if table_type == "versions":
            self.versions_table = self._get_or_create_table(
                table_name=self.versions_table_name,
                table_type="versions",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.versions_table

        if table_type == "traces":
            self.traces_table = self._get_or_create_table(
                table_name=self.trace_table_name,
                table_type="traces",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.traces_table

        if table_type == "spans":
            # Ensure traces table exists first (for foreign key)
            if create_table_if_not_found:
                self._get_table(table_type="traces", create_table_if_not_found=True)
            self.spans_table = self._get_or_create_table(
                table_name=self.span_table_name,
                table_type="spans",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.spans_table

        raise ValueError(f"Unknown table type: {table_type}")

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
            Table: SQLAlchemy Table object representing the schema.
        """

        with self.Session() as sess, sess.begin():
            table_is_available = is_table_available(session=sess, table_name=table_name, db_schema=self.db_schema)

        if not table_is_available:
            if not create_table_if_not_found:
                return None

            # Also store the schema version for the created table
            if table_name != self.versions_table_name:
                latest_schema_version = MigrationManager(self).latest_schema_version
                self.upsert_schema_version(table_name=table_name, version=latest_schema_version.public)

            return self._create_table(table_name=table_name, table_type=table_type)

        if not is_valid_table(
            db_engine=self.db_engine,
            table_name=table_name,
            table_type=table_type,
            db_schema=self.db_schema,
        ):
            table_ref = f"{self.db_schema}.{table_name}" if self.db_schema else table_name
            raise ValueError(f"Table {table_ref} has an invalid schema")

        try:
            return self._create_table_structure_only(table_name=table_name, table_type=table_type)

        except Exception as e:
            table_ref = f"{self.db_schema}.{table_name}" if self.db_schema else table_name
            log_error(f"Error loading existing table {table_ref}: {e}")
            raise

    def get_latest_schema_version(self, table_name: str) -> str:
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
            stmt = mysql.insert(table).values(
                table_name=table_name,
                version=version,
                created_at=current_datetime,  # Store as ISO format string
                updated_at=current_datetime,
            )
            # Update version if table_name already exists
            stmt = stmt.on_duplicate_key_update(
                version=version,
                updated_at=current_datetime,
            )
            sess.execute(stmt)

    # -- Session methods --
    def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """
        Delete a session from the database.

        Args:
            session_id (str): ID of the session to delete
            user_id (Optional[str]): User ID to filter by. Defaults to None.

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
                if user_id is not None:
                    delete_stmt = delete_stmt.where(table.c.user_id == user_id)
                result = sess.execute(delete_stmt)
                if result.rowcount == 0:
                    log_debug(f"No session found to delete with session_id: {session_id} in table {table.name}")
                    return False
                else:
                    log_debug(f"Successfully deleted session with session_id: {session_id} in table {table.name}")
                    return True

        except Exception as e:
            log_error(f"Error deleting session: {e}")
            raise e

    def delete_sessions(self, session_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete all given sessions from the database.
        Can handle multiple session types in the same run.

        Args:
            session_ids (List[str]): The IDs of the sessions to delete.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = self._get_table(table_type="sessions")
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                delete_stmt = table.delete().where(table.c.session_id.in_(session_ids))
                if user_id is not None:
                    delete_stmt = delete_stmt.where(table.c.user_id == user_id)
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
            session_type (Optional[SessionType]): The type of session to filter by.
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
            log_error(f"Exception reading from session table: {e}")
            raise e

    def rename_session(
        self,
        session_id: str,
        session_type: SessionType,
        session_name: str,
        user_id: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Optional[Union[Session, Dict[str, Any]]]:
        """
        Rename a session in the database.

        Args:
            session_id (str): The ID of the session to rename.
            session_type (SessionType): The type of session to rename.
            session_name (str): The new name for the session.
            user_id (Optional[str]): User ID to filter by. Defaults to None.
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
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)
                result = sess.execute(stmt)
                if result.rowcount == 0:
                    return None

                # Fetch the updated record
                select_stmt = select(table).where(table.c.session_id == session_id)
                if user_id is not None:
                    select_stmt = select_stmt.where(table.c.user_id == user_id)
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
            raise e

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
                    existing_row = sess.execute(
                        select(table.c.user_id)
                        .where(table.c.session_id == session_dict.get("session_id"))
                        .with_for_update()
                    ).fetchone()
                    if existing_row is not None:
                        existing_uid = existing_row[0]
                        if existing_uid is not None and existing_uid != session_dict.get("user_id"):
                            return None

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

                    if not deserialize:
                        return row._mapping

                    return AgentSession.from_dict(row._mapping)

            elif isinstance(session, TeamSession):
                with self.Session() as sess, sess.begin():
                    existing_row = sess.execute(
                        select(table.c.user_id)
                        .where(table.c.session_id == session_dict.get("session_id"))
                        .with_for_update()
                    ).fetchone()
                    if existing_row is not None:
                        existing_uid = existing_row[0]
                        if existing_uid is not None and existing_uid != session_dict.get("user_id"):
                            return None

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

                    if not deserialize:
                        return row._mapping

                    return TeamSession.from_dict(row._mapping)

            else:
                with self.Session() as sess, sess.begin():
                    existing_row = sess.execute(
                        select(table.c.user_id)
                        .where(table.c.session_id == session_dict.get("session_id"))
                        .with_for_update()
                    ).fetchone()
                    if existing_row is not None:
                        existing_uid = existing_row[0]
                        if existing_uid is not None and existing_uid != session_dict.get("user_id"):
                            return None

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

                    if not deserialize:
                        return row._mapping

                    return WorkflowSession.from_dict(row._mapping)

        except Exception as e:
            log_error(f"Error upserting into sessions table: {e}")
            raise e

    def upsert_sessions(
        self, sessions: List[Session], deserialize: Optional[bool] = True, preserve_updated_at: bool = False
    ) -> List[Union[Session, Dict[str, Any]]]:
        """
        Bulk upsert multiple sessions for improved performance on large datasets.

        Args:
            sessions (List[Session]): List of sessions to upsert.
            deserialize (Optional[bool]): Whether to deserialize the sessions. Defaults to True.

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
                return []

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
                        session_dict = session.to_dict()
                        # Use preserved updated_at if flag is set, otherwise use current time
                        updated_at = session_dict.get("updated_at") if preserve_updated_at else int(time.time())
                        agent_data.append(
                            {
                                "session_id": session_dict.get("session_id"),
                                "session_type": SessionType.AGENT.value,
                                "agent_id": session_dict.get("agent_id"),
                                "user_id": session_dict.get("user_id"),
                                "runs": session_dict.get("runs"),
                                "agent_data": session_dict.get("agent_data"),
                                "session_data": session_dict.get("session_data"),
                                "summary": session_dict.get("summary"),
                                "metadata": session_dict.get("metadata"),
                                "created_at": session_dict.get("created_at"),
                                "updated_at": updated_at,
                            }
                        )

                    if agent_data:
                        stmt = mysql.insert(table)
                        stmt = stmt.on_duplicate_key_update(
                            agent_id=stmt.inserted.agent_id,
                            user_id=stmt.inserted.user_id,
                            agent_data=stmt.inserted.agent_data,
                            session_data=stmt.inserted.session_data,
                            summary=stmt.inserted.summary,
                            metadata=stmt.inserted.metadata,
                            runs=stmt.inserted.runs,
                            updated_at=stmt.inserted.updated_at,
                        )
                        sess.execute(stmt, agent_data)

                        # Fetch the results for agent sessions
                        agent_ids = [session.session_id for session in agent_sessions]
                        select_stmt = select(table).where(table.c.session_id.in_(agent_ids))
                        result = sess.execute(select_stmt).fetchall()

                        for row in result:
                            if deserialize:
                                deserialized_session = AgentSession.from_dict(session_dict)
                                if deserialized_session is None:
                                    continue
                                results.append(deserialized_session)
                            else:
                                results.append(dict(row._mapping))

                # Bulk upsert team sessions
                if team_sessions:
                    team_data = []
                    for session in team_sessions:
                        session_dict = session.to_dict()
                        # Use preserved updated_at if flag is set, otherwise use current time
                        updated_at = session_dict.get("updated_at") if preserve_updated_at else int(time.time())
                        team_data.append(
                            {
                                "session_id": session_dict.get("session_id"),
                                "session_type": SessionType.TEAM.value,
                                "team_id": session_dict.get("team_id"),
                                "user_id": session_dict.get("user_id"),
                                "runs": session_dict.get("runs"),
                                "team_data": session_dict.get("team_data"),
                                "session_data": session_dict.get("session_data"),
                                "summary": session_dict.get("summary"),
                                "metadata": session_dict.get("metadata"),
                                "created_at": session_dict.get("created_at"),
                                "updated_at": updated_at,
                            }
                        )

                    if team_data:
                        stmt = mysql.insert(table)
                        stmt = stmt.on_duplicate_key_update(
                            team_id=stmt.inserted.team_id,
                            user_id=stmt.inserted.user_id,
                            team_data=stmt.inserted.team_data,
                            session_data=stmt.inserted.session_data,
                            summary=stmt.inserted.summary,
                            metadata=stmt.inserted.metadata,
                            runs=stmt.inserted.runs,
                            updated_at=stmt.inserted.updated_at,
                        )
                        sess.execute(stmt, team_data)

                        # Fetch the results for team sessions
                        team_ids = [session.session_id for session in team_sessions]
                        select_stmt = select(table).where(table.c.session_id.in_(team_ids))
                        result = sess.execute(select_stmt).fetchall()

                        for row in result:
                            if deserialize:
                                deserialized_team_session = TeamSession.from_dict(session_dict)
                                if deserialized_team_session is None:
                                    continue
                                results.append(deserialized_team_session)
                            else:
                                results.append(dict(row._mapping))

                # Bulk upsert workflow sessions
                if workflow_sessions:
                    workflow_data = []
                    for session in workflow_sessions:
                        session_dict = session.to_dict()
                        # Use preserved updated_at if flag is set, otherwise use current time
                        updated_at = session_dict.get("updated_at") if preserve_updated_at else int(time.time())
                        workflow_data.append(
                            {
                                "session_id": session_dict.get("session_id"),
                                "session_type": SessionType.WORKFLOW.value,
                                "workflow_id": session_dict.get("workflow_id"),
                                "user_id": session_dict.get("user_id"),
                                "runs": session_dict.get("runs"),
                                "workflow_data": session_dict.get("workflow_data"),
                                "session_data": session_dict.get("session_data"),
                                "summary": session_dict.get("summary"),
                                "metadata": session_dict.get("metadata"),
                                "created_at": session_dict.get("created_at"),
                                "updated_at": updated_at,
                            }
                        )

                    if workflow_data:
                        stmt = mysql.insert(table)
                        stmt = stmt.on_duplicate_key_update(
                            workflow_id=stmt.inserted.workflow_id,
                            user_id=stmt.inserted.user_id,
                            workflow_data=stmt.inserted.workflow_data,
                            session_data=stmt.inserted.session_data,
                            summary=stmt.inserted.summary,
                            metadata=stmt.inserted.metadata,
                            runs=stmt.inserted.runs,
                            updated_at=stmt.inserted.updated_at,
                        )
                        sess.execute(stmt, workflow_data)

                        # Fetch the results for workflow sessions
                        workflow_ids = [session.session_id for session in workflow_sessions]
                        select_stmt = select(table).where(table.c.session_id.in_(workflow_ids))
                        result = sess.execute(select_stmt).fetchall()

                        for row in result:
                            if deserialize:
                                deserialized_workflow_session = WorkflowSession.from_dict(session_dict)
                                if deserialized_workflow_session is None:
                                    continue
                                results.append(deserialized_workflow_session)
                            else:
                                results.append(dict(row._mapping))

            return results

        except Exception as e:
            log_error(f"Exception during bulk session upsert: {e}")
            return []

    # -- Memory methods --
    def delete_user_memory(self, memory_id: str, user_id: Optional[str] = None):
        """Delete a user memory from the database.

        Args:
            memory_id (str): The ID of the memory to delete.
            user_id (Optional[str]): The ID of the user to filter by. Defaults to None.

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
                    log_debug(f"Successfully deleted memory id: {memory_id}")
                else:
                    log_debug(f"No memory found with id: {memory_id}")

        except Exception as e:
            log_error(f"Error deleting memory: {e}")
            raise e

    def delete_user_memories(self, memory_ids: List[str], user_id: Optional[str] = None) -> None:
        """Delete user memories from the database.

        Args:
            memory_ids (List[str]): The IDs of the memories to delete.
            user_id (Optional[str]): The ID of the user to filter by. Defaults to None.

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
                    log_debug(f"No memories found with ids: {memory_ids}")

        except Exception as e:
            log_error(f"Error deleting memories: {e}")
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
            raise e

    def get_user_memory(
        self, memory_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[UserMemory]:
        """Get a memory from the database.

        Args:
            memory_id (str): The ID of the memory to get.
            deserialize (Optional[bool]): Whether to serialize the memory. Defaults to True.
            user_id (Optional[str]): The ID of the user to filter by. Defaults to None.

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
                if user_id is not None:
                    stmt = stmt.where(table.c.user_id == user_id)

                result = sess.execute(stmt).fetchone()
                if not result:
                    return None

                memory_raw = result._mapping
                if not deserialize:
                    return memory_raw
            return UserMemory.from_dict(memory_raw)

        except Exception as e:
            log_error(f"Exception reading from memory table: {e}")
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
            raise e

    def get_user_memory_stats(
        self, limit: Optional[int] = None, page: Optional[int] = None, user_id: Optional[str] = None
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

            with self.Session() as sess, sess.begin():
                if memory.memory_id is None:
                    memory.memory_id = str(uuid4())

                current_time = int(time.time())

                stmt = mysql.insert(table).values(
                    memory_id=memory.memory_id,
                    memory=memory.memory,
                    input=memory.input,
                    user_id=memory.user_id,
                    agent_id=memory.agent_id,
                    team_id=memory.team_id,
                    topics=memory.topics,
                    feedback=memory.feedback,
                    created_at=memory.created_at,
                    updated_at=current_time,
                )
                stmt = stmt.on_duplicate_key_update(
                    memory=stmt.inserted.memory,
                    topics=stmt.inserted.topics,
                    input=stmt.inserted.input,
                    user_id=stmt.inserted.user_id,
                    agent_id=stmt.inserted.agent_id,
                    team_id=stmt.inserted.team_id,
                    feedback=stmt.inserted.feedback,
                    updated_at=stmt.inserted.updated_at,
                    # Preserve created_at on update - don't overwrite existing value
                    created_at=table.c.created_at,
                )

                sess.execute(stmt)

                # Fetch the result
                select_stmt = select(table).where(table.c.memory_id == memory.memory_id)
                row = sess.execute(select_stmt).fetchone()
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
        self, memories: List[UserMemory], deserialize: Optional[bool] = True, preserve_updated_at: bool = False
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
                return []

            # Prepare data for bulk insert
            memory_data = []
            current_time = int(time.time())

            for memory in memories:
                if memory.memory_id is None:
                    memory.memory_id = str(uuid4())
                # Use preserved updated_at if flag is set, otherwise use current time
                updated_at = memory.updated_at if preserve_updated_at else current_time

                memory_data.append(
                    {
                        "memory_id": memory.memory_id,
                        "memory": memory.memory,
                        "input": memory.input,
                        "user_id": memory.user_id,
                        "agent_id": memory.agent_id,
                        "team_id": memory.team_id,
                        "topics": memory.topics,
                        "feedback": memory.feedback,
                        "created_at": memory.created_at,
                        "updated_at": updated_at,
                    }
                )

            results: List[Union[UserMemory, Dict[str, Any]]] = []

            with self.Session() as sess, sess.begin():
                if memory_data:
                    stmt = mysql.insert(table)
                    stmt = stmt.on_duplicate_key_update(
                        memory=stmt.inserted.memory,
                        topics=stmt.inserted.topics,
                        input=stmt.inserted.input,
                        user_id=stmt.inserted.user_id,
                        agent_id=stmt.inserted.agent_id,
                        team_id=stmt.inserted.team_id,
                        feedback=stmt.inserted.feedback,
                        updated_at=stmt.inserted.updated_at,
                        # Preserve created_at on update
                        created_at=table.c.created_at,
                    )
                    sess.execute(stmt, memory_data)

                    # Fetch the results
                    memory_ids = [memory.memory_id for memory in memories if memory.memory_id]
                    select_stmt = select(table).where(table.c.memory_id.in_(memory_ids))
                    result = sess.execute(select_stmt).fetchall()

                    for row in result:
                        memory_raw = dict(row._mapping)
                        if deserialize:
                            results.append(UserMemory.from_dict(memory_raw))
                        else:
                            results.append(memory_raw)

            return results

        except Exception as e:
            log_error(f"Exception during bulk memory upsert: {e}")
            return []

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
            log_error(f"Exception deleting all memories: {e}")
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
            log_error(f"Error calculating metrics: {e}")
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
            raise e

    # -- Knowledge methods --

    def delete_knowledge_content(self, id: str):
        """Delete a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to delete.
        """
        try:
            table = self._get_table(table_type="knowledge")
            if table is None:
                return

            with self.Session() as sess, sess.begin():
                stmt = table.delete().where(table.c.id == id)
                sess.execute(stmt)

            log_debug(f"Deleted knowledge content with id '{id}'")
        except Exception as e:
            log_error(f"Error deleting knowledge content: {e}")
            raise e

    def get_knowledge_content(self, id: str) -> Optional[KnowledgeRow]:
        """Get a knowledge row from the database.

        Args:
            id (str): The ID of the knowledge row to get.

        Returns:
            Optional[KnowledgeRow]: The knowledge row, or None if it doesn't exist.
        """
        try:
            table = self._get_table(table_type="knowledge")
            if table is None:
                return None

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
        linked_to: Optional[str] = None,
    ) -> Tuple[List[KnowledgeRow], int]:
        """Get all knowledge contents from the database.

        Args:
            limit (Optional[int]): The maximum number of knowledge contents to return.
            page (Optional[int]): The page number.
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by.
            linked_to (Optional[str]): Filter by linked_to value (knowledge instance name).

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

                # Apply linked_to filter if provided
                if linked_to is not None:
                    stmt = stmt.where(table.c.linked_to == linked_to)

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

            return knowledge_row

        except Exception as e:
            log_error(f"Error upserting knowledge row: {e}")
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
                stmt = mysql.insert(table).values(
                    {"created_at": current_time, "updated_at": current_time, **eval_run.model_dump()}
                )
                sess.execute(stmt)

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
                if not deserialize:
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
            raise e

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
            raise e

    # -- Culture methods --

    def clear_cultural_knowledge(self) -> None:
        """Delete all cultural knowledge from the database.

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
            log_warning(f"Exception deleting all cultural knowledge: {e}")
            raise e

    def delete_cultural_knowledge(self, id: str) -> None:
        """Delete a cultural knowledge entry from the database.

        Args:
            id (str): The ID of the cultural knowledge to delete.

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
                    log_debug(f"Successfully deleted cultural knowledge id: {id}")
                else:
                    log_debug(f"No cultural knowledge found with id: {id}")

        except Exception as e:
            log_error(f"Error deleting cultural knowledge: {e}")
            raise e

    def get_cultural_knowledge(
        self, id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[CulturalKnowledge, Dict[str, Any]]]:
        """Get a cultural knowledge entry from the database.

        Args:
            id (str): The ID of the cultural knowledge to get.
            deserialize (Optional[bool]): Whether to deserialize the cultural knowledge. Defaults to True.

        Returns:
            Optional[Union[CulturalKnowledge, Dict[str, Any]]]: The cultural knowledge entry, or None if it doesn't exist.

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
            log_error(f"Exception reading from cultural knowledge table: {e}")
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
        """Get all cultural knowledge from the database as CulturalKnowledge objects.

        Args:
            name (Optional[str]): The name of the cultural knowledge to filter by.
            agent_id (Optional[str]): The ID of the agent to filter by.
            team_id (Optional[str]): The ID of the team to filter by.
            limit (Optional[int]): The maximum number of cultural knowledge entries to return.
            page (Optional[int]): The page number.
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by.
            deserialize (Optional[bool]): Whether to deserialize the cultural knowledge. Defaults to True.

        Returns:
            Union[List[CulturalKnowledge], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of CulturalKnowledge objects
                - When deserialize=False: List of CulturalKnowledge dictionaries and total count

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
            log_error(f"Error reading from cultural knowledge table: {e}")
            raise e

    def upsert_cultural_knowledge(
        self, cultural_knowledge: CulturalKnowledge, deserialize: Optional[bool] = True
    ) -> Optional[Union[CulturalKnowledge, Dict[str, Any]]]:
        """Upsert a cultural knowledge entry into the database.

        Args:
            cultural_knowledge (CulturalKnowledge): The cultural knowledge to upsert.
            deserialize (Optional[bool]): Whether to deserialize the cultural knowledge. Defaults to True.

        Returns:
            Optional[CulturalKnowledge]: The upserted cultural knowledge entry.

        Raises:
            Exception: If an error occurs during upsert.
        """
        try:
            table = self._get_table(table_type="culture", create_table_if_not_found=True)
            if table is None:
                return None

            if cultural_knowledge.id is None:
                cultural_knowledge.id = str(uuid4())

            # Serialize content, categories, and notes into a JSON dict for DB storage
            content_dict = serialize_cultural_knowledge_for_db(cultural_knowledge)

            with self.Session() as sess, sess.begin():
                stmt = mysql.insert(table).values(
                    id=cultural_knowledge.id,
                    name=cultural_knowledge.name,
                    summary=cultural_knowledge.summary,
                    content=content_dict if content_dict else None,
                    metadata=cultural_knowledge.metadata,
                    input=cultural_knowledge.input,
                    created_at=cultural_knowledge.created_at,
                    updated_at=int(time.time()),
                    agent_id=cultural_knowledge.agent_id,
                    team_id=cultural_knowledge.team_id,
                )
                stmt = stmt.on_duplicate_key_update(
                    name=cultural_knowledge.name,
                    summary=cultural_knowledge.summary,
                    content=content_dict if content_dict else None,
                    metadata=cultural_knowledge.metadata,
                    input=cultural_knowledge.input,
                    updated_at=int(time.time()),
                    agent_id=cultural_knowledge.agent_id,
                    team_id=cultural_knowledge.team_id,
                )
                sess.execute(stmt)

            # Fetch the inserted/updated row
            return self.get_cultural_knowledge(id=cultural_knowledge.id, deserialize=deserialize)

        except Exception as e:
            log_error(f"Error upserting cultural knowledge: {e}")
            raise e

    # --- Traces ---
    def _get_traces_base_query(self, table: Table, spans_table: Optional[Table] = None):
        """Build base query for traces with aggregated span counts.

        Args:
            table: The traces table.
            spans_table: The spans table (optional).

        Returns:
            SQLAlchemy select statement with total_spans and error_count calculated dynamically.
        """
        from sqlalchemy import case, literal

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
        from sqlalchemy import case, or_

        is_root_name = or_(name_col.like("%.run%"), name_col.like("%.arun%"))

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

        Uses INSERT ... ON DUPLICATE KEY UPDATE (upsert) to handle concurrent inserts
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
                insert_stmt = mysql.insert(table).values(trace_dict)

                # Build component level expressions for comparing trace priority
                new_level = self._get_trace_component_level_expr(
                    insert_stmt.inserted.workflow_id,
                    insert_stmt.inserted.team_id,
                    insert_stmt.inserted.agent_id,
                    insert_stmt.inserted.name,
                )
                existing_level = self._get_trace_component_level_expr(
                    table.c.workflow_id,
                    table.c.team_id,
                    table.c.agent_id,
                    table.c.name,
                )

                # Build the ON DUPLICATE KEY UPDATE clause
                # Use LEAST for start_time, GREATEST for end_time to capture full trace duration
                # Duration is calculated using TIMESTAMPDIFF in microseconds then converted to ms
                upsert_stmt = insert_stmt.on_duplicate_key_update(
                    end_time=func.greatest(table.c.end_time, insert_stmt.inserted.end_time),
                    start_time=func.least(table.c.start_time, insert_stmt.inserted.start_time),
                    # Calculate duration in milliseconds using TIMESTAMPDIFF
                    # TIMESTAMPDIFF(MICROSECOND, start, end) / 1000 gives milliseconds
                    duration_ms=func.timestampdiff(
                        text("MICROSECOND"),
                        func.least(table.c.start_time, insert_stmt.inserted.start_time),
                        func.greatest(table.c.end_time, insert_stmt.inserted.end_time),
                    )
                    / 1000,
                    status=insert_stmt.inserted.status,
                    # Update name only if new trace is from a higher-level component
                    # Priority: workflow (3) > team (2) > agent (1) > child spans (0)
                    name=case(
                        (new_level > existing_level, insert_stmt.inserted.name),
                        else_=table.c.name,
                    ),
                    # Preserve existing non-null context values using COALESCE
                    run_id=func.coalesce(insert_stmt.inserted.run_id, table.c.run_id),
                    session_id=func.coalesce(insert_stmt.inserted.session_id, table.c.session_id),
                    user_id=func.coalesce(insert_stmt.inserted.user_id, table.c.user_id),
                    agent_id=func.coalesce(insert_stmt.inserted.agent_id, table.c.agent_id),
                    team_id=func.coalesce(insert_stmt.inserted.team_id, table.c.team_id),
                    workflow_id=func.coalesce(insert_stmt.inserted.workflow_id, table.c.workflow_id),
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
        """Get traces matching the provided filters.

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
            from agno.tracing.schemas import Trace

            log_debug(
                f"get_traces called with filters: run_id={run_id}, session_id={session_id}, user_id={user_id}, agent_id={agent_id}, page={page}, limit={limit}"
            )

            table = self._get_table(table_type="traces")
            if table is None:
                log_debug("Traces table not found")
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
                if user_id is not None:
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
                Each dict contains: session_id, user_id, agent_id, team_id, total_traces,
                first_trace_at, last_trace_at.
        """
        try:
            log_debug(
                f"get_trace_stats called with filters: user_id={user_id}, agent_id={agent_id}, "
                f"workflow_id={workflow_id}, team_id={team_id}, "
                f"start_time={start_time}, end_time={end_time}, page={page}, limit={limit}"
            )

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
                if user_id is not None:
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
                log_debug(f"Total matching sessions: {total_count}")

                # Apply pagination and ordering
                offset = (page - 1) * limit if page and limit else 0
                paginated_stmt = base_stmt.order_by(func.max(table.c.created_at).desc()).limit(limit).offset(offset)

                results = sess.execute(paginated_stmt).fetchall()
                log_debug(f"Returning page {page} with {len(results)} session stats")

                # Convert to list of dicts with datetime objects
                stats_list = []
                for row in results:
                    # Convert ISO strings to datetime objects
                    first_trace_at_str = row.first_trace_at
                    last_trace_at_str = row.last_trace_at

                    # Parse ISO format strings to datetime objects (handle None values)
                    first_trace_at = None
                    last_trace_at = None
                    if first_trace_at_str is not None:
                        first_trace_at = datetime.fromisoformat(first_trace_at_str.replace("Z", "+00:00"))
                    if last_trace_at_str is not None:
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

    # --- Spans ---
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
                stmt = mysql.insert(table).values(span.to_dict())
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
                    stmt = mysql.insert(table).values(span.to_dict())
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
                stmt = select(table).where(table.c.span_id == span_id)
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
        limit: Optional[int] = 1000,
    ) -> List:
        """Get spans matching the provided filters.

        Args:
            trace_id: Filter by trace ID.
            parent_span_id: Filter by parent span ID.
            limit: Maximum number of spans to return.

        Returns:
            List[Span]: List of matching spans.
        """
        try:
            from agno.tracing.schemas import Span

            table = self._get_table(table_type="spans")
            if table is None:
                return []

            with self.Session() as sess:
                stmt = select(table)

                # Apply filters
                if trace_id:
                    stmt = stmt.where(table.c.trace_id == trace_id)
                if parent_span_id:
                    stmt = stmt.where(table.c.parent_span_id == parent_span_id)

                if limit:
                    stmt = stmt.limit(limit)

                results = sess.execute(stmt).fetchall()
                return [Span.from_dict(dict(row._mapping)) for row in results]

        except Exception as e:
            log_error(f"Error getting spans: {e}")
            return []

    # -- Learning methods (stubs) --
    def get_learning(
        self,
        learning_type: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("Learning methods not yet implemented for SingleStoreDb")

    def upsert_learning(
        self,
        id: str,
        learning_type: str,
        content: Dict[str, Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        raise NotImplementedError("Learning methods not yet implemented for SingleStoreDb")

    def delete_learning(self, id: str) -> bool:
        raise NotImplementedError("Learning methods not yet implemented for SingleStoreDb")

    def get_learnings(
        self,
        learning_type: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError("Learning methods not yet implemented for SingleStoreDb")
