"""Redis-backed run queue store.

Implements the run-queue contract (see ``InMemoryRunQueueStore`` and the
Postgres adapter methods) on Redis, so the durable queue can live on a
dedicated Redis instead of the primary database:

    AgentOS(run_queue=RunQueueConfig(durable=True, db=RedisRunQueueStore(async_redis)))

Layout (all keys under ``key_prefix``):
- ``job:{id}``   - the job as one JSON document (single-key CAS target)
- ``queued``     - zset job_id scored by available_at (claim order)
- ``running``    - zset job_id scored by locked_at (stale scan / sweep)
- ``all``        - zset job_id scored by created_at (listing / retention)
- ``idem:{key}`` - idempotency key -> job_id, with a TTL

Atomicity: claims and fenced writes use optimistic WATCH/MULTI on the job key
(the SKIP LOCKED equivalent - a raced claim retries the next candidate).

Durability caveat (documented trade-off): Redis acceptance durability depends
on persistence configuration. Use AOF (appendfsync everysec or always) to
approach Postgres-grade "no accepted request is ever lost"; with default RDB
snapshotting a crash can lose recently accepted jobs.
"""

import json
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

_redis_available = True
_redis_import_error: Optional[str] = None

try:
    from redis.asyncio import Redis as AsyncRedis
    from redis.asyncio import RedisCluster as AsyncRedisCluster
    from redis.exceptions import WatchError
except ImportError:
    _redis_available = False
    _redis_import_error = "`redis` not installed. Please install it using `pip install redis`"
    if TYPE_CHECKING:
        from redis.asyncio import Redis as AsyncRedis
        from redis.asyncio import RedisCluster as AsyncRedisCluster
    else:
        AsyncRedis = Any
        AsyncRedisCluster = Any
        WatchError = Exception

_TERMINAL = ("completed", "failed", "cancelled")

# How many candidates to inspect per claim pass before giving up (bounds work
# under contention; the next poll tick retries).
_CLAIM_SCAN_LIMIT = 8


