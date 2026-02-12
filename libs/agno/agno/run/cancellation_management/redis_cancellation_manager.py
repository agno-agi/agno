"""Redis-based run cancellation management."""

from typing import TYPE_CHECKING, Any, Dict, Optional, Union

from agno.exceptions import RunCancelledException
from agno.run.cancellation_management.base import BaseRunCancellationManager
from agno.utils.log import logger

# Defer import error until class instantiation
_redis_available = True
_redis_import_error: Optional[str] = None

try:
    from redis import Redis, RedisCluster
    from redis.asyncio import Redis as AsyncRedis
    from redis.asyncio import RedisCluster as AsyncRedisCluster
except ImportError:
    _redis_available = False
    _redis_import_error = "`redis` not installed. Please install it using `pip install redis`"
    # Type hints for when redis is not installed
    if TYPE_CHECKING:
        from redis import Redis, RedisCluster
        from redis.asyncio import Redis as AsyncRedis
        from redis.asyncio import RedisCluster as AsyncRedisCluster
    else:
        Redis = Any
        RedisCluster = Any
        AsyncRedis = Any
        AsyncRedisCluster = Any


class RedisRunCancellationManager(BaseRunCancellationManager):
    """Redis-based cancellation manager for distributed run cancellation.
    This manager stores run cancellation state in Redis, enabling cancellation
    across multiple processes or services.

    To use: call the set_cancellation_manager function to set the cancellation manager.
    Args:
        redis_client: Sync Redis client for sync methods. Can be Redis or RedisCluster.
        async_redis_client: Async Redis client for async methods. Can be AsyncRedis or AsyncRedisCluster.
        key_prefix: Prefix for Redis keys. Defaults to "agno:run:cancellation:".
        ttl_seconds: TTL for keys in seconds. Defaults to 86400 (1 day).
            Keys auto-expire to prevent orphaned keys if runs aren't cleaned up.
            Set to None to disable expiration.
    """

    DEFAULT_TTL_SECONDS = 60 * 60 * 24  # 1 day

    def __init__(
        self,
        redis_client: Optional[Union[Redis, RedisCluster]] = None,
        async_redis_client: Optional[Union[AsyncRedis, AsyncRedisCluster]] = None,
        key_prefix: str = "agno:run:cancellation:",
        ttl_seconds: Optional[int] = DEFAULT_TTL_SECONDS,
    ):
        if not _redis_available:
            raise ImportError(_redis_import_error)

        super().__init__()
        self.redis_client = redis_client
        self.async_redis_client = async_redis_client
        self.key_prefix = key_prefix
        self.ttl_seconds = ttl_seconds

        if redis_client is None and async_redis_client is None:
            raise ValueError("At least one of redis_client or async_redis_client must be provided")

    def _get_key(self, run_id: str) -> str:
        """Get the Redis key for a run ID."""
        return f"{self.key_prefix}{run_id}"

    def _ensure_sync_client(self) -> Union[Redis, RedisCluster]:
        """Ensure sync client is available."""
        if self.redis_client is None:
            raise RuntimeError("Sync Redis client not provided. Use async methods or provide a sync client.")
        return self.redis_client

    def _ensure_async_client(self) -> Union[AsyncRedis, AsyncRedisCluster]:
        """Ensure async client is available."""
        if self.async_redis_client is None:
            raise RuntimeError("Async Redis client not provided. Use sync methods or provide an async client.")
        return self.async_redis_client

    def register_run(self, run_id: str) -> None:
        """Register a new run as not cancelled.

        Uses NX flag to preserve any existing cancellation intent
        (cancel-before-start support for background runs).
        """
        client = self._ensure_sync_client()
        key = self._get_key(run_id)
        # NX: only set if key does not exist, preserving cancel-before-start intent
        client.set(key, "0", ex=self.ttl_seconds, nx=True)

    async def aregister_run(self, run_id: str) -> None:
        """Register a new run as not cancelled (async version).

        Uses NX flag to preserve any existing cancellation intent
        (cancel-before-start support for background runs).
        """
        client = self._ensure_async_client()
        key = self._get_key(run_id)
        # NX: only set if key does not exist, preserving cancel-before-start intent
        await client.set(key, "0", ex=self.ttl_seconds, nx=True)

    # Lua script for atomic cancel: checks existence then sets to "1" with optional TTL.
    # Returns 1 if the key already existed (run was registered), 0 otherwise.
    _CANCEL_LUA = """
local existed = redis.call('EXISTS', KEYS[1])
redis.call('SET', KEYS[1], '1')
local ttl = tonumber(ARGV[1])
if ttl and ttl > 0 then
    redis.call('EXPIRE', KEYS[1], ttl)
end
return existed
"""

    def cancel_run(self, run_id: str) -> bool:
        """Cancel a run by marking it as cancelled.

        Always stores cancellation intent, even for runs not yet registered
        (cancel-before-start support for background runs).

        Returns:
            bool: True if run was previously registered, False if storing
            cancellation intent for an unregistered run.
        """
        client = self._ensure_sync_client()
        key = self._get_key(run_id)

        # Atomic: check existence then set to "1" in a single round-trip
        was_registered = bool(client.eval(self._CANCEL_LUA, 1, key, self.ttl_seconds or 0))

        if was_registered:
            logger.info(f"Run {run_id} marked for cancellation")
        else:
            logger.info(f"Run {run_id} not yet registered, storing cancellation intent")
        return was_registered

    async def acancel_run(self, run_id: str) -> bool:
        """Cancel a run by marking it as cancelled (async version).

        Always stores cancellation intent, even for runs not yet registered
        (cancel-before-start support for background runs).

        Returns:
            bool: True if run was previously registered, False if storing
            cancellation intent for an unregistered run.
        """
        client = self._ensure_async_client()
        key = self._get_key(run_id)

        # Atomic: check existence then set to "1" in a single round-trip
        was_registered = bool(await client.eval(self._CANCEL_LUA, 1, key, self.ttl_seconds or 0))  # type: ignore[misc]

        if was_registered:
            logger.info(f"Run {run_id} marked for cancellation")
        else:
            logger.info(f"Run {run_id} not yet registered, storing cancellation intent")
        return was_registered

    def is_cancelled(self, run_id: str) -> bool:
        """Check if a run is cancelled."""
        client = self._ensure_sync_client()
        key = self._get_key(run_id)
        value = client.get(key)
        if value is None:
            return False
        # Redis returns bytes, handle both bytes and str
        if isinstance(value, bytes):
            return value == b"1"
        return value == "1"

    async def ais_cancelled(self, run_id: str) -> bool:
        """Check if a run is cancelled (async version)."""
        client = self._ensure_async_client()
        key = self._get_key(run_id)
        value = await client.get(key)
        if value is None:
            return False
        # Redis returns bytes, handle both bytes and str
        if isinstance(value, bytes):
            return value == b"1"
        return value == "1"

    def cleanup_run(self, run_id: str) -> None:
        """Remove a run from tracking (called when run completes)."""
        client = self._ensure_sync_client()
        key = self._get_key(run_id)
        client.delete(key)

    async def acleanup_run(self, run_id: str) -> None:
        """Remove a run from tracking (called when run completes) (async version)."""
        client = self._ensure_async_client()
        key = self._get_key(run_id)
        await client.delete(key)

    def raise_if_cancelled(self, run_id: str) -> None:
        """Check if a run should be cancelled and raise exception if so."""
        if self.is_cancelled(run_id):
            logger.info(f"Cancelling run {run_id}")
            raise RunCancelledException(f"Run {run_id} was cancelled")

    async def araise_if_cancelled(self, run_id: str) -> None:
        """Check if a run should be cancelled and raise exception if so (async version)."""
        if await self.ais_cancelled(run_id):
            logger.info(f"Cancelling run {run_id}")
            raise RunCancelledException(f"Run {run_id} was cancelled")

    def get_active_runs(self) -> Dict[str, bool]:
        """Get all currently tracked runs and their cancellation status.

        Note: Uses scan_iter which works correctly with both standalone Redis
        and Redis Cluster (scans all nodes in cluster mode).
        """
        client = self._ensure_sync_client()
        result: Dict[str, bool] = {}

        # scan_iter handles cluster mode correctly (scans all nodes)
        pattern = f"{self.key_prefix}*"
        for key in client.scan_iter(match=pattern, count=100):
            # Extract run_id from key
            if isinstance(key, bytes):
                key = key.decode("utf-8")
            run_id = key[len(self.key_prefix) :]

            # Get value
            value = client.get(key)
            if value is not None:
                if isinstance(value, bytes):
                    is_cancelled = value == b"1"
                else:
                    is_cancelled = value == "1"
                result[run_id] = is_cancelled

        return result

    async def aget_active_runs(self) -> Dict[str, bool]:
        """Get all currently tracked runs and their cancellation status (async version).

        Note: Uses scan_iter which works correctly with both standalone Redis
        and Redis Cluster (scans all nodes in cluster mode).
        """
        client = self._ensure_async_client()
        result: Dict[str, bool] = {}

        # scan_iter handles cluster mode correctly (scans all nodes)
        pattern = f"{self.key_prefix}*"
        async for key in client.scan_iter(match=pattern, count=100):
            # Extract run_id from key
            if isinstance(key, bytes):
                key = key.decode("utf-8")
            run_id = key[len(self.key_prefix) :]

            # Get value
            value = await client.get(key)
            if value is not None:
                if isinstance(value, bytes):
                    is_cancelled = value == b"1"
                else:
                    is_cancelled = value == "1"
                result[run_id] = is_cancelled

        return result
