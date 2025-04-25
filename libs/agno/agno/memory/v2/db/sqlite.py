import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    from sqlalchemy import (JSON, Column, DateTime, Engine, MetaData, String,
                            Table, create_engine, delete, inspect, select,
                            text)
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import scoped_session, sessionmaker
    from sqlalchemy.sql.expression import (Insert,  # Import Insert and Update
                                           Update)
except ImportError:
    raise ImportError(
        "`sqlalchemy` not installed. Please install it with `pip install sqlalchemy`"
    )

try:
    import numpy as np
except ImportError:
    raise ImportError(
        "`numpy` not installed. Please install it with `pip install numpy`"
    )

from agno.memory.v2.db.base import MemoryDb
from agno.memory.v2.db.schema import MemoryRow
from agno.utils.log import log_debug, log_info, log_warning, logger


# Helper function for calculating cosine similarity
def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    # Ensure inputs are lists of floats
    if not isinstance(v1, list) or not isinstance(v2, list):
        return 0.0
    if not all(isinstance(x, (int, float)) for x in v1) or not all(
        isinstance(x, (int, float)) for x in v2
    ):
        return 0.0

    v1_array = np.array(v1).astype(float)
    v2_array = np.array(v2).astype(float)

    # Check for zero vectors or dimension mismatch
    if (
        v1_array.shape != v2_array.shape
        or np.linalg.norm(v1_array) == 0
        or np.linalg.norm(v2_array) == 0
    ):
        return 0.0

    dot_product = np.dot(v1_array, v2_array)
    norm_v1 = np.linalg.norm(v1_array)
    norm_v2 = np.linalg.norm(v2_array)

    similarity = dot_product / (norm_v1 * norm_v2)
    # Clip similarity to [-1, 1] to handle potential floating point inaccuracies
    return float(np.clip(similarity, -1.0, 1.0))


