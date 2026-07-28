"""In-memory job queue store.

Implements the same contract as the Postgres run-queue methods (enqueue_job,
claim_job, heartbeat_jobs, complete_job, retry_or_fail_job,
cancel_job, sweep_exhausted_jobs, fail_swept_job, get_job,
count_queued_jobs) against process memory.

This is the contract-test fixture and the single-process dev fallback - it is
NOT durable (a restart loses the queue) and is never a substitute for the
DB-backed store in production. One instance per process.
"""

import asyncio
import time
from typing import Any, Dict, List, Optional


class InMemoryQueueStore:
    """Process-local job queue store with the DB adapters' queue contract."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def enqueue_job(self, job: Dict[str, Any], max_depth: int = 0) -> Dict[str, Any]:
        async with self._lock:
            key = job.get("idempotency_key")
            if key is not None:
                for existing in self._jobs.values():
                    if existing.get("idempotency_key") == key:
                        return {"accepted": False, "reason": "duplicate", "job": dict(existing)}
            if max_depth and max_depth > 0:
                queued = sum(1 for j in self._jobs.values() if j["status"] == "queued")
                if queued >= max_depth:
                    return {"accepted": False, "reason": "queue_full", "job": None}
            self._jobs[job["id"]] = dict(job)
            return {"accepted": True, "reason": None, "job": dict(job)}

    async def claim_job(self, worker_id: str, lock_grace_seconds: int = 60) -> Optional[Dict[str, Any]]:
        async with self._lock:
            now = int(time.time())
            stale = now - lock_grace_seconds
            candidates = [
                j
                for j in self._jobs.values()
                if j["available_at"] <= now
                and (
                    j["status"] == "queued"
                    or (
                        j["status"] == "running"
                        and j.get("locked_at") is not None
                        and j["locked_at"] <= stale
                        and j["attempt"] < j["max_attempts"]
                    )
                )
            ]
            if not candidates:
                return None
            job = min(candidates, key=lambda j: j["created_at"])
            job.update(
                status="running",
                locked_by=worker_id,
                locked_at=now,
                attempt=job["attempt"] + 1,
                updated_at=now,
            )
            return dict(job)

    async def heartbeat_jobs(self, worker_id: str, job_ids: List[str]) -> int:
        async with self._lock:
            now = int(time.time())
            count = 0
            for job_id in job_ids:
                job = self._jobs.get(job_id)
                if job is not None and job.get("locked_by") == worker_id and job["status"] == "running":
                    job["locked_at"] = now
                    count += 1
            return count

    async def complete_job(
        self, job_id: str, worker_id: str, attempt: int, status: str, error: Optional[str] = None
    ) -> bool:
        async with self._lock:
            job = self._jobs.get(job_id)
            if (
                job is None
                or job.get("locked_by") != worker_id
                or job["attempt"] != attempt
                or job["status"] != "running"
            ):
                return False
            now = int(time.time())
            job.update(status=status, error=error, locked_by=None, locked_at=None, completed_at=now, updated_at=now)
            return True

    async def retry_or_fail_job(
        self, job_id: str, worker_id: str, attempt: int, error: str, retry_delay_seconds: int = 30
    ) -> Optional[str]:
        async with self._lock:
            job = self._jobs.get(job_id)
            if (
                job is None
                or job.get("locked_by") != worker_id
                or job["attempt"] != attempt
                or job["status"] != "running"
            ):
                return None
            now = int(time.time())
            if job["attempt"] < job["max_attempts"]:
                job.update(
                    status="queued",
                    error=error,
                    locked_by=None,
                    locked_at=None,
                    available_at=now + retry_delay_seconds,
                    updated_at=now,
                )
                return "queued"
            job.update(status="failed", error=error, locked_by=None, locked_at=None, completed_at=now, updated_at=now)
            return "failed"

    async def cancel_job(self, job_id: str) -> bool:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job["status"] != "queued":
                return False
            now = int(time.time())
            job.update(status="cancelled", completed_at=now, updated_at=now)
            return True

    async def sweep_exhausted_jobs(self, lock_grace_seconds: int = 60, limit: int = 20) -> List[Dict[str, Any]]:
        async with self._lock:
            stale = int(time.time()) - lock_grace_seconds
            exhausted = [
                dict(j)
                for j in self._jobs.values()
                if j["status"] == "running"
                and j.get("locked_at") is not None
                and j["locked_at"] <= stale
                and j["attempt"] >= j["max_attempts"]
            ]
            exhausted.sort(key=lambda j: j["locked_at"])
            return exhausted[:limit]

    async def fail_swept_job(self, job_id: str, lock_grace_seconds: int = 60, error: str = "worker lost") -> bool:
        async with self._lock:
            now = int(time.time())
            stale = now - lock_grace_seconds
            job = self._jobs.get(job_id)
            if job is None or job["status"] != "running" or job.get("locked_at") is None or job["locked_at"] > stale:
                return False
            job.update(status="failed", error=error, locked_by=None, locked_at=None, completed_at=now, updated_at=now)
            return True

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job is not None else None

    async def count_queued_jobs(self) -> int:
        async with self._lock:
            return sum(1 for j in self._jobs.values() if j["status"] == "queued")
