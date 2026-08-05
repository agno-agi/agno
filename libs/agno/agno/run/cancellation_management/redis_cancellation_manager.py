"""Redis-based run cancellation management."""

from typing import TYPE_CHECKING, Any, Dict, Iterable, Optional, Set, Union

from agno.exceptions import RunCancelledException
from agno.run.cancellation_management.base import BaseRunCancellationManager
from agno.utils.log import log_warning, logger

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

    def _get_members_key(self, team_run_id: str) -> str:
        """Get the Redis key for a team run's member set."""
        return f"{self.key_prefix}members:{team_run_id}"

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
        # Fail-open: registration is best-effort coordination - a Redis fault
        # at the top of every run must not raise into execution
        try:
            client = self._ensure_sync_client()
        except Exception as e:
            log_warning(f"Cancellation registration unavailable (Redis fault, failing open): {e}")
            return
        key = self._get_key(run_id)
        try:
            # NX: only set if key does not exist, preserving cancel-before-start intent
            client.set(key, "0", ex=self.ttl_seconds, nx=True)
        except Exception as e:
            log_warning(f"Cancellation registration unavailable (Redis fault, failing open): {e}")

    async def aregister_run(self, run_id: str) -> None:
        """Register a new run as not cancelled (async version).

        Uses NX flag to preserve any existing cancellation intent
        (cancel-before-start support for background runs).
        """
        # Fail-open: registration is best-effort coordination - a Redis fault
        # at the top of every run must not raise into execution
        try:
            client = self._ensure_async_client()
        except Exception as e:
            log_warning(f"Cancellation registration unavailable (Redis fault, failing open): {e}")
            return
        key = self._get_key(run_id)
        try:
            # NX: only set if key does not exist, preserving cancel-before-start intent
            await client.set(key, "0", ex=self.ttl_seconds, nx=True)
        except Exception as e:
            log_warning(f"Cancellation registration unavailable (Redis fault, failing open): {e}")

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

        if was_registered:
            logger.info(f"Run {run_id} marked for cancellation")
        else:
            logger.info(f"Run {run_id} not yet registered, storing cancellation intent")
        return was_registered

    def is_cancelled(self, run_id: str) -> bool:
        """Check if a run is cancelled.

        FAIL-OPEN by contract: Redis is coordination, not truth. This check
        runs several times per run at safe points - a Redis restart, failover,
        timeout or pool exhaustion mid-run must degrade to "not cancelled"
        (the signal is re-checked at the next safe point), never propagate
        into the run and mark a healthy run ERROR."""
        try:
            client = self._ensure_sync_client()
            value = client.get(self._get_key(run_id))
        except Exception as e:
            log_warning(f"Cancellation check unavailable (Redis fault, failing open): {e}")
            return False
        if value is None:
            return False
        # Redis returns bytes, handle both bytes and str
        if isinstance(value, bytes):
            return value == b"1"
        return value == "1"

    async def ais_cancelled(self, run_id: str) -> bool:
        """Check if a run is cancelled (async version). Fail-open: see
        is_cancelled."""
        try:
            client = self._ensure_async_client()
            value = await client.get(self._get_key(run_id))
        except Exception as e:
            log_warning(f"Cancellation check unavailable (Redis fault, failing open): {e}")
            return False
        if value is None:
            return False
        # Redis returns bytes, handle both bytes and str
        if isinstance(value, bytes):
            return value == b"1"
        return value == "1"

    def cleanup_run(self, run_id: str) -> None:
        """Remove a run from tracking (called when run completes).

        FAIL-OPEN like is_cancelled: cleanup runs inside terminal paths
        (producers' finally blocks, continue/requeue seams) where a Redis
        blip must not fail the surrounding operation. Worst case a stale key
        lives until its TTL."""
        try:
            client = self._ensure_sync_client()
            client.delete(self._get_key(run_id))
        except Exception as e:
            log_warning(f"Cancellation cleanup unavailable (Redis fault, failing open): {e}")

    async def acleanup_run(self, run_id: str) -> None:
        """Remove a run from tracking (async version). Fail-open: see
        cleanup_run."""
        try:
            client = self._ensure_async_client()
            await client.delete(self._get_key(run_id))
        except Exception as e:
            log_warning(f"Cancellation cleanup unavailable (Redis fault, failing open): {e}")

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

            # Skip member-set keys: they hold Redis SETs (see _get_members_key),
            # not run-status strings, so a GET on them would raise WRONGTYPE.
            if run_id.startswith("members:"):
                continue

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

            # Skip member-set keys: they hold Redis SETs (see _get_members_key),
            # not run-status strings, so a GET on them would raise WRONGTYPE.
            if run_id.startswith("members:"):
                continue

            # Get value
            value = await client.get(key)
            if value is not None:
                if isinstance(value, bytes):
                    is_cancelled = value == b"1"
                else:
                    is_cancelled = value == "1"
                result[run_id] = is_cancelled

        return result

    def register_member_run(self, team_run_id: str, member_run_id: str) -> None:
        """Record that a member run belongs to a team run for cancel-cascade.

        FAIL-OPEN like every coordination write here: this is called from
        inside member-delegation tool execution, and a Redis blip must
        degrade the cancel-cascade (this member is missed by a later team
        cancel), never error a healthy team run mid-flight."""
        try:
            client = self._ensure_sync_client()
            key = self._get_members_key(team_run_id)
            pipe = client.pipeline()
            pipe.sadd(key, member_run_id)
            if self.ttl_seconds and self.ttl_seconds > 0:
                pipe.expire(key, self.ttl_seconds)
            pipe.execute()
        except Exception as e:
            log_warning(f"Member-run registration unavailable (Redis fault, failing open): {e}")

    async def aregister_member_run(self, team_run_id: str, member_run_id: str) -> None:
        """Record that a member run belongs to a team run for cancel-cascade
        (async version). Fail-open: see register_member_run."""
        try:
            client = self._ensure_async_client()
            key = self._get_members_key(team_run_id)
            pipe = client.pipeline()
            pipe.sadd(key, member_run_id)
            if self.ttl_seconds and self.ttl_seconds > 0:
                pipe.expire(key, self.ttl_seconds)
            await pipe.execute()
        except Exception as e:
            log_warning(f"Member-run registration unavailable (Redis fault, failing open): {e}")

    def _decode_members(self, members: Iterable[Any]) -> Set[str]:
        """Decode a Redis set response (bytes or str) into a Set[str]."""
        return {m.decode("utf-8") if isinstance(m, bytes) else m for m in members}

    def get_member_run_ids(self, team_run_id: str) -> Set[str]:
        """Return the in-flight member run_ids of a team run."""
        client = self._ensure_sync_client()
        pipe = client.pipeline()
        pipe.smembers(self._get_members_key(team_run_id))
        results = pipe.execute()
        return self._decode_members(results[0] or set())

    async def aget_member_run_ids(self, team_run_id: str) -> Set[str]:
        """Return the in-flight member run_ids of a team run (async version)."""
        client = self._ensure_async_client()
        pipe = client.pipeline()
        pipe.smembers(self._get_members_key(team_run_id))
        results = await pipe.execute()
        return self._decode_members(results[0] or set())

    def cleanup_member_runs(self, team_run_id: str) -> None:
        """Drop a team run's member mapping when the team run finishes.

        FAIL-OPEN: team finalize calls this right before the terminal save,
        and a Redis blip must not error out a run that already succeeded -
        an uncleaned mapping simply expires with its TTL."""
        try:
            client = self._ensure_sync_client()
            client.delete(self._get_members_key(team_run_id))
        except Exception as e:
            log_warning(f"Member-run cleanup unavailable (Redis fault, failing open): {e}")

    async def acleanup_member_runs(self, team_run_id: str) -> None:
        """Drop a team run's member mapping when the team run finishes
        (async version). Fail-open: see cleanup_member_runs."""
        try:
            client = self._ensure_async_client()
            await client.delete(self._get_members_key(team_run_id))
        except Exception as e:
            log_warning(f"Member-run cleanup unavailable (Redis fault, failing open): {e}")