class SqliteMemoryDb(MemoryDb):
    def __init__(
        self,
        table_name: str = "memory",
        db_url: Optional[str] = None,
        db_file: Optional[str] = None,
        db_engine: Optional[Engine] = None,
    ):
        """
        This class provides a memory store backed by a SQLite table.

        The following order is used to determine the database connection:
            1. Use the db_engine if provided
            2. Use the db_url
            3. Use the db_file
            4. Create a new in-memory database

        Args:
            table_name: The name of the table to store Agent sessions.
            db_url: The database URL to connect to.
            db_file: The database file to connect to.
            db_engine: The database engine to use.
        """
        self.db_file = db_file
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

        # Database session
        self.Session = scoped_session(sessionmaker(bind=self.db_engine))
        # Database table for memories
        self.table: Table = self.get_table()

    def __dict__(self) -> Dict[str, Any]:
        return {
            "name": "SqliteMemoryDb",
            "table_name": self.table_name,
            "db_file": self.db_file,
        }

    def get_table(self) -> Table:
        return Table(
            self.table_name,
            self.metadata,
            Column("id", String, primary_key=True),
            Column("user_id", String, index=True),
            Column("memory", String),  # Store memory data as JSON string
            Column("created_at", DateTime, server_default=text("CURRENT_TIMESTAMP")),
            Column("embedding", JSON),  # Store embedding as JSON
            Column(
                "updated_at",
                DateTime,
                server_default=text("CURRENT_TIMESTAMP"),
                onupdate=text("CURRENT_TIMESTAMP"),
            ),
            extend_existing=True,
        )

    def create(self) -> None:
        if not self.table_exists():
            try:
                log_debug(f"Creating table: {self.table_name}")
                self.table.create(self.db_engine, checkfirst=True)
            except Exception as e:
                logger.error(f"Error creating table '{self.table_name}': {e}")
                raise

    def memory_exists(self, memory: MemoryRow) -> bool:
        with self.Session() as session:
            stmt = select(self.table.c.id).where(self.table.c.id == memory.id)
            result = session.execute(stmt).first()
            return result is not None

    def read_memories(
        self,
        user_id: Optional[str] = None,
        limit: Optional[int] = None,
        sort: Optional[str] = None,
    ) -> List[MemoryRow]:
        memories: List[MemoryRow] = []
        try:
            with self.Session() as session:
                stmt = select(self.table)
                if user_id is not None:
                    stmt = stmt.where(self.table.c.user_id == user_id)

                if sort == "asc":
                    stmt = stmt.order_by(self.table.c.created_at.asc())
                else:
                    # Default to descending order (latest first)
                    stmt = stmt.order_by(self.table.c.created_at.desc())

                if limit is not None:
                    stmt = stmt.limit(limit)

                result = session.execute(stmt)
                for row in result:
                    try:
                        # Decode memory from JSON string
                        memory_data = json.loads(row.memory)
                        # Decode embedding from JSON if it exists
                        embedding_data = (
                            json.loads(row.embedding) if row.embedding else None
                        )

                        memories.append(
                            MemoryRow(
                                id=row.id,
                                user_id=row.user_id,
                                memory=memory_data,  # Assign decoded dict
                                embedding=embedding_data,  # Assign decoded list or None
                                last_updated=row.updated_at or row.created_at,
                            )
                        )
                    except (json.JSONDecodeError, TypeError, KeyError) as e:
                        log_warning(
                            f"Error processing memory row {row.id} during read: {e}"
                        )

        except SQLAlchemyError as e:
            log_debug(f"Exception reading from table: {e}")
            # If table doesn't exist, create it
            if not self.table_exists():
                log_debug(f"Table does not exist: {self.table_name}")
                log_debug("Creating table for future transactions")
                self.create()
        return memories

    def upsert_memory(self, memory: MemoryRow, create_and_retry: bool = True) -> None:
        try:
            with self.Session() as session:
                existing = session.execute(
                    select(self.table).where(self.table.c.id == memory.id)
                ).first()

                # Serialize memory dict and embedding list to JSON strings for storage
                memory_json = json.dumps(memory.memory)
                embedding_json = (
                    json.dumps(memory.embedding) if memory.embedding else None
                )

                stmt: Union[Update, Insert]  # Add type hint for stmt
                if existing:
                    stmt = (
                        self.table.update()
                        .where(self.table.c.id == memory.id)
                        .values(
                            user_id=memory.user_id,
                            memory=memory_json,  # Store JSON string
                            updated_at=text("CURRENT_TIMESTAMP"),
                            embedding=embedding_json,  # Store JSON string or None
                        )
                    )
                else:
                    stmt = self.table.insert().values(
                        id=memory.id,
                        user_id=memory.user_id,
                        memory=memory_json,  # Store JSON string
                        embedding=embedding_json,  # Store JSON string or None
                    )

                session.execute(stmt)
                session.commit()
        except SQLAlchemyError as e:
            logger.error(f"Exception upserting into table: {e}")
            if not self.table_exists():
                log_info(f"Table does not exist: {self.table_name}")
                log_info("Creating table for future transactions")
                self.create()
                if create_and_retry:
                    return self.upsert_memory(memory, create_and_retry=False)
            else:
                raise

    def delete_memory(self, memory_id: str) -> None:
        with self.Session() as session:
            stmt = delete(self.table).where(self.table.c.id == memory_id)
            session.execute(stmt)
            session.commit()

    def drop_table(self) -> None:
        if self.table_exists():
            log_debug(f"Deleting table: {self.table_name}")
            self.table.drop(self.db_engine)

    def table_exists(self) -> bool:
        log_debug(f"Checking if table exists: {self.table.name}")
        try:
            return self.inspector.has_table(self.table.name)
        except Exception as e:
            logger.error(e)
            return False

    def clear(self) -> bool:
        with self.Session() as session:
            if self.table_exists():
                stmt = delete(self.table)
                session.execute(stmt)
                session.commit()
        return True

    def search_memories_semantic(
        self,
        query_embedding: List[float],
        user_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[MemoryRow]:
        """Retrieve memories semantically similar to the query embedding using cosine similarity."""
        memories: List[MemoryRow] = []
        try:
            with self.Session() as session:
                stmt = select(self.table)
                if user_id is not None:
                    stmt = stmt.where(self.table.c.user_id == user_id)

                # Filter out rows without embeddings before fetching
                stmt = stmt.where(self.table.c.embedding.is_not(None))

                result = session.execute(stmt)
                all_rows = result.fetchall()  # Fetch all rows first

            # Calculate cosine similarity for each memory
            memory_similarities = []
            for row in all_rows:  # Iterate through fetched rows
                try:
                    # Decode memory from JSON string
                    memory_data = json.loads(row.memory)
                    # Decode embedding from JSON if it exists
                    embedding_data = (
                        json.loads(row.embedding) if row.embedding else None
                    )

                    if embedding_data:
                        # Call the helper function directly, not as a method
                        similarity = cosine_similarity(query_embedding, embedding_data)
                        # Reconstruct MemoryRow here to include similarity temporarily
                        # We need the full MemoryRow for the final result list
                        mem_row = MemoryRow(
                            id=row.id,
                            user_id=row.user_id,
                            memory=memory_data,
                            embedding=embedding_data,  # Keep embedding for potential debugging
                            last_updated=row.updated_at or row.created_at,
                        )
                        memory_similarities.append(
                            (mem_row, similarity)
                        )  # Store tuple (MemoryRow, similarity)
                    else:
                        log_warning(
                            f"Memory row {row.id} missing embedding data, skipping."
                        )

                except (json.JSONDecodeError, TypeError, KeyError) as e:
                    log_warning(
                        f"Error processing memory row {row.id} during semantic search: {e}"
                    )

            # Sort memories by similarity score (descending)
            memory_similarities.sort(key=lambda item: item[1], reverse=True)

            # Apply limit
            if limit is not None:
                memory_similarities = memory_similarities[:limit]

            # Extract MemoryRow objects from sorted list
            memories = [
                item[0] for item in memory_similarities
            ]  # Extract MemoryRow from tuple

        except SQLAlchemyError as e:
            log_debug(f"Exception reading from table during semantic search: {e}")
            # If table doesn't exist, create it (though less likely in semantic search path)
            if not self.table_exists():
                log_debug(f"Table does not exist: {self.table_name}")
                self.create()
        except ImportError:
            log_warning(
                "Numpy is required for cosine similarity calculation in SQLite. Please install numpy."
            )
            # Optionally, could fall back to non-semantic search here, but for now return empty
        except Exception as e:
            log_warning(f"Unexpected error during SQLite semantic search: {e}")

        return memories

    def __del__(self):
        # self.Session.remove()
        pass
