from textwrap import dedent
from typing import Final, List, Optional, Union

try:
    from surrealdb import BlockingHttpSurrealConnection, BlockingWsSurrealConnection, RecordID
except ImportError as e:
    msg = "The `surrealdb` package is not installed. Please install it via `pip install surrealdb`."
    raise ImportError(msg) from e

from agno.memory.v2.db.base import MemoryDb
from agno.memory.v2.db.schema import MemoryRow
from agno.utils.log import log_debug, logger


class SurrealMemoryDb(MemoryDb):
    """SurrealDB Memory Database implementation."""

    # SurrealQL queries
    CREATE_TABLE_QUERY: Final[str] = dedent("""
        DEFINE TABLE IF NOT EXISTS {table} SCHEMAFUL;

        DEFINE FIELD IF NOT EXISTS memory ON {table} FLEXIBLE TYPE object;
        DEFINE FIELD IF NOT EXISTS user ON {table} TYPE record<user>;
        DEFINE FIELD IF NOT EXISTS time ON {table} TYPE object DEFAULT ALWAYS {{}};
        DEFINE FIELD IF NOT EXISTS time.created_at ON {table} TYPE datetime VALUE time::now() READONLY;
        DEFINE FIELD IF NOT EXISTS time.updated_at ON {table} TYPE datetime VALUE time::now() READONLY;

        DEFINE INDEX IF NOT EXISTS idx_{table}_user ON {table} FIELDS user;
    """)
    INFO_DB_QUERY: Final[str] = "INFO FOR DB;"

    def __init__(
        self,
        *,
        client: Union[BlockingWsSurrealConnection, BlockingHttpSurrealConnection],
        table: str = "memory",
    ):
        """
        This class provides a memory store backed by a SurrealDB table.

        Args:
            client: A blocking connection, either HTTP or WS
            table: The name of the table to store memories
        """
        self.client: Union[BlockingHttpSurrealConnection, BlockingWsSurrealConnection] = client
        self.table: str = table
        self.users_table: str = "user"

    def create(self) -> None:
        """Create indexes for the table"""
        if not self.table_exists():
            log_debug(f"Creating table: {self.table}")
            query = self.CREATE_TABLE_QUERY.format(table=self.table)
            self.client.query(query)

    def memory_exists(self, memory: MemoryRow) -> bool:
        """Check if a memory exists

        Args:
            memory: MemoryRow to check
        Returns:
            bool: True if the memory exists, False otherwise
        """
        try:
            result = self.client.select(RecordID(self.table, memory.id))
            logger.debug(f"Found: {result}")
            return bool(result)
        except Exception as e:
            logger.error(f"Error checking memory existence: {e}")
            return False

    def read_memories(
        self, user_id: Optional[str] = None, limit: Optional[int] = None, sort: Optional[str] = None
    ) -> List[MemoryRow]:
        """Read memories from the table

        Args:
            user_id: ID of the user to read
            limit: Maximum number of memories to read
            sort: Sort order ("asc" or "desc")
        Returns:
            List[MemoryRow]: List of memories
        """
        filter_clause = "WHERE user = $user" if user_id is not None else ""
        limit_clause = f"LIMIT {limit}" if limit is not None else ""
        order_clause = f"ORDER BY time.created_at {sort}" if sort is not None else ""
        query = dedent(f"""
            SELECT *
            FROM {self.table}
            {filter_clause}
            {order_clause}
            {limit_clause}
        """)
        try:
            response = self.client.query(
                query, {"table": self.table, "user": RecordID(self.users_table, user_id or "")}
            )
            logger.debug(f"Read memories: {response}. Query: {query}")
        except Exception as e:
            logger.error(f"Error reading memories: {e}")
            raise e
        if isinstance(response, list):
            memories: List[MemoryRow] = []
            for row in response:
                memory_rec_id = row.get("id")
                user_rec_id = row.get("user")
                assert isinstance(user_rec_id, RecordID)
                assert isinstance(memory_rec_id, RecordID)
                memories.append(MemoryRow(id=memory_rec_id.id, user_id=user_rec_id.id, memory=row.get("memory", {})))
            return memories
        else:
            raise ValueError(f"Unexpected response type: {type(response)}")

    def upsert_memory(self, memory: MemoryRow) -> None:
        """Upsert a memory into the table

        Args:
            memory: MemoryRow to upsert
        Returns:
            None
        """
        response = self.client.upsert(
            RecordID(self.table, memory.id),
            {"memory": memory.memory, "user": RecordID(self.users_table, memory.user_id)},
        )
        logger.debug(f"Upserted memory with id {memory.id}: {response}")

    def delete_memory(self, memory_id: str) -> None:
        """Delete a memory from the table

        Args:
            memory_id: ID of the memory to delete
        Returns:
            None
        """
        self.client.delete(RecordID(self.table, memory_id))

    def drop_table(self) -> None:
        """Drop the table

        Returns:
            None
        """
        self.client.query(f"REMOVE TABLE IF EXISTS {self.table}")

    def table_exists(self) -> bool:
        """Check if the table exists

        Returns:
            bool: True if the table exists, False otherwise
        """
        log_debug(f"Checking if table exists: {self.table}")
        response = self.client.query(self.INFO_DB_QUERY)
        if isinstance(response, dict) and "tables" in response:
            return self.table in response["tables"]
        else:
            logger.error(f"Unexpected response from SurrealDB: {response}")
        return False

    def clear(self) -> bool:
        """Clear the table

        Returns:
            bool: True if the table was cleared, False otherwise
        """
        response = self.client.delete(self.table)
        logger.debug(f"Cleared table {self.table}: {response}")
        return False
