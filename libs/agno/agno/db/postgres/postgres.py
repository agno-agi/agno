import time
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple, Union, cast
from uuid import uuid4

if TYPE_CHECKING:
    from agno.tracing.schemas import Span, Trace

from agno.db.base import BaseDb, PrimitiveType, SessionType
from agno.db.migrations.manager import MigrationManager
from agno.db.postgres.schemas import get_table_schema_definition
from agno.db.postgres.utils import (
    apply_sorting,
    bulk_upsert_metrics,
    calculate_date_metrics,
    create_schema,
    deserialize_cultural_knowledge,
    fetch_all_sessions_data,
    get_dates_to_calculate_metrics_for,
    is_table_available,
    is_valid_table,
    serialize_cultural_knowledge,
)
from agno.db.schemas.culture import CulturalKnowledge
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.session import AgentSession, Session, TeamSession, WorkflowSession
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.string import generate_id, sanitize_postgres_string, sanitize_postgres_strings

try:
    from sqlalchemy import (
        ForeignKey,
        ForeignKeyConstraint,
        Index,
        PrimaryKeyConstraint,
        String,
        UniqueConstraint,
        and_,
        case,
        func,
        or_,
        select,
        update,
    )
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.dialects.postgresql import TIMESTAMP
    from sqlalchemy.engine import Engine, create_engine
    from sqlalchemy.exc import ProgrammingError
    from sqlalchemy.orm import scoped_session, sessionmaker
    from sqlalchemy.schema import Column, MetaData, Table
    from sqlalchemy.sql.expression import text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


