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

    def _get_children_key(self, parent_run_id: str) -> str:
        """Get the Redis key for a parent's child run set."""
        return f"{self.key_prefix}children:{parent_run_id}"

    def _get_parent_key(self, child_run_id: str) -> str:
        """Get the Redis key for a child's parent run."""
        return f"{self.key_prefix}parent:{child_run_id}"

    def _is_relationship_key(self, key: str) -> bool:
        """Check whether a Redis key stores cancellation relationship metadata."""
        return key.startswith(f"{self.key_prefix}children:") or key.startswith(f"{self.key_prefix}parent:")

    def _set_cancelled(self, client: Union[Redis, RedisCluster], run_id: str) -> None:
        key = self._get_key(run_id)
        if self.ttl_seconds and self.ttl_seconds > 0:
            client.set(key, "1", ex=self.ttl_seconds)
        else:
            client.set(key, "1")

    async def _aset_cancelled(self, client: Union[AsyncRedis, AsyncRedisCluster], run_id: str) -> None:
        key = self._get_key(run_id)
        if self.ttl_seconds and self.ttl_seconds > 0:
            await client.set(key, "1", ex=self.ttl_seconds)
        else:
            await client.set(key, "1")

    def _expire_relationship_keys(self, client: Union[Redis, RedisCluster], *keys: str) -> None:
        if self.ttl_seconds and self.ttl_seconds > 0:
            for key in keys:
                client.expire(key, self.ttl_seconds)

    async def _aexpire_relationship_keys(self, client: Union[AsyncRedis, AsyncRedisCluster], *keys: str) -> None:
        if self.ttl_seconds and self.ttl_seconds > 0:
            for key in keys:
                await client.expire(key, self.ttl_seconds)

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

    def register_child_run(self, parent_run_id: str, child_run_id: str) -> None:
        """Track a child run and preserve already-stored parent cancellation intent."""
        client = self._ensure_sync_client()
        children_key = self._get_children_key(parent_run_id)
        parent_key = self._get_parent_key(child_run_id)

        client.sadd(children_key, child_run_id)
        client.set(parent_key, parent_run_id, ex=self.ttl_seconds)
        self._expire_relationship_keys(client, children_key, parent_key)
        if self.is_cancelled(parent_run_id):
            self._set_cancelled(client, child_run_id)
            self._cancel_children(client, child_run_id)

    async def aregister_child_run(self, parent_run_id: str, child_run_id: str) -> None:
        """Track a child run and preserve already-stored parent cancellation intent (async version)."""
        client = self._ensure_async_client()
        children_key = self._get_children_key(parent_run_id)
        parent_key = self._get_parent_key(child_run_id)

        await client.sadd(children_key, child_run_id)
        await client.set(parent_key, parent_run_id, ex=self.ttl_seconds)
        await self._aexpire_relationship_keys(client, children_key, parent_key)
        if await self.ais_cancelled(parent_run_id):
            await self._aset_cancelled(client, child_run_id)
            await self._acancel_children(client, child_run_id)

    def _cancel_via_pipeline(self, client: Union[Redis, RedisCluster], key: str) -> bool:
        """Cancel a run atomically using a pipeline: EXISTS + SET (+ EXPIRE).

        Returns True if the key already existed (run was registered).
        """
        pipe = client.pipeline()
        pipe.exists(key)
        if self.ttl_seconds and self.ttl_seconds > 0:
            pipe.set(key, "1", ex=self.ttl_seconds)
        else:
            pipe.set(key, "1")
        results = pipe.execute()
        return bool(results[0])

    async def _acancel_via_pipeline(self, client: Union[AsyncRedis, AsyncRedisCluster], key: str) -> bool:
        """Cancel a run atomically using an async pipeline: EXISTS + SET (+ EXPIRE).

        Returns True if the key already existed (run was registered).
        """
        pipe = client.pipeline()
        pipe.exists(key)
        if self.ttl_seconds and self.ttl_seconds > 0:
            pipe.set(key, "1", ex=self.ttl_seconds)
        else:
            pipe.set(key, "1")
        results = await pipe.execute()
        return bool(results[0])

    def _cancel_children(self, client: Union[Redis, RedisCluster], run_id: str, visited: Optional[set] = None) -> None:
        """Mark all currently-known descendants as cancelled."""
        if visited is None:
            visited = set()
        if run_id in visited:
            return
        visited.add(run_id)
        child_run_ids = client.smembers(self._get_children_key(run_id))
        for child_run_id in child_run_ids:
            if isinstance(child_run_id, bytes):
                child_run_id = child_run_id.decode("utf-8")
            self._set_cancelled(client, child_run_id)
            self._cancel_children(client, child_run_id, visited)

    async def _acancel_children(
        self, client: Union[AsyncRedis, AsyncRedisCluster], run_id: str, visited: Optional[set] = None
    ) -> None:
        """Mark all currently-known descendants as cancelled (async version)."""
        if visited is None:
            visited = set()
        if run_id in visited:
            return
        visited.add(run_id)
        child_run_ids = await client.smembers(self._get_children_key(run_id))
        for child_run_id in child_run_ids:
            if isinstance(child_run_id, bytes):
                child_run_id = child_run_id.decode("utf-8")
            await self._aset_cancelled(client, child_run_id)
            await self._acancel_children(client, child_run_id, visited)

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

        was_registered = self._cancel_via_pipeline(client, key)
        self._cancel_children(client, run_id)

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

        was_registered = await self._acancel_via_pipeline(client, key)
        await self._acancel_children(client, run_id)

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
        parent_key = self._get_parent_key(run_id)
        parent_run_id = client.get(parent_key)
        if isinstance(parent_run_id, bytes):
            parent_run_id = parent_run_id.decode("utf-8")
        if parent_run_id:
            client.srem(self._get_children_key(parent_run_id), run_id)
        child_run_ids = client.smembers(self._get_children_key(run_id))
        for child_run_id in child_run_ids:
            if isinstance(child_run_id, bytes):
                child_run_id = child_run_id.decode("utf-8")
            client.delete(self._get_parent_key(child_run_id))
        client.delete(key)
        client.delete(parent_key)
        client.delete(self._get_children_key(run_id))

    async def acleanup_run(self, run_id: str) -> None:
        """Remove a run from tracking (called when run completes) (async version)."""
        client = self._ensure_async_client()
        key = self._get_key(run_id)
        parent_key = self._get_parent_key(run_id)
        parent_run_id = await client.get(parent_key)
        if isinstance(parent_run_id, bytes):
            parent_run_id = parent_run_id.decode("utf-8")
        if parent_run_id:
            await client.srem(self._get_children_key(parent_run_id), run_id)
        child_run_ids = await client.smembers(self._get_children_key(run_id))
        for child_run_id in child_run_ids:
            if isinstance(child_run_id, bytes):
                child_run_id = child_run_id.decode("utf-8")
            await client.delete(self._get_parent_key(child_run_id))
        await client.delete(key)
        await client.delete(parent_key)
        await client.delete(self._get_children_key(run_id))

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
            if self._is_relationship_key(key):
                continue
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
            if self._is_relationship_key(key):
                continue
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