class RedisRunQueueStore:
    """Run queue store on Redis (async client)."""

    def __init__(
        self,
        async_redis_client: "AsyncRedis",
        key_prefix: str = "agno:run_queue:",
        idempotency_ttl_seconds: int = 86400,
    ):
        if not _redis_available:
            raise ImportError(_redis_import_error)
        self._redis = async_redis_client
        self._prefix = key_prefix
        self._idem_ttl = idempotency_ttl_seconds

    # -- keys ---------------------------------------------------------------

    def _job_key(self, job_id: str) -> str:
        return f"{self._prefix}job:{job_id}"

    @property
    def _queued_key(self) -> str:
        return f"{self._prefix}queued"

    @property
    def _running_key(self) -> str:
        return f"{self._prefix}running"

    @property
    def _all_key(self) -> str:
        return f"{self._prefix}all"

    def _idem_key(self, key: str) -> str:
        return f"{self._prefix}idem:{key}"

    async def _load(self, job_id: str) -> Optional[Dict[str, Any]]:
        raw = await self._redis.get(self._job_key(job_id))
        if raw is None:
            return None
        return json.loads(raw if isinstance(raw, str) else raw.decode())

    # -- contract -----------------------------------------------------------

    async def enqueue_run_job(self, job: Dict[str, Any], max_depth: int = 0) -> Dict[str, Any]:
        idem = job.get("idempotency_key")
        if idem is not None:
            # SET NX is the atomic dedup gate
            claimed_key = await self._redis.set(self._idem_key(idem), job["id"], nx=True, ex=self._idem_ttl)
            if not claimed_key:
                existing_id = await self._redis.get(self._idem_key(idem))
                existing = (
                    await self._load(existing_id if isinstance(existing_id, str) else existing_id.decode())
                    if existing_id
                    else None
                )
                return {"accepted": False, "reason": "duplicate", "job": existing}

        if max_depth and max_depth > 0:
            queued = await self._redis.zcard(self._queued_key)
            if int(queued) >= max_depth:
                if idem is not None:
                    await self._redis.delete(self._idem_key(idem))
                return {"accepted": False, "reason": "queue_full", "job": None}

        pipe = self._redis.pipeline()
        pipe.set(self._job_key(job["id"]), json.dumps(job))
        pipe.zadd(self._queued_key, {job["id"]: job["available_at"]})
        pipe.zadd(self._all_key, {job["id"]: job["created_at"]})
        await pipe.execute()
        return {"accepted": True, "reason": None, "job": dict(job)}

    async def claim_run_job(self, worker_id: str, lock_grace_seconds: int = 60) -> Optional[Dict[str, Any]]:
        now = int(time.time())
        stale = now - lock_grace_seconds

        # 1) queued candidates, oldest available first
        queued_ids = await self._redis.zrangebyscore(self._queued_key, "-inf", now, start=0, num=_CLAIM_SCAN_LIMIT)
        for raw_id in queued_ids:
            job = await self._try_claim(_to_str(raw_id), worker_id, now, expect_status="queued")
            if job is not None:
                return job

        # 2) stale running reclaim, gated on the attempt budget
        stale_ids = await self._redis.zrangebyscore(self._running_key, "-inf", stale, start=0, num=_CLAIM_SCAN_LIMIT)
        for raw_id in stale_ids:
            job = await self._try_claim(_to_str(raw_id), worker_id, now, expect_status="running", stale_before=stale)
            if job is not None:
                return job
        return None

    async def _try_claim(
        self, job_id: str, worker_id: str, now: int, expect_status: str, stale_before: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Optimistic CAS claim on the job document; a raced claim returns None."""
        job_key = self._job_key(job_id)
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                await pipe.watch(job_key)
                raw = await pipe.get(job_key)
                if raw is None:
                    await pipe.unwatch()
                    return None
                job = json.loads(raw if isinstance(raw, str) else raw.decode())
                claimable = (
                    job["status"] == expect_status
                    and job["available_at"] <= now
                    and (
                        expect_status == "queued"
                        or (
                            job.get("locked_at") is not None
                            and stale_before is not None
                            and job["locked_at"] <= stale_before
                            and job["attempt"] < job["max_attempts"]
                        )
                    )
                )
                if not claimable:
                    await pipe.unwatch()
                    return None
                job.update(
                    status="running", locked_by=worker_id, locked_at=now, attempt=job["attempt"] + 1, updated_at=now
                )
                pipe.multi()
                pipe.set(job_key, json.dumps(job))
                pipe.zrem(self._queued_key, job_id)
                pipe.zadd(self._running_key, {job_id: now})
                await pipe.execute()
                return job
        except WatchError:
            return None

    async def _fenced_update(self, job_id: str, worker_id: str, attempt: int, mutate: Any) -> Optional[Dict[str, Any]]:
        """CAS update allowed only for the claim holder of this attempt."""
        job_key = self._job_key(job_id)
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                await pipe.watch(job_key)
                raw = await pipe.get(job_key)
                if raw is None:
                    await pipe.unwatch()
                    return None
                job = json.loads(raw if isinstance(raw, str) else raw.decode())
                if job.get("locked_by") != worker_id or job["attempt"] != attempt or job["status"] != "running":
                    await pipe.unwatch()
                    return None
                mutate(job)
                pipe.multi()
                pipe.set(job_key, json.dumps(job))
                pipe.zrem(self._running_key, job_id)
                if job["status"] == "queued":
                    pipe.zadd(self._queued_key, {job_id: job["available_at"]})
                await pipe.execute()
                return job
        except WatchError:
            return None

    async def heartbeat_run_jobs(self, worker_id: str, job_ids: List[str]) -> int:
        count = 0
        now = int(time.time())
        for job_id in job_ids:

            def _beat(job: Dict[str, Any]) -> None:
                job["locked_at"] = now

            updated = await self._fenced_update(job_id, worker_id, await self._attempt_of(job_id), _beat)
            if updated is not None:
                await self._redis.zadd(self._running_key, {job_id: now})
                count += 1
        return count

    async def _attempt_of(self, job_id: str) -> int:
        job = await self._load(job_id)
        return job["attempt"] if job is not None else -1

    async def complete_run_job(
        self, job_id: str, worker_id: str, attempt: int, status: str, error: Optional[str] = None
    ) -> bool:
        now = int(time.time())

        def _complete(job: Dict[str, Any]) -> None:
            job.update(status=status, error=error, locked_by=None, locked_at=None, completed_at=now, updated_at=now)

        return await self._fenced_update(job_id, worker_id, attempt, _complete) is not None

    async def retry_or_fail_run_job(
        self, job_id: str, worker_id: str, attempt: int, error: str, retry_delay_seconds: int = 30
    ) -> Optional[str]:
        now = int(time.time())
        outcome: Dict[str, str] = {}

        def _retry(job: Dict[str, Any]) -> None:
            if job["attempt"] < job["max_attempts"]:
                job.update(
                    status="queued",
                    error=error,
                    locked_by=None,
                    locked_at=None,
                    available_at=now + retry_delay_seconds,
                    updated_at=now,
                )
                outcome["status"] = "queued"
            else:
                job.update(
                    status="failed", error=error, locked_by=None, locked_at=None, completed_at=now, updated_at=now
                )
                outcome["status"] = "failed"

        updated = await self._fenced_update(job_id, worker_id, attempt, _retry)
        return outcome.get("status") if updated is not None else None

    async def cancel_run_job(self, job_id: str) -> bool:
        job_key = self._job_key(job_id)
        now = int(time.time())
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                await pipe.watch(job_key)
                raw = await pipe.get(job_key)
                if raw is None:
                    await pipe.unwatch()
                    return False
                job = json.loads(raw if isinstance(raw, str) else raw.decode())
                if job["status"] != "queued":
                    await pipe.unwatch()
                    return False
                job.update(status="cancelled", completed_at=now, updated_at=now)
                pipe.multi()
                pipe.set(job_key, json.dumps(job))
                pipe.zrem(self._queued_key, job_id)
                await pipe.execute()
                return True
        except WatchError:
            return False

    async def sweep_exhausted_run_jobs(self, lock_grace_seconds: int = 60, limit: int = 20) -> List[Dict[str, Any]]:
        stale = int(time.time()) - lock_grace_seconds
        stale_ids = await self._redis.zrangebyscore(self._running_key, "-inf", stale, start=0, num=limit * 2)
        exhausted: List[Dict[str, Any]] = []
        for raw_id in stale_ids:
            job = await self._load(_to_str(raw_id))
            if (
                job is not None
                and job["status"] == "running"
                and job.get("locked_at") is not None
                and job["locked_at"] <= stale
                and job["attempt"] >= job["max_attempts"]
            ):
                exhausted.append(job)
                if len(exhausted) >= limit:
                    break
        return exhausted

    async def fail_swept_run_job(self, job_id: str, lock_grace_seconds: int = 60, error: str = "worker lost") -> bool:
        job_key = self._job_key(job_id)
        now = int(time.time())
        stale = now - lock_grace_seconds
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                await pipe.watch(job_key)
                raw = await pipe.get(job_key)
                if raw is None:
                    await pipe.unwatch()
                    return False
                job = json.loads(raw if isinstance(raw, str) else raw.decode())
                # Re-check staleness inside the CAS: a live heartbeat wins
                if job["status"] != "running" or job.get("locked_at") is None or job["locked_at"] > stale:
                    await pipe.unwatch()
                    return False
                job.update(
                    status="failed", error=error, locked_by=None, locked_at=None, completed_at=now, updated_at=now
                )
                pipe.multi()
                pipe.set(job_key, json.dumps(job))
                pipe.zrem(self._running_key, job_id)
                await pipe.execute()
                return True
        except WatchError:
            return False

    async def get_run_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        return await self._load(job_id)

    async def count_queued_run_jobs(self) -> int:
        return int(await self._redis.zcard(self._queued_key))

    # -- Operations surface (DLQ, requeue, stats, retention) ---------------

    async def list_run_jobs(self, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        job_ids = await self._redis.zrevrange(self._all_key, 0, max(limit * 4, limit) - 1)
        jobs: List[Dict[str, Any]] = []
        for raw_id in job_ids:
            job = await self._load(_to_str(raw_id))
            if job is not None and (status is None or job["status"] == status):
                jobs.append(job)
                if len(jobs) >= limit:
                    break
        return jobs

    async def requeue_run_job(self, job_id: str) -> bool:
        """Operator requeue for a terminally failed/cancelled job: grants
        exactly one more execution by raising max_attempts to attempt + 1."""
        job_key = self._job_key(job_id)
        now = int(time.time())
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                await pipe.watch(job_key)
                raw = await pipe.get(job_key)
                if raw is None:
                    await pipe.unwatch()
                    return False
                job = json.loads(raw if isinstance(raw, str) else raw.decode())
                if job["status"] not in ("failed", "cancelled"):
                    await pipe.unwatch()
                    return False
                job.update(
                    status="queued",
                    max_attempts=job["attempt"] + 1,
                    available_at=now,
                    locked_by=None,
                    locked_at=None,
                    completed_at=None,
                    updated_at=now,
                )
                pipe.multi()
                pipe.set(job_key, json.dumps(job))
                pipe.zadd(self._queued_key, {job_id: now})
                await pipe.execute()
                return True
        except WatchError:
            return False

    async def run_queue_stats(self) -> Dict[str, Any]:
        now = int(time.time())
        job_ids = await self._redis.zrange(self._all_key, 0, -1)
        counts: Dict[str, int] = {}
        oldest_queued: Optional[int] = None
        for raw_id in job_ids:
            job = await self._load(_to_str(raw_id))
            if job is None:
                continue
            counts[job["status"]] = counts.get(job["status"], 0) + 1
            if job["status"] == "queued":
                age = now - job["created_at"]
                oldest_queued = age if oldest_queued is None else max(oldest_queued, age)
        return {"counts": counts, "oldest_queued_age_seconds": oldest_queued}

    async def cleanup_run_jobs(self, older_than_seconds: int = 86400) -> int:
        cutoff = int(time.time()) - older_than_seconds
        job_ids = await self._redis.zrange(self._all_key, 0, -1)
        removed = 0
        for raw_id in job_ids:
            job_id = _to_str(raw_id)
            job = await self._load(job_id)
            if (
                job is not None
                and job["status"] in _TERMINAL
                and job.get("completed_at") is not None
                and job["completed_at"] <= cutoff
            ):
                pipe = self._redis.pipeline()
                pipe.delete(self._job_key(job_id))
                pipe.zrem(self._all_key, job_id)
                pipe.zrem(self._queued_key, job_id)
                pipe.zrem(self._running_key, job_id)
                await pipe.execute()
                removed += 1
        return removed


def _to_str(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)
