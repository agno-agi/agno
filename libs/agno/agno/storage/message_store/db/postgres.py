import time
import uuid
from datetime import datetime
from hashlib import md5
from typing import Any, Dict, List, Literal, Optional

from agno.embedder import Embedder
from agno.storage.base import Storage
from agno.storage.message_store.db.base import MessageHistoryStoreDb
from agno.storage.session import Session
from agno.storage.session.agent import AgentSession
from agno.storage.session.team import TeamSession
from agno.storage.session.workflow import WorkflowSession
from agno.utils.log import log_debug, log_info, log_warning, logger

try:
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.engine import Engine, create_engine
    from sqlalchemy.inspection import inspect
    from sqlalchemy.orm import scoped_session, sessionmaker
    from sqlalchemy.schema import Column, Index, MetaData, Table
    from sqlalchemy.sql.expression import select, text
    from sqlalchemy.types import BigInteger, String
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    raise ImportError("`pgvector` not installed. Please install using `pip install pgvector`")


class PgVectorMessageStore(MessageHistoryStoreDb):
    def __init__(
        self,
        table_name: str,
        schema: Optional[str] = "ai",
        db_url: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        embedder: Optional[Embedder] = None,
    ):
        """
        This class provides message history storage using a PostgreSQL table.

        The following order is used to determine the database connection:
            1. Use the db_engine if provided
            2. Use the db_url
            3. Raise an error if neither is provided

        Args:
            table_name (str): Name of the table to store message history.
            schema (Optional[str]): The schema to use for the table. Defaults to "ai".
            db_url (Optional[str]): The database URL to connect to.
            db_engine (Optional[Engine]): The SQLAlchemy database engine to use.
            schema_version (int): Version of the schema. Defaults to 1.
            auto_upgrade_schema (bool): Whether to automatically upgrade the schema.
            mode (Optional[Literal["agent", "team", "workflow"]]): The mode of the storage.
        Raises:
            ValueError: If neither db_url nor db_engine is provided.
        """
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

        # Embedder for embedding the document contents
        if embedder is None:
            from agno.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_info("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder: Embedder = embedder

        if self.embedder is None:
            self.embedder = Embedder()

        # Database session
        self.Session: scoped_session = scoped_session(sessionmaker(bind=self.db_engine))
        # Database table for storage
        self.table: Table = self.get_table()

    def get_table(self) -> Table:
        """
        Get the table schema based on the schema version.

        Returns:
            Table: SQLAlchemy Table object for the current schema version.

        Raises:
            ValueError: If an unsupported schema version is specified.
        """
        table = Table(
            self.table_name,
            self.metadata,
            Column("message_id", String, primary_key=True),
            Column("user_message", String),
            Column("session_id", String, primary_key=True),
            Column("user_id", String, index=True),
            Column("run_messages", postgresql.JSONB),
            Column("embeddings", Vector(self.embedder.dimensions)),
            Column("created_at", BigInteger, server_default=text("(extract(epoch from now()))::bigint")),
            Column("updated_at", BigInteger, server_onupdate=text("(extract(epoch from now()))::bigint")),
        )

        # Add indexes
        Index("idx_{self.table_name}_message_id", table.c.message_id)
        Index("idx_{self.table_name}_session_id", table.c.session_id)
        Index("idx_{self.table_name}_user_id", table.c.user_id)
        Index("idx_{self.table_name}_user_message", table.c.user_message)

        return table

    def create(self) -> None:
        """
        Create the table if it does not exist.
        """
        if not self.table_exists():
            try:
                with self.Session() as sess, sess.begin():
                    if self.schema is not None:
                        log_debug(f"Creating schema: {self.schema}")
                        sess.execute(text(f"CREATE SCHEMA IF NOT EXISTS {self.schema};"))
                log_debug(f"Creating table: {self.table_name}")
                self.table.create(self.db_engine, checkfirst=True)
            except Exception as e:
                logger.error(f"Error creating table '{self.table.fullname}': {e}")
                raise

    def table_exists(self) -> bool:
        """
        Check if the table exists in the database.
        """
        return self.inspector.has_table(self.table_name, schema=self.schema)

    def upsert(self, session_id: str, user_id: str, runs: List[Dict[str, Any]]):
        """
        Upsert a message into the database.
        """

        session_id = session_id
        user_id = user_id
        runs = runs

        if runs is None or len(runs) == 0:
            return

        for run in runs:
            message = run.get("message", {})
            if message.get("role") != "user":
                continue

            user_message = message.get("content", "")
            cleaned_content = user_message.strip().lower()
            message_id = md5(cleaned_content.encode()).hexdigest()
            embedding = self.embedder.get_embedding(user_message)

            row = {
                "message_id": message_id,
                "user_message": user_message,
                "session_id": session_id,
                "user_id": user_id,
                "run_messages": run.get("response", {}).get("messages", []),
                "embeddings": embedding,
            }

            stmt = postgresql.insert(self.table).values(row)
            stmt = stmt.on_conflict_do_update(
                index_elements=["message_id", "session_id"],
                set_={
                    "user_message": stmt.excluded.user_message,
                    "user_id": stmt.excluded.user_id,
                    "run_messages": stmt.excluded.run_messages,
                    "embeddings": stmt.excluded.embeddings,
                    "updated_at": stmt.excluded.updated_at,
                },
            )

            self.Session.execute(stmt)

        self.Session.commit()

    def read(self, session_id: str, user_id: str) -> List[Dict[str, Any]]:
        """
        Read user messages from the database for a given session and user.

        Args:
            session_id (str): The session identifier.
            user_id (str): The user identifier.

        Returns:
            List[Dict[str, Any]]: A list of message records.
        """
        try:
            with self.Session() as sess:
                query = (
                    self.table.select()
                    .where(self.table.c.session_id == session_id, self.table.c.user_id == user_id)
                    .order_by(self.table.c.created_at.asc())
                )
                results = sess.execute(query).fetchall()
                return [dict(row._mapping) for row in results]

        except Exception as e:
            log_debug(f"Error reading messages: {e}")
            return []

    def search(
        self, query: str, user_id: Optional[str] = None, session_id: Optional[str] = None, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
            Perform a vector similarity search over user messages.

        Args:
            query (str): The user query.
            user_id (Optional[str]): Optional user ID to filter.
            session_id (Optional[str]): Optional session ID to filter.
            limit (int): Number of results to return.

        Returns:
            List[Dict[str, Any]]: Matching message rows with similarity ordering.
        """
        try:
            query_embedding = self.embedder.get_embedding(query)
            if query_embedding is None:
                logger.error(f"Failed to generate embedding for query: {query}")
                return []

            stmt = select(
                self.table.c.run_messages,
            )

            # Optional filters
            if user_id:
                stmt = stmt.where(self.table.c.user_id == user_id)
            if session_id:
                stmt = stmt.where(self.table.c.session_id == session_id)

            # Apply distance function
            stmt = stmt.order_by(self.table.c.embeddings.cosine_distance(query_embedding)).limit(limit)

            with self.Session() as sess, sess.begin():
                results = sess.execute(stmt).fetchall()

            return [dict(row._mapping) for row in results]

        except Exception as e:
            logger.error(f"Error during message vector search: {e}")
            return []

    def exists(self) -> bool:
        """
        Check if the table exists in the database.
        """
        return self.table_exists()