class PostgresDb(BaseDb):
    def __init__(
        self,
        db_url: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        db_schema: Optional[str] = None,
        session_table: Optional[str] = None,
        culture_table: Optional[str] = None,
        memory_table: Optional[str] = None,
        metrics_table: Optional[str] = None,
        eval_table: Optional[str] = None,
        knowledge_table: Optional[str] = None,
        traces_table: Optional[str] = None,
        spans_table: Optional[str] = None,
        versions_table: Optional[str] = None,
        entity_table: Optional[str] = None,
        config_table: Optional[str] = None,
        entity_ref_table: Optional[str] = None,
        id: Optional[str] = None,
        create_schema: bool = True,
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
            memory_table (Optional[str]): Name of the table to store memories.
            metrics_table (Optional[str]): Name of the table to store metrics.
            eval_table (Optional[str]): Name of the table to store evaluation runs data.
            knowledge_table (Optional[str]): Name of the table to store knowledge content.
            culture_table (Optional[str]): Name of the table to store cultural knowledge.
            traces_table (Optional[str]): Name of the table to store run traces.
            spans_table (Optional[str]): Name of the table to store span events.
            versions_table (Optional[str]): Name of the table to store schema versions.
            entity_table (Optional[str]): Name of the table to store entities.
            config_table (Optional[str]): Name of the table to store configurations.
            entity_ref_table (Optional[str]): Name of the table to store entity references.
            id (Optional[str]): ID of the database.
            create_schema (bool): Whether to automatically create the database schema if it doesn't exist.
                Set to False if schema is managed externally (e.g., via migrations). Defaults to True.

        Raises:
            ValueError: If neither db_url nor db_engine is provided.
            ValueError: If none of the tables are provided.
        """
        _engine: Optional[Engine] = db_engine
        if _engine is None and db_url is not None:
            _engine = create_engine(
                db_url,
                pool_pre_ping=True,
                pool_recycle=3600,
            )
        if _engine is None:
            raise ValueError("One of db_url or db_engine must be provided")

        self.db_url: Optional[str] = db_url
        self.db_engine: Engine = _engine

        if id is None:
            base_seed = db_url or str(db_engine.url)  # type: ignore
            schema_suffix = db_schema if db_schema is not None else "ai"
            seed = f"{base_seed}#{schema_suffix}"
            id = generate_id(seed)

        super().__init__(
            id=id,
            session_table=session_table,
            memory_table=memory_table,
            metrics_table=metrics_table,
            eval_table=eval_table,
            knowledge_table=knowledge_table,
            culture_table=culture_table,
            traces_table=traces_table,
            spans_table=spans_table,
            versions_table=versions_table,
            entity_table=entity_table,
            config_table=config_table,
            entity_ref_table=entity_ref_table,
        )

        self.db_schema: str = db_schema if db_schema is not None else "ai"
        self.metadata: MetaData = MetaData(schema=self.db_schema)
        self.create_schema: bool = create_schema

        # Initialize database session
        self.Session: scoped_session = scoped_session(sessionmaker(bind=self.db_engine, expire_on_commit=False))

    # -- Serialization methods --
    def to_dict(self):
        base = super().to_dict()
        base.update(
            {
                "db_url": self.db_url,
                "db_schema": self.db_schema,
                "type": "postgres",
            }
        )
        return base

    @classmethod
    def from_dict(cls, data):
        return cls(
            db_url=data.get("db_url"),
            db_schema=data.get("db_schema"),
            session_table=data.get("session_table"),
            culture_table=data.get("culture_table"),
            memory_table=data.get("memory_table"),
            metrics_table=data.get("metrics_table"),
            eval_table=data.get("eval_table"),
            knowledge_table=data.get("knowledge_table"),
            traces_table=data.get("traces_table"),
            spans_table=data.get("spans_table"),
            versions_table=data.get("versions_table"),
            entity_table=data.get("entity_table"),
            config_table=data.get("config_table"),
            entity_ref_table=data.get("entity_ref_table"),
            id=data.get("id"),
        )

    def close(self) -> None:
        """Close database connections and dispose of the connection pool.

        Should be called during application shutdown to properly release
        all database connections.
        """
        if self.db_engine is not None:
            self.db_engine.dispose()

    # -- DB methods --
    def table_exists(self, table_name: str) -> bool:
        """Check if a table with the given name exists in the Postgres database.

        Args:
            table_name: Name of the table to check

        Returns:
            bool: True if the table exists in the database, False otherwise
        """
        with self.Session() as sess:
            return is_table_available(session=sess, table_name=table_name, db_schema=self.db_schema)

    def _create_all_tables(self):
        """Create all tables for the database."""
        tables_to_create = [
            (self.session_table_name, "sessions"),
            (self.memory_table_name, "memories"),
            (self.metrics_table_name, "metrics"),
            (self.eval_table_name, "evals"),
            (self.knowledge_table_name, "knowledge"),
            (self.versions_table_name, "versions"),
            (self.entity_table_name, "entities"),
            (self.config_table_name, "configs"),
            (self.entity_ref_table_name, "entity_refs"),
        ]

        for table_name, table_type in tables_to_create:
            self._get_or_create_table(table_name=table_name, table_type=table_type, create_table_if_not_found=True)

    def _create_table(self, table_name: str, table_type: str) -> Table:
        """
        Create a table with the appropriate schema based on the table type.

        Supports:
        - _unique_constraints: [{"name": "...", "columns": [...]}]
        - __primary_key__: ["col1", "col2", ...]
        - __foreign_keys__: [{"columns":[...], "ref_table":"...", "ref_columns":[...]}]
        - column-level foreign_key: "logical_table.column" (resolved via _resolve_* helpers)
        """
        try:
            # Pass traces_table_name and db_schema for spans table foreign key resolution
            table_schema = get_table_schema_definition(
                table_type, traces_table_name=self.trace_table_name, db_schema=self.db_schema
            ).copy()

            columns: List[Column] = []
            indexes: List[str] = []

            # Extract special schema keys before iterating columns
            schema_unique_constraints = table_schema.pop("_unique_constraints", [])
            schema_primary_key = table_schema.pop("__primary_key__", None)
            schema_foreign_keys = table_schema.pop("__foreign_keys__", [])

            # Build columns
            for col_name, col_config in table_schema.items():
                column_args = [col_name, col_config["type"]()]
                column_kwargs = {}

                # Column-level PK only if no composite PK is defined
                if col_config.get("primary_key", False) and schema_primary_key is None:
                    column_kwargs["primary_key"] = True

                if "nullable" in col_config:
                    column_kwargs["nullable"] = col_config["nullable"]

                if "default" in col_config:
                    column_kwargs["default"] = col_config["default"]

                if col_config.get("index", False):
                    indexes.append(col_name)

                if col_config.get("unique", False):
                    column_kwargs["unique"] = True

                # Single-column FK
                if "foreign_key" in col_config:
                    fk_ref = self._resolve_fk_reference(col_config["foreign_key"])
                    column_args.append(ForeignKey(fk_ref))

                columns.append(Column(*column_args, **column_kwargs))

            # Create the table object
            table = Table(table_name, self.metadata, *columns, schema=self.db_schema)

            # Composite PK
            if schema_primary_key is not None:
                missing = [c for c in schema_primary_key if c not in table.c]
                if missing:
                    raise ValueError(f"Composite PK references missing columns in {table_name}: {missing}")

                pk_constraint_name = f"{table_name}_pkey"
                table.append_constraint(PrimaryKeyConstraint(*schema_primary_key, name=pk_constraint_name))

            # Composite FKs
            for fk_config in schema_foreign_keys:
                fk_columns = fk_config["columns"]
                ref_table_logical = fk_config["ref_table"]
                ref_columns = fk_config["ref_columns"]

                if len(fk_columns) != len(ref_columns):
                    raise ValueError(
                        f"Composite FK in {table_name} has mismatched columns/ref_columns: {fk_columns} vs {ref_columns}"
                    )

                missing = [c for c in fk_columns if c not in table.c]
                if missing:
                    raise ValueError(f"Composite FK references missing columns in {table_name}: {missing}")

                resolved_ref_table = self._resolve_table_name(ref_table_logical)
                fk_constraint_name = f"{table_name}_{'_'.join(fk_columns)}_fkey"

                # IMPORTANT: since Table(schema=self.db_schema) is used, do NOT schema-qualify these targets.
                ref_column_strings = [f"{resolved_ref_table}.{col}" for col in ref_columns]

                table.append_constraint(
                    ForeignKeyConstraint(
                        fk_columns,
                        ref_column_strings,
                        name=fk_constraint_name,
                    )
                )

            # Multi-column unique constraints
            for constraint in schema_unique_constraints:
                constraint_name = f"{table_name}_{constraint['name']}"
                constraint_columns = constraint["columns"]

                missing = [c for c in constraint_columns if c not in table.c]
                if missing:
                    raise ValueError(f"Unique constraint references missing columns in {table_name}: {missing}")

                table.append_constraint(UniqueConstraint(*constraint_columns, name=constraint_name))

            # Indexes
            for idx_col in indexes:
                if idx_col not in table.c:
                    raise ValueError(f"Index references missing column in {table_name}: {idx_col}")
                idx_name = f"idx_{table_name}_{idx_col}"
                Index(idx_name, table.c[idx_col])  # Correct way; do NOT append as constraint

            # Create schema if requested
            if self.create_schema:
                with self.Session() as sess, sess.begin():
                    create_schema(session=sess, db_schema=self.db_schema)

            # Create table
            table_created = False
            if not self.table_exists(table_name):
                table.create(self.db_engine, checkfirst=True)
                log_debug(f"Successfully created table '{self.db_schema}.{table_name}'")
                table_created = True
            else:
                log_debug(f"Table {self.db_schema}.{table_name} already exists, skipping creation")

            # Create indexes (Postgres)
            for idx in table.indexes:
                try:
                    with self.Session() as sess:
                        exists_query = text(
                            "SELECT 1 FROM pg_indexes WHERE schemaname = :schema AND indexname = :index_name"
                        )
                        exists = (
                            sess.execute(exists_query, {"schema": self.db_schema, "index_name": idx.name}).scalar()
                            is not None
                        )
                        if exists:
                            log_debug(
                                f"Index {idx.name} already exists in {self.db_schema}.{table_name}, skipping creation"
                            )
                            continue

                    idx.create(self.db_engine)
                    log_debug(f"Created index: {idx.name} for table {self.db_schema}.{table_name}")

                except Exception as e:
                    log_error(f"Error creating index {idx.name}: {e}")

            # Store the schema version for the created table
            if table_name != self.versions_table_name and table_created:
                latest_schema_version = MigrationManager(self).latest_schema_version
                self.upsert_schema_version(table_name=table_name, version=latest_schema_version.public)

            return table

        except Exception as e:
            log_error(f"Could not create table {self.db_schema}.{table_name}: {e}")
            raise

    def _resolve_fk_reference(self, fk_ref: str) -> str:
        """
        Resolve a simple foreign key reference to fully qualified name.

        Accepts:
        - "logical_table.column"  -> "{schema}.{resolved_table}.{column}"
        - already-qualified refs  -> returned as-is
        """
        parts = fk_ref.split(".")
        if len(parts) == 2:
            table, column = parts
            resolved_table = self._resolve_table_name(table)
            return f"{self.db_schema}.{resolved_table}.{column}"
        return fk_ref

    def _resolve_table_name(self, logical_name: str) -> str:
        """
        Resolve logical table name to configured table name.
        """
        table_map = {
            "entities": self.entity_table_name,
            "configs": self.config_table_name,
            "entity_refs": self.entity_ref_table_name,
            "traces": self.trace_table_name,
            "spans": self.span_table_name,
            "sessions": self.session_table_name,
            "memories": self.memory_table_name,
            "metrics": self.metrics_table_name,
            "evals": self.eval_table_name,
            "knowledge": self.knowledge_table_name,
            "versions": self.versions_table_name,
        }
        return table_map.get(logical_name, logical_name)

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
            # Ensure traces table exists first (spans has FK to traces)
            if create_table_if_not_found:
                self._get_table(table_type="traces", create_table_if_not_found=True)

            self.spans_table = self._get_or_create_table(
                table_name=self.span_table_name,
                table_type="spans",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.spans_table

        if table_type == "entities":
            self.entity_table = self._get_or_create_table(
                table_name=self.entity_table_name,
                table_type="entities",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.entity_table

        if table_type == "configs":
            self.config_table = self._get_or_create_table(
                table_name=self.config_table_name,
                table_type="configs",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.config_table

        if table_type == "entity_refs":
            self.entity_ref_table = self._get_or_create_table(
                table_name=self.entity_ref_table_name,
                table_type="entity_refs",
                create_table_if_not_found=create_table_if_not_found,
            )
            return self.entity_ref_table

        raise ValueError(f"Unknown table type: {table_type}")

    def _get_or_create_table(
        self, table_name: str, table_type: str, create_table_if_not_found: Optional[bool] = False
    ) -> Optional[Table]:
        """
        Check if the table exists and is valid, else create it.

        Args:
            table_name (str): Name of the table to get or create
            table_type (str): Type of table (used to get schema definition)

        Returns:
            Optional[Table]: SQLAlchemy Table object representing the schema.
        """

        with self.Session() as sess, sess.begin():
            table_is_available = is_table_available(session=sess, table_name=table_name, db_schema=self.db_schema)

        if not table_is_available:
            if not create_table_if_not_found:
                return None
            return self._create_table(table_name=table_name, table_type=table_type)

        if not is_valid_table(
            db_engine=self.db_engine,
            table_name=table_name,
            table_type=table_type,
            db_schema=self.db_schema,
        ):
            raise ValueError(f"Table {self.db_schema}.{table_name} has an invalid schema")

        try:
            table = Table(table_name, self.metadata, schema=self.db_schema, autoload_with=self.db_engine)
            return table

        except Exception as e:
            log_error(f"Error loading existing table {self.db_schema}.{table_name}: {e}")
            raise

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
            stmt = postgresql.insert(table).values(
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

                # Filter by session_type to ensure we get the correct session type
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
                    stmt = stmt.where(
                        func.coalesce(table.c.session_data["session_name"].astext, "").ilike(f"%{session_name}%")
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
                # Sanitize session_name to remove null bytes
                sanitized_session_name = sanitize_postgres_string(session_name)
                stmt = (
                    update(table)
                    .where(table.c.session_id == session_id)
                    .where(table.c.session_type == session_type.value)
                    .values(
                        session_data=func.cast(
                            func.jsonb_set(
                                func.cast(table.c.session_data, postgresql.JSONB),
                                text("'{session_name}'"),
                                func.to_jsonb(sanitized_session_name),
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

            log_debug(f"Renamed session with id '{session_id}' to '{session_name}'")

            session = dict(row._mapping)
            if not deserialize:
                return session

            # Return the appropriate session type
            if session_type == SessionType.AGENT:
                return AgentSession.from_dict(session)
            elif session_type == SessionType.TEAM:
                return TeamSession.from_dict(session)
            elif session_type == SessionType.WORKFLOW:
                return WorkflowSession.from_dict(session)
            else:
                raise ValueError(f"Invalid session type: {session_type}")

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
            # Sanitize JSON/dict fields to remove null bytes from nested strings
            if session_dict.get("agent_data"):
                session_dict["agent_data"] = sanitize_postgres_strings(session_dict["agent_data"])
            if session_dict.get("team_data"):
                session_dict["team_data"] = sanitize_postgres_strings(session_dict["team_data"])
            if session_dict.get("workflow_data"):
                session_dict["workflow_data"] = sanitize_postgres_strings(session_dict["workflow_data"])
            if session_dict.get("session_data"):
                session_dict["session_data"] = sanitize_postgres_strings(session_dict["session_data"])
            if session_dict.get("summary"):
                session_dict["summary"] = sanitize_postgres_strings(session_dict["summary"])
            if session_dict.get("metadata"):
                session_dict["metadata"] = sanitize_postgres_strings(session_dict["metadata"])
            if session_dict.get("runs"):
                session_dict["runs"] = sanitize_postgres_strings(session_dict["runs"])

            if isinstance(session, AgentSession):
                with self.Session() as sess, sess.begin():
                    stmt = postgresql.insert(table).values(
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
                    stmt = stmt.on_conflict_do_update(  # type: ignore
                        index_elements=["session_id"],
                        set_=dict(
                            agent_id=session_dict.get("agent_id"),
                            user_id=session_dict.get("user_id"),
                            agent_data=session_dict.get("agent_data"),
                            session_data=session_dict.get("session_data"),
                            summary=session_dict.get("summary"),
                            metadata=session_dict.get("metadata"),
                            runs=session_dict.get("runs"),
                            updated_at=int(time.time()),
                        ),
                    ).returning(table)
                    result = sess.execute(stmt)
                    row = result.fetchone()
                    session_dict = dict(row._mapping)

                    if session_dict is None or not deserialize:
                        return session_dict
                    return AgentSession.from_dict(session_dict)

            elif isinstance(session, TeamSession):
                with self.Session() as sess, sess.begin():
                    stmt = postgresql.insert(table).values(
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
                    stmt = stmt.on_conflict_do_update(  # type: ignore
                        index_elements=["session_id"],
                        set_=dict(
                            team_id=session_dict.get("team_id"),
                            user_id=session_dict.get("user_id"),
                            team_data=session_dict.get("team_data"),
                            session_data=session_dict.get("session_data"),
                            summary=session_dict.get("summary"),
                            metadata=session_dict.get("metadata"),
                            runs=session_dict.get("runs"),
                            updated_at=int(time.time()),
                        ),
                    ).returning(table)
                    result = sess.execute(stmt)
                    row = result.fetchone()
                    session_dict = dict(row._mapping)

                    if session_dict is None or not deserialize:
                        return session_dict
                    return TeamSession.from_dict(session_dict)

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
                        metadata=session_dict.get("metadata"),
                        created_at=session_dict.get("created_at"),
                        updated_at=session_dict.get("created_at"),
                    )
                    stmt = stmt.on_conflict_do_update(  # type: ignore
                        index_elements=["session_id"],
                        set_=dict(
                            workflow_id=session_dict.get("workflow_id"),
                            user_id=session_dict.get("user_id"),
                            workflow_data=session_dict.get("workflow_data"),
                            session_data=session_dict.get("session_data"),
                            summary=session_dict.get("summary"),
                            metadata=session_dict.get("metadata"),
                            runs=session_dict.get("runs"),
                            updated_at=int(time.time()),
                        ),
                    ).returning(table)
                    result = sess.execute(stmt)
                    row = result.fetchone()
                    session_dict = dict(row._mapping)

                    if session_dict is None or not deserialize:
                        return session_dict
                    return WorkflowSession.from_dict(session_dict)

            else:
                raise ValueError(f"Invalid session type: {session.session_type}")

        except Exception as e:
            log_error(f"Exception upserting into sessions table: {e}")
            raise e

    def upsert_sessions(
        self, sessions: List[Session], deserialize: Optional[bool] = True, preserve_updated_at: bool = False
    ) -> List[Union[Session, Dict[str, Any]]]:
        """
        Bulk insert or update multiple sessions.

        Args:
            sessions (List[Session]): The list of session data to upsert.
            deserialize (Optional[bool]): Whether to deserialize the sessions. Defaults to True.
            preserve_updated_at (bool): If True, preserve the updated_at from the session object.

        Returns:
            List[Union[Session, Dict[str, Any]]]: List of upserted sessions

        Raises:
            Exception: If an error occurs during bulk upsert.
        """
        try:
            if not sessions:
                return []

            table = self._get_table(table_type="sessions", create_table_if_not_found=True)
            if table is None:
                return []

            # Group sessions by type for better handling
            agent_sessions = [s for s in sessions if isinstance(s, AgentSession)]
            team_sessions = [s for s in sessions if isinstance(s, TeamSession)]
            workflow_sessions = [s for s in sessions if isinstance(s, WorkflowSession)]

            results: List[Union[Session, Dict[str, Any]]] = []

            # Bulk upsert agent sessions
            if agent_sessions:
                session_records = []
                for agent_session in agent_sessions:
                    session_dict = agent_session.to_dict()
                    # Sanitize JSON/dict fields to remove null bytes from nested strings
                    if session_dict.get("agent_data"):
                        session_dict["agent_data"] = sanitize_postgres_strings(session_dict["agent_data"])
                    if session_dict.get("session_data"):
                        session_dict["session_data"] = sanitize_postgres_strings(session_dict["session_data"])
                    if session_dict.get("summary"):
                        session_dict["summary"] = sanitize_postgres_strings(session_dict["summary"])
                    if session_dict.get("metadata"):
                        session_dict["metadata"] = sanitize_postgres_strings(session_dict["metadata"])
                    if session_dict.get("runs"):
                        session_dict["runs"] = sanitize_postgres_strings(session_dict["runs"])

                    # Use preserved updated_at if flag is set (even if None), otherwise use current time
                    updated_at = session_dict.get("updated_at") if preserve_updated_at else int(time.time())
                    session_records.append(
                        {
                            "session_id": session_dict.get("session_id"),
                            "session_type": SessionType.AGENT.value,
                            "agent_id": session_dict.get("agent_id"),
                            "user_id": session_dict.get("user_id"),
                            "agent_data": session_dict.get("agent_data"),
                            "session_data": session_dict.get("session_data"),
                            "summary": session_dict.get("summary"),
                            "metadata": session_dict.get("metadata"),
                            "runs": session_dict.get("runs"),
                            "created_at": session_dict.get("created_at"),
                            "updated_at": updated_at,
                        }
                    )

                with self.Session() as sess, sess.begin():
                    stmt: Any = postgresql.insert(table)
                    update_columns = {
                        col.name: stmt.excluded[col.name]
                        for col in table.columns
                        if col.name not in ["id", "session_id", "created_at"]
                    }
                    stmt = stmt.on_conflict_do_update(index_elements=["session_id"], set_=update_columns).returning(
                        table
                    )

                    result = sess.execute(stmt, session_records)
                    for row in result.fetchall():
                        session_dict = dict(row._mapping)
                        if deserialize:
                            deserialized_agent_session = AgentSession.from_dict(session_dict)
                            if deserialized_agent_session is None:
                                continue
                            results.append(deserialized_agent_session)
                        else:
                            results.append(session_dict)

            # Bulk upsert team sessions
            if team_sessions:
                session_records = []
                for team_session in team_sessions:
                    session_dict = team_session.to_dict()
                    # Sanitize JSON/dict fields to remove null bytes from nested strings
                    if session_dict.get("team_data"):
                        session_dict["team_data"] = sanitize_postgres_strings(session_dict["team_data"])
                    if session_dict.get("session_data"):
                        session_dict["session_data"] = sanitize_postgres_strings(session_dict["session_data"])
                    if session_dict.get("summary"):
                        session_dict["summary"] = sanitize_postgres_strings(session_dict["summary"])
                    if session_dict.get("metadata"):
                        session_dict["metadata"] = sanitize_postgres_strings(session_dict["metadata"])
                    if session_dict.get("runs"):
                        session_dict["runs"] = sanitize_postgres_strings(session_dict["runs"])

                    # Use preserved updated_at if flag is set (even if None), otherwise use current time
                    updated_at = session_dict.get("updated_at") if preserve_updated_at else int(time.time())
                    session_records.append(
                        {
                            "session_id": session_dict.get("session_id"),
                            "session_type": SessionType.TEAM.value,
                            "team_id": session_dict.get("team_id"),
                            "user_id": session_dict.get("user_id"),
                            "team_data": session_dict.get("team_data"),
                            "session_data": session_dict.get("session_data"),
                            "summary": session_dict.get("summary"),
                            "metadata": session_dict.get("metadata"),
                            "runs": session_dict.get("runs"),
                            "created_at": session_dict.get("created_at"),
                            "updated_at": updated_at,
                        }
                    )

                with self.Session() as sess, sess.begin():
                    stmt = postgresql.insert(table)
                    update_columns = {
                        col.name: stmt.excluded[col.name]
                        for col in table.columns
                        if col.name not in ["id", "session_id", "created_at"]
                    }
                    stmt = stmt.on_conflict_do_update(index_elements=["session_id"], set_=update_columns).returning(
                        table
                    )

                    result = sess.execute(stmt, session_records)
                    for row in result.fetchall():
                        session_dict = dict(row._mapping)
                        if deserialize:
                            deserialized_team_session = TeamSession.from_dict(session_dict)
                            if deserialized_team_session is None:
                                continue
                            results.append(deserialized_team_session)
                        else:
                            results.append(session_dict)

            # Bulk upsert workflow sessions
            if workflow_sessions:
                session_records = []
                for workflow_session in workflow_sessions:
                    session_dict = workflow_session.to_dict()
                    # Sanitize JSON/dict fields to remove null bytes from nested strings
                    if session_dict.get("workflow_data"):
                        session_dict["workflow_data"] = sanitize_postgres_strings(session_dict["workflow_data"])
                    if session_dict.get("session_data"):
                        session_dict["session_data"] = sanitize_postgres_strings(session_dict["session_data"])
                    if session_dict.get("summary"):
                        session_dict["summary"] = sanitize_postgres_strings(session_dict["summary"])
                    if session_dict.get("metadata"):
                        session_dict["metadata"] = sanitize_postgres_strings(session_dict["metadata"])
                    if session_dict.get("runs"):
                        session_dict["runs"] = sanitize_postgres_strings(session_dict["runs"])

                    # Use preserved updated_at if flag is set (even if None), otherwise use current time
                    updated_at = session_dict.get("updated_at") if preserve_updated_at else int(time.time())
                    session_records.append(
                        {
                            "session_id": session_dict.get("session_id"),
                            "session_type": SessionType.WORKFLOW.value,
                            "workflow_id": session_dict.get("workflow_id"),
                            "user_id": session_dict.get("user_id"),
                            "workflow_data": session_dict.get("workflow_data"),
                            "session_data": session_dict.get("session_data"),
                            "summary": session_dict.get("summary"),
                            "metadata": session_dict.get("metadata"),
                            "runs": session_dict.get("runs"),
                            "created_at": session_dict.get("created_at"),
                            "updated_at": updated_at,
                        }
                    )

                with self.Session() as sess, sess.begin():
                    stmt = postgresql.insert(table)
                    update_columns = {
                        col.name: stmt.excluded[col.name]
                        for col in table.columns
                        if col.name not in ["id", "session_id", "created_at"]
                    }
                    stmt = stmt.on_conflict_do_update(index_elements=["session_id"], set_=update_columns).returning(
                        table
                    )

                    result = sess.execute(stmt, session_records)
                    for row in result.fetchall():
                        session_dict = dict(row._mapping)
                        if deserialize:
                            deserialized_workflow_session = WorkflowSession.from_dict(session_dict)
                            if deserialized_workflow_session is None:
                                continue
                            results.append(deserialized_workflow_session)
                        else:
                            results.append(session_dict)

            return results

        except Exception as e:
            log_error(f"Exception bulk upserting sessions: {e}")
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
                    log_debug(f"No user memories found with ids: {memory_ids}")
                else:
                    log_debug(f"Successfully deleted {result.rowcount} user memories")

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
                # Filter out NULL topics and ensure topics is an array before extracting elements
                # jsonb_typeof returns 'array' for JSONB arrays
                conditions = [
                    table.c.topics.is_not(None),
                    func.jsonb_typeof(table.c.topics) == "array",
                ]

                try:
                    # jsonb_array_elements_text is a set-returning function that must be used with select_from
                    stmt = select(func.jsonb_array_elements_text(table.c.topics).label("topic"))
                    stmt = stmt.select_from(table)
                    stmt = stmt.where(and_(*conditions))
                    result = sess.execute(stmt).fetchall()
                except ProgrammingError:
                    # Retrying with json_array_elements_text. This works in older versions,
                    # where the topics column was of type JSON instead of JSONB
                    # For JSON (not JSONB), we use json_typeof
                    json_conditions = [
                        table.c.topics.is_not(None),
                        func.json_typeof(table.c.topics) == "array",
                    ]
                    stmt = select(func.json_array_elements_text(table.c.topics).label("topic"))
                    stmt = stmt.select_from(table)
                    stmt = stmt.where(and_(*json_conditions))
                    result = sess.execute(stmt).fetchall()

                # Extract topics from records - each record is a Row with a 'topic' attribute
                topics = [record.topic for record in result if record.topic is not None]
                return list(set(topics))

        except Exception as e:
            log_error(f"Exception reading from memory table: {e}")
            return []

    def get_user_memory(
        self, memory_id: str, deserialize: Optional[bool] = True, user_id: Optional[str] = None
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
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

                memory_raw = dict(result._mapping)
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
                    for topic in topics:
                        stmt = stmt.where(func.cast(table.c.topics, String).like(f'%"{topic}"%'))
                if search_content is not None:
                    stmt = stmt.where(func.cast(table.c.memory, postgresql.TEXT).ilike(f"%{search_content}%"))

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

            # Sanitize string fields to remove null bytes (PostgreSQL doesn't allow them)
            sanitized_input = sanitize_postgres_string(memory.input)
            sanitized_feedback = sanitize_postgres_string(memory.feedback)

            with self.Session() as sess, sess.begin():
                if memory.memory_id is None:
                    memory.memory_id = str(uuid4())

                current_time = int(time.time())

                stmt = postgresql.insert(table).values(
                    memory_id=memory.memory_id,
                    memory=memory.memory,
                    input=sanitized_input,
                    user_id=memory.user_id,
                    agent_id=memory.agent_id,
                    team_id=memory.team_id,
                    topics=memory.topics,
                    feedback=sanitized_feedback,
                    created_at=memory.created_at,
                    updated_at=memory.updated_at
                    if memory.updated_at is not None
                    else (memory.created_at if memory.created_at is not None else current_time),
                )
                stmt = stmt.on_conflict_do_update(  # type: ignore
                    index_elements=["memory_id"],
                    set_=dict(
                        memory=memory.memory,
                        topics=memory.topics,
                        input=sanitized_input,
                        agent_id=memory.agent_id,
                        team_id=memory.team_id,
                        feedback=sanitized_feedback,
                        updated_at=current_time,
                        # Preserve created_at on update - don't overwrite existing value
                        created_at=table.c.created_at,
                    ),
                ).returning(table)

                result = sess.execute(stmt)
                row = result.fetchone()

            memory_raw = dict(row._mapping)

            if not memory_raw or not deserialize:
                return memory_raw

            return UserMemory.from_dict(memory_raw)

        except Exception as e:
            log_error(f"Exception upserting user memory: {e}")
            raise e

    def upsert_memories(
        self, memories: List[UserMemory], deserialize: Optional[bool] = True, preserve_updated_at: bool = False
    ) -> List[Union[UserMemory, Dict[str, Any]]]:
        """
        Bulk insert or update multiple memories in the database for improved performance.

        Args:
            memories (List[UserMemory]): The list of memories to upsert.
            deserialize (Optional[bool]): Whether to deserialize the memories. Defaults to True.
            preserve_updated_at (bool): If True, preserve the updated_at from the memory object.
                                       If False (default), set updated_at to current time.

        Returns:
            List[Union[UserMemory, Dict[str, Any]]]: List of upserted memories

        Raises:
            Exception: If an error occurs during bulk upsert.
        """
        try:
            if not memories:
                return []

            table = self._get_table(table_type="memories", create_table_if_not_found=True)
            if table is None:
                return []

            # Prepare memory records for bulk insert
            memory_records = []
            current_time = int(time.time())

            for memory in memories:
                if memory.memory_id is None:
                    memory.memory_id = str(uuid4())

                # Use preserved updated_at if flag is set (even if None), otherwise use current time
                updated_at = memory.updated_at if preserve_updated_at else current_time

                # Sanitize string fields to remove null bytes (PostgreSQL doesn't allow them)
                sanitized_input = sanitize_postgres_string(memory.input)
                sanitized_feedback = sanitize_postgres_string(memory.feedback)

                memory_records.append(
                    {
                        "memory_id": memory.memory_id,
                        "memory": memory.memory,
                        "input": sanitized_input,
                        "user_id": memory.user_id,
                        "agent_id": memory.agent_id,
                        "team_id": memory.team_id,
                        "topics": memory.topics,
                        "feedback": sanitized_feedback,
                        "created_at": memory.created_at,
                        "updated_at": updated_at,
                    }
                )

            results: List[Union[UserMemory, Dict[str, Any]]] = []

            with self.Session() as sess, sess.begin():
                insert_stmt = postgresql.insert(table)
                update_columns = {
                    col.name: insert_stmt.excluded[col.name]
                    for col in table.columns
                    if col.name not in ["memory_id", "created_at"]  # Don't update primary key or created_at
                }
                stmt = insert_stmt.on_conflict_do_update(index_elements=["memory_id"], set_=update_columns).returning(
                    table
                )

                result = sess.execute(stmt, memory_records)
                for row in result.fetchall():
                    memory_dict = dict(row._mapping)
                    if deserialize:
                        deserialized_memory = UserMemory.from_dict(memory_dict)
                        if deserialized_memory is None:
                            continue
                        results.append(deserialized_memory)
                    else:
                        results.append(memory_dict)

            return results

        except Exception as e:
            log_error(f"Exception bulk upserting memories: {e}")
            return []

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

        first_session_date = first_session[0]["created_at"] if first_session else None  # type: ignore[index]

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

            log_debug("Updated metrics calculations")

            return results

        except Exception as e:
            log_error(f"Exception refreshing metrics: {e}")
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
            log_error(f"Exception getting metrics: {e}")
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

        except Exception as e:
            log_error(f"Exception deleting knowledge content: {e}")
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
            log_error(f"Exception getting knowledge content: {e}")
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
            create_table_if_not_found (Optional[bool]): Whether to create the table if it doesn't exist.

        Returns:
            List[KnowledgeRow]: The knowledge contents.

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table = self._get_table(table_type="knowledge")
            if table is None:
                return [], 0

            with self.Session() as sess, sess.begin():
                stmt = select(table)

                # Apply sorting
                stmt = apply_sorting(stmt, table, sort_by, sort_order)

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
            log_error(f"Exception getting knowledge contents: {e}")
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
                # Get the actual table columns to avoid "unconsumed column names" error
                table_columns = set(table.columns.keys())

                # Only include fields that exist in the table and are not None
                insert_data = {}
                update_fields = {}

                # Map of KnowledgeRow fields to table columns
                field_mapping = {
                    "id": "id",
                    "name": "name",
                    "description": "description",
                    "metadata": "metadata",
                    "type": "type",
                    "size": "size",
                    "linked_to": "linked_to",
                    "access_count": "access_count",
                    "status": "status",
                    "status_message": "status_message",
                    "created_at": "created_at",
                    "updated_at": "updated_at",
                    "external_id": "external_id",
                }

                # Build insert and update data only for fields that exist in the table
                # String fields that need sanitization
                string_fields = {"name", "description", "type", "status", "status_message", "external_id", "linked_to"}

                for model_field, table_column in field_mapping.items():
                    if table_column in table_columns:
                        value = getattr(knowledge_row, model_field, None)
                        if value is not None:
                            # Sanitize string fields to remove null bytes
                            if table_column in string_fields and isinstance(value, str):
                                value = sanitize_postgres_string(value)
                            # Sanitize metadata dict if present
                            elif table_column == "metadata" and isinstance(value, dict):
                                value = sanitize_postgres_strings(value)
                            insert_data[table_column] = value
                            # Don't include ID in update_fields since it's the primary key
                            if table_column != "id":
                                update_fields[table_column] = value

                # Ensure id is always included for the insert
                if "id" in table_columns and knowledge_row.id:
                    insert_data["id"] = knowledge_row.id

                # Handle case where update_fields is empty (all fields are None or don't exist in table)
                if not update_fields:
                    # If we have insert_data, just do an insert without conflict resolution
                    if insert_data:
                        stmt = postgresql.insert(table).values(insert_data)
                        sess.execute(stmt)
                    else:
                        # If we have no data at all, this is an error
                        log_error("No valid fields found for knowledge row upsert")
                        return None
                else:
                    # Normal upsert with conflict resolution
                    stmt = (
                        postgresql.insert(table)
                        .values(insert_data)
                        .on_conflict_do_update(index_elements=["id"], set_=update_fields)
                    )
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
                eval_data = eval_run.model_dump()
                # Sanitize string fields in eval_run
                if eval_data.get("name"):
                    eval_data["name"] = sanitize_postgres_string(eval_data["name"])
                if eval_data.get("evaluated_component_name"):
                    eval_data["evaluated_component_name"] = sanitize_postgres_string(
                        eval_data["evaluated_component_name"]
                    )
                # Sanitize nested dicts/JSON fields
                if eval_data.get("eval_data"):
                    eval_data["eval_data"] = sanitize_postgres_strings(eval_data["eval_data"])
                if eval_data.get("eval_input"):
                    eval_data["eval_input"] = sanitize_postgres_strings(eval_data["eval_input"])

                stmt = postgresql.insert(table).values(
                    {"created_at": current_time, "updated_at": current_time, **eval_data}
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
                    log_warning(f"No eval runs found with IDs: {eval_run_ids}")
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

                eval_run_raw = dict(result._mapping)
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
                # Sanitize string field to remove null bytes
                sanitized_name = sanitize_postgres_string(name)
                stmt = (
                    table.update()
                    .where(table.c.run_id == eval_run_id)
                    .values(name=sanitized_name, updated_at=int(time.time()))
                )
                sess.execute(stmt)

            eval_run_raw = self.get_eval_run(eval_run_id=eval_run_id, deserialize=deserialize)
            if not eval_run_raw or not deserialize:
                return eval_run_raw

            return EvalRunRecord.model_validate(eval_run_raw)

        except Exception as e:
            log_error(f"Error upserting eval run name {eval_run_id}: {e}")
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

            return deserialize_cultural_knowledge(db_row)

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

            return [deserialize_cultural_knowledge(row) for row in db_rows]

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
            content_dict = serialize_cultural_knowledge(cultural_knowledge)
            # Sanitize content_dict to remove null bytes from nested strings
            if content_dict:
                content_dict = cast(Dict[str, Any], sanitize_postgres_strings(content_dict))

            # Sanitize string fields to remove null bytes (PostgreSQL doesn't allow them)
            sanitized_name = sanitize_postgres_string(cultural_knowledge.name)
            sanitized_summary = sanitize_postgres_string(cultural_knowledge.summary)
            sanitized_input = sanitize_postgres_string(cultural_knowledge.input)

            with self.Session() as sess, sess.begin():
                stmt = postgresql.insert(table).values(
                    id=cultural_knowledge.id,
                    name=sanitized_name,
                    summary=sanitized_summary,
                    content=content_dict if content_dict else None,
                    metadata=sanitize_postgres_strings(cultural_knowledge.metadata)
                    if cultural_knowledge.metadata
                    else None,
                    input=sanitized_input,
                    created_at=cultural_knowledge.created_at,
                    updated_at=int(time.time()),
                    agent_id=cultural_knowledge.agent_id,
                    team_id=cultural_knowledge.team_id,
                )
                stmt = stmt.on_conflict_do_update(  # type: ignore
                    index_elements=["id"],
                    set_=dict(
                        name=sanitized_name,
                        summary=sanitized_summary,
                        content=content_dict if content_dict else None,
                        metadata=sanitize_postgres_strings(cultural_knowledge.metadata)
                        if cultural_knowledge.metadata
                        else None,
                        input=sanitized_input,
                        updated_at=int(time.time()),
                        agent_id=cultural_knowledge.agent_id,
                        team_id=cultural_knowledge.team_id,
                    ),
                ).returning(table)

                result = sess.execute(stmt)
                row = result.fetchone()

                if row is None:
                    return None

            db_row = dict(row._mapping)
            if not db_row or not deserialize:
                return db_row

            return deserialize_cultural_knowledge(db_row)

        except Exception as e:
            log_error(f"Error upserting cultural knowledge: {e}")
            raise e

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
        try:
            table = self._get_table(table_type="traces", create_table_if_not_found=True)
            if table is None:
                return

            trace_dict = trace.to_dict()
            trace_dict.pop("total_spans", None)
            trace_dict.pop("error_count", None)
            # Sanitize string fields and nested JSON structures
            if trace_dict.get("name"):
                trace_dict["name"] = sanitize_postgres_string(trace_dict["name"])
            if trace_dict.get("status"):
                trace_dict["status"] = sanitize_postgres_string(trace_dict["status"])
            # Sanitize any nested dict/JSON fields
            trace_dict = cast(Dict[str, Any], sanitize_postgres_strings(trace_dict))

            with self.Session() as sess, sess.begin():
                # Use upsert to handle concurrent inserts atomically
                # On conflict, update fields while preserving existing non-null context values
                # and keeping the earliest start_time
                insert_stmt = postgresql.insert(table).values(trace_dict)

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
                # Use LEAST for start_time, GREATEST for end_time to capture full trace duration
                # Use COALESCE to preserve existing non-null context values
                upsert_stmt = insert_stmt.on_conflict_do_update(
                    index_elements=["trace_id"],
                    set_={
                        "end_time": func.greatest(table.c.end_time, insert_stmt.excluded.end_time),
                        "start_time": func.least(table.c.start_time, insert_stmt.excluded.start_time),
                        "duration_ms": func.extract(
                            "epoch",
                            func.cast(
                                func.greatest(table.c.end_time, insert_stmt.excluded.end_time),
                                TIMESTAMP(timezone=True),
                            )
                            - func.cast(
                                func.least(table.c.start_time, insert_stmt.excluded.start_time),
                                TIMESTAMP(timezone=True),
                            ),
                        )
                        * 1000,
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
            from agno.tracing.schemas import Trace

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
                Each dict contains: session_id, user_id, agent_id, team_id, total_traces,
                first_trace_at, last_trace_at.
        """
        try:
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
                span_dict = span.to_dict()
                # Sanitize string fields and nested JSON structures
                if span_dict.get("name"):
                    span_dict["name"] = sanitize_postgres_string(span_dict["name"])
                if span_dict.get("status_code"):
                    span_dict["status_code"] = sanitize_postgres_string(span_dict["status_code"])
                # Sanitize any nested dict/JSON fields
                span_dict = cast(Dict[str, Any], sanitize_postgres_strings(span_dict))
                stmt = postgresql.insert(table).values(span_dict)
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
                    span_dict = span.to_dict()
                    # Sanitize string fields and nested JSON structures
                    if span_dict.get("name"):
                        span_dict["name"] = sanitize_postgres_string(span_dict["name"])
                    if span_dict.get("status_code"):
                        span_dict["status_code"] = sanitize_postgres_string(span_dict["status_code"])
                    # Sanitize any nested dict/JSON fields
                    span_dict = sanitize_postgres_strings(span_dict)
                    stmt = postgresql.insert(table).values(span_dict)
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

    # --- Entities ---
    def get_entity(
        self,
        entity_id: str,
        entity_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get an entity by ID.

        Args:
            entity_id: The entity ID.
            entity_type: Optional type filter (agent|team|workflow).

        Returns:
            Entity dictionary or None if not found.
        """
        try:
            table = self._get_table(table_type="entities")
            if table is None:
                return None

            with self.Session() as sess:
                stmt = select(table).where(
                    table.c.entity_id == entity_id,
                    table.c.deleted_at.is_(None),
                )
                if entity_type is not None:
                    stmt = stmt.where(table.c.entity_type == entity_type)

                result = sess.execute(stmt).fetchone()
                return dict(result._mapping) if result else None

        except Exception as e:
            log_error(f"Error getting entity: {e}")
            raise

    def upsert_entity(
        self,
        entity_id: str,
        entity_type: Optional[PrimitiveType] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create or update an entity.

        Args:
            entity_id: Unique identifier.
            entity_type: Type (agent|team|workflow). Required for create, optional for update.
            name: Display name.
            description: Optional description.
            metadata: Optional metadata dict.

        Returns:
            Created/updated entity dictionary.

        Raises:
            ValueError: If creating and entity_type is not provided.
        """
        try:
            table = self._get_table(table_type="entities", create_table_if_not_found=True)

            with self.Session() as sess, sess.begin():
                existing = sess.execute(select(table).where(table.c.entity_id == entity_id)).fetchone()

                if existing is None:
                    # Create new entity
                    if entity_type is None:
                        raise ValueError("entity_type is required when creating a new entity")

                    sess.execute(
                        table.insert().values(
                            entity_id=entity_id,
                            entity_type=entity_type.value if hasattr(entity_type, "value") else entity_type,
                            name=name or entity_id,
                            description=description,
                            current_version=None,
                            metadata=metadata,
                            created_at=int(time.time()),
                        )
                    )
                    log_debug(f"Created entity {entity_id}")

                elif existing.deleted_at is not None:
                    # Reactivate soft-deleted
                    if entity_type is None:
                        raise ValueError("entity_type is required when reactivating a deleted entity")

                    sess.execute(
                        table.update()
                        .where(table.c.entity_id == entity_id)
                        .values(
                            entity_type=entity_type.value if hasattr(entity_type, "value") else entity_type,
                            name=name or entity_id,
                            description=description,
                            current_version=None,
                            metadata=metadata,
                            updated_at=int(time.time()),
                            deleted_at=None,
                        )
                    )
                    log_debug(f"Reactivated entity {entity_id}")

                else:
                    # Update existing
                    updates = {"updated_at": int(time.time())}
                    if entity_type is not None:
                        updates["entity_type"] = entity_type.value if hasattr(entity_type, "value") else entity_type
                    if name is not None:
                        updates["name"] = name
                    if description is not None:
                        updates["description"] = description
                    if metadata is not None:
                        updates["metadata"] = metadata

                    sess.execute(table.update().where(table.c.entity_id == entity_id).values(**updates))
                    log_debug(f"Updated entity {entity_id}")

            return self.get_entity(entity_id)

        except Exception as e:
            log_error(f"Error upserting entity: {e}")
            raise

    def delete_entity(
        self,
        entity_id: str,
        hard_delete: bool = False,
    ) -> bool:
        """Delete an entity and all its configs/refs.

        Args:
            entity_id: The entity ID.
            hard_delete: If True, permanently delete. Otherwise soft-delete.

        Returns:
            True if deleted, False if not found.
        """
        try:
            entities_table = self._get_table(table_type="entities")
            configs_table = self._get_table(table_type="configs")
            refs_table = self._get_table(table_type="entity_refs")

            if entities_table is None:
                return False

            with self.Session() as sess, sess.begin():
                if hard_delete:
                    # Delete refs where this entity is parent or child
                    if refs_table is not None:
                        sess.execute(refs_table.delete().where(refs_table.c.parent_entity_id == entity_id))
                        sess.execute(refs_table.delete().where(refs_table.c.child_entity_id == entity_id))
                    # Delete configs
                    if configs_table is not None:
                        sess.execute(configs_table.delete().where(configs_table.c.entity_id == entity_id))
                    # Delete entity
                    result = sess.execute(entities_table.delete().where(entities_table.c.entity_id == entity_id))
                else:
                    # Soft delete
                    now = int(time.time())
                    result = sess.execute(
                        entities_table.update()
                        .where(entities_table.c.entity_id == entity_id)
                        .values(deleted_at=now, current_version=None)
                    )

            return result.rowcount > 0

        except Exception as e:
            log_error(f"Error deleting entity: {e}")
            raise

    def list_entities(
        self,
        entity_type: Optional[str] = None,
        include_deleted: bool = False,
    ) -> List[Dict[str, Any]]:
        """List all entities, optionally filtered by type.

        Args:
            entity_type: Filter by type (agent|team|workflow).
            include_deleted: Include soft-deleted entities.

        Returns:
            List of entity dictionaries.
        """
        try:
            table = self._get_table(table_type="entities")
            if table is None:
                return []

            with self.Session() as sess:
                stmt = select(table).order_by(table.c.created_at.desc())

                if entity_type is not None:
                    stmt = stmt.where(table.c.entity_type == entity_type)
                if not include_deleted:
                    stmt = stmt.where(table.c.deleted_at.is_(None))

                results = sess.execute(stmt).fetchall()
                return [dict(row._mapping) for row in results]

        except Exception as e:
            log_error(f"Error listing entities: {e}")
            raise

    # --- Config ---
    def get_config(
        self,
        entity_id: str,
        version: Optional[int] = None,
        label: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get a config by entity ID and version/label.

        Args:
            entity_id: The entity ID.
            version: Specific version number. If None, uses current.
            label: Version label to lookup. Ignored if version is provided.

        Returns:
            Config dictionary or None if not found.
        """
        try:
            configs_table = self._get_table(table_type="configs")
            entities_table = self._get_table(table_type="entities")

            if configs_table is None or entities_table is None:
                return None

            with self.Session() as sess:
                if version is not None:
                    # Direct version lookup
                    stmt = select(configs_table).where(
                        configs_table.c.entity_id == entity_id,
                        configs_table.c.version == version,
                    )
                elif label is not None:
                    # Label lookup
                    stmt = select(configs_table).where(
                        configs_table.c.entity_id == entity_id,
                        configs_table.c.version_label == label,
                    )
                else:
                    # Get current version from entity
                    entity = sess.execute(
                        select(entities_table.c.current_version).where(entities_table.c.entity_id == entity_id)
                    ).fetchone()

                    if entity is None or entity.current_version is None:
                        return None

                    stmt = select(configs_table).where(
                        configs_table.c.entity_id == entity_id,
                        configs_table.c.version == entity.current_version,
                    )

                result = sess.execute(stmt).fetchone()
                return dict(result._mapping) if result else None

        except Exception as e:
            log_error(f"Error getting config: {e}")
            raise

    def upsert_config(
        self,
        entity_id: str,
        config: Dict[str, Any],
        version: Optional[int] = None,
        version_label: Optional[str] = None,
        stage: str = "draft",
        notes: Optional[str] = None,
        set_current: bool = True,
        refs: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Create or update a config version for an entity.

        Args:
            entity_id: The entity ID.
            config: The config data.
            version: If None, creates new version. If provided, updates that version.
            version_label: Optional human-readable label.
            stage: "draft" or "published".
            notes: Optional notes.
            set_current: Whether to set as current version.
            refs: Optional list of refs to create/replace with this config.

        Returns:
            Created/updated config dictionary.

        Raises:
            ValueError: If entity doesn't exist, version not found, or label conflict.
        """
        try:
            configs_table = self._get_table(table_type="configs", create_table_if_not_found=True)
            entities_table = self._get_table(table_type="entities")
            refs_table = self._get_table(table_type="entity_refs", create_table_if_not_found=True)

            with self.Session() as sess, sess.begin():
                # Verify entity exists
                entity = sess.execute(
                    select(entities_table).where(
                        entities_table.c.entity_id == entity_id,
                        entities_table.c.deleted_at.is_(None),
                    )
                ).fetchone()
                if entity is None:
                    raise ValueError(f"Entity {entity_id} not found")

                # Check label uniqueness (exclude current version if updating)
                if version_label is not None:
                    label_query = select(configs_table).where(
                        configs_table.c.entity_id == entity_id,
                        configs_table.c.version_label == version_label,
                    )
                    if version is not None:
                        label_query = label_query.where(configs_table.c.version != version)

                    existing_label = sess.execute(label_query).fetchone()
                    if existing_label:
                        raise ValueError(f"Label '{version_label}' already exists for {entity_id}")

                # Validate refs for published configs
                if stage == "published" and refs:
                    for ref in refs:
                        if ref.get("child_version") is None:
                            raise ValueError(
                                f"Published configs must have pinned refs. "
                                f"Ref to {ref['child_entity_id']} has no version."
                            )

                if version is None:
                    # CREATE: Get next version number
                    max_version = sess.execute(
                        select(configs_table.c.version)
                        .where(configs_table.c.entity_id == entity_id)
                        .order_by(configs_table.c.version.desc())
                        .limit(1)
                    ).scalar()
                    new_version = (max_version or 0) + 1

                    sess.execute(
                        configs_table.insert().values(
                            entity_id=entity_id,
                            version=new_version,
                            version_label=version_label,
                            stage=stage,
                            config=config,
                            notes=notes,
                            created_at=int(time.time()),
                        )
                    )
                    final_version = new_version
                    log_debug(f"Created config {entity_id} v{final_version}")

                else:
                    # UPDATE: Verify version exists
                    existing = sess.execute(
                        select(configs_table).where(
                            configs_table.c.entity_id == entity_id,
                            configs_table.c.version == version,
                        )
                    ).fetchone()
                    if existing is None:
                        raise ValueError(f"Config {entity_id} v{version} not found")

                    # TODO: prevent updating published configs

                    sess.execute(
                        configs_table.update()
                        .where(
                            configs_table.c.entity_id == entity_id,
                            configs_table.c.version == version,
                        )
                        .values(
                            version_label=version_label,
                            stage=stage,
                            config=config,
                            notes=notes,
                            updated_at=int(time.time()),
                        )
                    )
                    final_version = version
                    log_debug(f"Updated config {entity_id} v{final_version}")

                # Handle refs (delete old, insert new)
                if refs is not None and refs_table is not None:
                    # Delete existing refs for this version
                    sess.execute(
                        refs_table.delete().where(
                            refs_table.c.parent_entity_id == entity_id,
                            refs_table.c.parent_version == final_version,
                        )
                    )
                    # Insert new refs
                    for ref in refs:
                        sess.execute(
                            refs_table.insert().values(
                                parent_entity_id=entity_id,
                                parent_version=final_version,
                                ref_kind=ref["ref_kind"],
                                ref_key=ref["ref_key"],
                                child_entity_id=ref["child_entity_id"],
                                child_version=ref.get("child_version"),
                                position=ref["position"],
                                meta=ref.get("meta"),
                                created_at=int(time.time()),
                            )
                        )

                # Update current version pointer
                if set_current:
                    sess.execute(
                        entities_table.update()
                        .where(entities_table.c.entity_id == entity_id)
                        .values(current_version=final_version, updated_at=int(time.time()))
                    )

            return self.get_config(entity_id, version=final_version)

        except Exception as e:
            log_error(f"Error upserting config: {e}")
            raise

    def list_config_versions(
        self,
        entity_id: str,
    ) -> List[Dict[str, Any]]:
        """List all config versions for an entity.

        Args:
            entity_id: The entity ID.

        Returns:
            List of config dictionaries, newest first.
        """
        try:
            table = self._get_table(table_type="configs")
            if table is None:
                return []

            with self.Session() as sess:
                stmt = select(table).where(table.c.entity_id == entity_id).order_by(table.c.version.desc())
                results = sess.execute(stmt).fetchall()
                return [dict(row._mapping) for row in results]

        except Exception as e:
            log_error(f"Error listing config versions: {e}")
            raise

    def set_current_version(
        self,
        entity_id: str,
        version: int,
    ) -> bool:
        """Set a specific version as current.

        Args:
            entity_id: The entity ID.
            version: The version to set as current.

        Returns:
            True if successful, False if version not found.
        """
        try:
            configs_table = self._get_table(table_type="configs")
            entities_table = self._get_table(table_type="entities")

            if configs_table is None or entities_table is None:
                return False

            with self.Session() as sess, sess.begin():
                # Verify version exists
                exists = sess.execute(
                    select(configs_table).where(
                        configs_table.c.entity_id == entity_id,
                        configs_table.c.version == version,
                    )
                ).fetchone()
                if exists is None:
                    return False

                # Update pointer
                sess.execute(
                    entities_table.update()
                    .where(entities_table.c.entity_id == entity_id)
                    .values(current_version=version, updated_at=int(time.time()))
                )

            log_debug(f"Set {entity_id} current version to {version}")
            return True

        except Exception as e:
            log_error(f"Error setting current version: {e}")
            raise

    def publish_config(
        self,
        entity_id: str,
        version: int,
        pin_refs: bool = True,
    ) -> bool:
        """Publish a config version, optionally pinning all refs.

        Args:
            entity_id: The entity ID.
            version: The version to publish.
            pin_refs: If True, resolve and pin all NULL child_versions.

        Returns:
            True if successful, False if version not found.
        """
        try:
            configs_table = self._get_table(table_type="configs")
            refs_table = self._get_table(table_type="entity_refs")
            entities_table = self._get_table(table_type="entities")

            if configs_table is None:
                return False

            with self.Session() as sess, sess.begin():
                # Verify version exists and is draft
                config = sess.execute(
                    select(configs_table).where(
                        configs_table.c.entity_id == entity_id,
                        configs_table.c.version == version,
                    )
                ).fetchone()
                if config is None:
                    return False

                # Pin refs if requested
                if pin_refs and refs_table is not None:
                    refs = sess.execute(
                        select(refs_table).where(
                            refs_table.c.parent_entity_id == entity_id,
                            refs_table.c.parent_version == version,
                            refs_table.c.child_version.is_(None),
                        )
                    ).fetchall()

                    for ref in refs:
                        # Resolve current version
                        child_current = sess.execute(
                            select(entities_table.c.current_version).where(
                                entities_table.c.entity_id == ref.child_entity_id
                            )
                        ).scalar()

                        if child_current is None:
                            raise ValueError(f"Cannot pin ref to {ref.child_entity_id}: no current version")

                        # Update ref
                        sess.execute(
                            refs_table.update()
                            .where(
                                refs_table.c.parent_entity_id == entity_id,
                                refs_table.c.parent_version == version,
                                refs_table.c.ref_kind == ref.ref_kind,
                                refs_table.c.ref_key == ref.ref_key,
                            )
                            .values(child_version=child_current, updated_at=int(time.time()))
                        )

                # Update stage
                sess.execute(
                    configs_table.update()
                    .where(
                        configs_table.c.entity_id == entity_id,
                        configs_table.c.version == version,
                    )
                    .values(stage="published", updated_at=int(time.time()))
                )

            log_debug(f"Published {entity_id} v{version}")
            return True

        except Exception as e:
            log_error(f"Error publishing config: {e}")
            raise

    # -- References --
    def get_refs(
        self,
        entity_id: str,
        version: int,
        ref_kind: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get refs for a config version.

        Args:
            entity_id: The entity ID.
            version: The config version.
            ref_kind: Optional filter by ref kind (member|step).

        Returns:
            List of ref dictionaries, ordered by position.
        """
        try:
            table = self._get_table(table_type="entity_refs")
            if table is None:
                return []

            with self.Session() as sess:
                stmt = (
                    select(table)
                    .where(
                        table.c.parent_entity_id == entity_id,
                        table.c.parent_version == version,
                    )
                    .order_by(table.c.position)
                )
                if ref_kind is not None:
                    stmt = stmt.where(table.c.ref_kind == ref_kind)

                results = sess.execute(stmt).fetchall()
                return [dict(row._mapping) for row in results]

        except Exception as e:
            log_error(f"Error getting refs: {e}")
            raise

    def get_dependents(
        self,
        entity_id: str,
        version: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Find all entities that reference this entity.

        Args:
            entity_id: The entity ID to find dependents of.
            version: Optional specific version. If None, finds refs to any version.

        Returns:
            List of ref dictionaries showing what depends on this entity.
        """
        try:
            table = self._get_table(table_type="entity_refs")
            if table is None:
                return []

            with self.Session() as sess:
                stmt = select(table).where(table.c.child_entity_id == entity_id)
                if version is not None:
                    stmt = stmt.where(table.c.child_version == version)

                results = sess.execute(stmt).fetchall()
                return [dict(row._mapping) for row in results]

        except Exception as e:
            log_error(f"Error getting dependents: {e}")
            raise

    def resolve_version(
        self,
        entity_id: str,
        version: Optional[int],
    ) -> Optional[int]:
        """Resolve a version number, handling NULL (current) case.

        Args:
            entity_id: The entity ID.
            version: Version number or None for current.

        Returns:
            Resolved version number or None if entity not found.
        """
        if version is not None:
            return version

        try:
            entities_table = self._get_table(table_type="entities")
            if entities_table is None:
                return None

            with self.Session() as sess:
                result = sess.execute(
                    select(entities_table.c.current_version).where(entities_table.c.entity_id == entity_id)
                ).scalar()
                return result

        except Exception as e:
            log_error(f"Error resolving version: {e}")
            raise

    def load_entity_graph(
        self,
        entity_id: str,
        version: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Load an entity with its full resolved graph.

        Args:
            entity_id: The entity ID.
            version: Specific version or None for current.

        Returns:
            Dictionary with entity, config, refs, and resolved children.
        """
        try:
            # Get entity
            entity = self.get_entity(entity_id)
            if entity is None:
                return None

            # Resolve version
            resolved_version = self.resolve_version(entity_id, version)
            if resolved_version is None:
                return None

            # Get config
            config = self.get_config(entity_id, version=resolved_version)
            if config is None:
                return None

            # Get refs
            refs = self.get_refs(entity_id, resolved_version)

            # Resolve children recursively
            children = []
            resolved_versions = {entity_id: resolved_version}

            for ref in refs:
                child_version = self.resolve_version(
                    ref["child_entity_id"],
                    ref["child_version"],
                )
                resolved_versions[ref["child_entity_id"]] = child_version

                child_graph = self.load_entity_graph(
                    ref["child_entity_id"],
                    version=child_version,
                )

                if child_graph:
                    # Merge nested resolved versions
                    resolved_versions.update(child_graph.get("resolved_versions", {}))

                children.append(
                    {
                        "ref": ref,
                        "graph": child_graph,
                    }
                )

            return {
                "entity": entity,
                "config": config,
                "children": children,
                "resolved_versions": resolved_versions,
            }

        except Exception as e:
            log_error(f"Error loading entity graph: {e}")
            raise
