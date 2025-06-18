import json
import time
from typing import Any, Dict, List, Optional

try:
    from redis import ConnectionError, Redis
except ImportError:
    raise ImportError("`redis` not installed. Please install it using `pip install redis`")

from agno.memory.v2.db.base import MemoryDb
from agno.memory.v2.db.schema import MemoryRow
from agno.utils.log import log_debug, log_info, logger


class RedisMemoryDb(MemoryDb):
    def __init__(
        self,
        prefix: str = "agno_memory",
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        expire: Optional[int] = None,
    ):
        """
        Initialize Redis memory store.

        Args:
            prefix (str): Prefix for Redis keys to namespace the memories
            host (str): Redis host address
            port (int): Redis port number
            db (int): Redis database number
            password (Optional[str]): Redis password if authentication is required
            expire (Optional[int]): TTL (time to live) in seconds for Redis keys. None means no expiration.
        """
        self.prefix = prefix
        self.expire = expire
        self.redis_client = Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=True,  # Automatically decode responses to str
        )
        log_debug(f"Created RedisMemoryDb with prefix: '{self.prefix}'")

    def __dict__(self) -> Dict[str, Any]:
        return {
            "name": "RedisMemoryDb",
            "prefix": self.prefix,
            "expire": self.expire,
        }

    def _get_key(self, memory_id: str) -> str:
        """Generate Redis key for a memory."""
        return f"{self.prefix}:{memory_id}"

    def create(self) -> None:
        """
        Test connection to Redis.
        For Redis, we don't need to create schema as it's schema-less.
        """
        try:
            self.redis_client.ping()
            log_debug("Redis connection successful")
        except ConnectionError as e:
            logger.error(f"Could not connect to Redis: {e}")
            raise

    def memory_exists(self, memory: MemoryRow) -> bool:
        """Check if a memory exists"""
        try:
            key = self._get_key(memory.id)  # type: ignore
            return self.redis_client.exists(key) > 0  # type: ignore
        except Exception as e:
            logger.error(f"Error checking memory existence: {e}")
            return False

    def read_memories(
        self, user_id: Optional[str] = None, limit: Optional[int] = None, sort: Optional[str] = None
    ) -> List[MemoryRow]:
        """Read memories from Redis"""
        memories: List[MemoryRow] = []
        try:
            # Get all keys matching the prefix pattern
            pattern = f"{self.prefix}:*"
            memory_data = []

            # Collect all matching memories
            for key in self.redis_client.scan_iter(match=pattern):
                data_str = self.redis_client.get(key)
                if data_str:
                    data = json.loads(data_str)  # type: ignore

                    # Filter by user_id if specified
                    if user_id is None or data.get("user_id") == user_id:
                        memory_data.append(data)

            # Sort by created_at timestamp
            if sort == "asc":
                memory_data.sort(key=lambda x: x.get("created_at", 0))
            else:
                memory_data.sort(key=lambda x: x.get("created_at", 0), reverse=True)

            # Apply limit if specified
            if limit is not None and limit > 0:
                memory_data = memory_data[:limit]

            # Convert to MemoryRow objects
            for data in memory_data:
                memories.append(MemoryRow.model_validate(data))

        except Exception as e:
            logger.error(f"Error reading memories: {e}")

        return memories

    def upsert_memory(self, memory: MemoryRow) -> Optional[MemoryRow]:
        """Upsert a memory in Redis"""
        try:
            # Prepare data
            timestamp = int(time.time())

            # Convert to dict and handle datetime objects
            memory_data = memory.model_dump(mode="json")

            # Add timestamps if not present
            if "created_at" not in memory_data:
                memory_data["created_at"] = timestamp

            memory_data["updated_at"] = timestamp

            # Save to Redis
            key = self._get_key(memory.id)  # type: ignore
            if self.expire is not None:
                self.redis_client.set(key, json.dumps(memory_data), ex=self.expire)
            else:
                self.redis_client.set(key, json.dumps(memory_data))

            return memory

        except Exception as e:
            logger.error(f"Error upserting memory: {e}")
            return None

    def delete_memory(self, memory_id: str) -> None:
        """Delete a memory from Redis"""
        try:
            key = self._get_key(memory_id)
            self.redis_client.delete(key)
            log_debug(f"Deleted memory: {memory_id}")
        except Exception as e:
            logger.error(f"Error deleting memory: {e}")

    def drop_table(self) -> None:
        """Drop all memories from Redis (same as clear)"""
        self.clear()

    def table_exists(self) -> bool:
        """Check if any memories exist with our prefix"""
        try:
            pattern = f"{self.prefix}:*"
            # Use scan_iter with count=1 to efficiently check if any keys exist
            for _ in self.redis_client.scan_iter(match=pattern, count=1):
                return True
            return False
        except Exception as e:
            logger.error(f"Error checking if table exists: {e}")
            return False

    def clear(self) -> bool:
        """Clear all memories with our prefix"""
        try:
            pattern = f"{self.prefix}:*"
            keys_to_delete = list(self.redis_client.scan_iter(match=pattern))

            if keys_to_delete:
                self.redis_client.delete(*keys_to_delete)
                log_info(f"Cleared {len(keys_to_delete)} memories with prefix: {self.prefix}")

            return True
        except Exception as e:
            logger.error(f"Error clearing memories: {e}")
            return False
