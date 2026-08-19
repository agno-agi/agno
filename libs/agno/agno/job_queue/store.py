"""In-memory job queue store.

Implements the same contract as the Postgres queue methods (enqueue_job,
claim_job, heartbeat_jobs, complete_job, retry_or_fail_job,
cancel_job, continue_job, sweep_exhausted_jobs, acquire_sweep,
settle_swept_job, get_job, count_queued_jobs) against process memory.

This is the contract-test fixture and the single-process dev fallback - it is
NOT durable (a restart loses the queue) and is never a substitute for the
DB-backed store in production. One instance per process.
"""

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple, Union


class InMemoryQueueStore:
    """Process-local job queue store with the DB adapters' queue contract."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def enqueue_job(self, job: Dict[str, Any], max_depth: int = 0) -> Dict[str, Any]:
        async with self._lock:
            # Same dedup semantics as the production stores: empty means no
            # key, and the namespace is scoped per user (cross-tenant key
            # reuse must not attach to another tenant's job). The STORED
            # value normalizes too (Postgres parity: the column reads NULL,
            # never '') so get_job consumers need no per-store knowledge.
            if not job.get("idempotency_key"):
                job = {**job, "idempotency_key": None}
            key = job.get("idempotency_key")
            if key is not None:
                user = job.get("user_id")
                for existing in self._jobs.values():
                    if existing.get("idempotency_key") == key and existing.get("user_id") == user:
                        return {"accepted": False, "reason": "duplicate", "job": dict(existing)}
            if max_depth and max_depth > 0:
                queued = sum(1 for j in self._jobs.values() if j["status"] == "queued")
                if queued >= max_depth:
                    return {"accepted": False, "reason": "queue_full", "job": None}
            # Mirror Postgres, where id is the primary key: a collision is a
            # programming error (ids are server-minted uuid4), never a client
            # dedup. Silently overwriting would reset a live ticket to
            # queued/attempt-0 - two executors, the first one's completion
            # fenced out.
            if job["id"] in self._jobs:
                raise RuntimeError(f"enqueue_job: job {job['id']} already exists; ids are never reused")
            self._jobs[job["id"]] = dict(job)
            return {"accepted": True, "reason": None, "job": dict(job)}

    async def claim_job(
        self, worker_id: str, lock_grace_seconds: int = 60, deployment_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        # Affinity filters BOTH branches - fresh claims and stale reclaims -
        # because a reclaim executes too. deployment_id=None degenerates to
        # claiming only unstamped jobs (mixed fleets safe by construction).
        async with self._lock:
            now = int(time.time())
            stale = now - lock_grace_seconds
            candidates = [
                j
                for j in self._jobs.values()
                if j["available_at"] <= now
                and (j.get("deployment_id") is None or j.get("deployment_id") == deployment_id)
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

    async def settle_paused_job(self, job_id: str, status: str, error: Optional[str] = None) -> bool:
        """Terminalize a PAUSED ticket whose continue ran INLINE, outside the
        queue: the run reached a terminal state but no worker owns the ticket,
        and paused tickets are retention-exempt - without this /queue said
        paused forever and the rows accumulated unboundedly. CAS on
        status='paused': a queued/claimed continuation owns the ticket and is
        never clobbered (its own terminal write settles it)."""
        if status not in ("completed", "cancelled", "failed"):
            return False
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job["status"] != "paused":
                return False
            now = int(time.time())
            job.update(status=status, error=error, locked_by=None, locked_at=None, completed_at=now, updated_at=now)
            return True

    async def cancel_job(self, job_id: str) -> bool:
        # Paused counts as "still waiting": nothing is executing a paused
        # ticket, so the tombstone contract ("this job will not execute")
        # applies the same way. Without it, cancelling a paused run was a
        # half-cancel - intent registered, ticket paused forever, and a later
        # continue would resurrect a run the user cancelled.
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job["status"] not in ("queued", "paused"):
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

    async def acquire_sweep(self, job_id: str, worker_id: str, lock_grace_seconds: int = 60) -> bool:
        """Take ownership of a stale, budget-exhausted running job BEFORE any
        run-row write. The sweep must never touch a run row whose ticket it
        does not own: the old order wrote the row first and only then
        discovered - via the swept-settle's staleness recheck - that a live
        heartbeat owned the ticket, after already defacing a healthy run's
        row. Refreshing locked_at here also doubles as the retry backoff for
        a failing terminalization: the job becomes re-sweepable once the
        sweeper's own lock goes stale."""
        async with self._lock:
            now = int(time.time())
            stale = now - lock_grace_seconds
            job = self._jobs.get(job_id)
            if (
                job is None
                or job["status"] != "running"
                or job.get("locked_at") is None
                or job["locked_at"] > stale
                or job["attempt"] < job["max_attempts"]
            ):
                return False
            job.update(locked_by=worker_id, locked_at=now, updated_at=now)
            return True

    async def settle_swept_job(self, job_id: str, worker_id: str, status: str, error: Optional[str] = None) -> bool:
        """Ownership-keyed settle for the SWEEPER: only the holder of the
        sweep lock (via acquire_sweep) may write. The target status matches
        what the run row actually says instead of always "failed" - the
        sweep RECONCILES, it does not deface: a falsely-swept leg may have
        completed, cancelled, or paused before the sweeper looked, and its
        ticket must record that, not contradict it."""
        if status not in ("completed", "cancelled", "paused", "failed"):
            return False
        async with self._lock:
            now = int(time.time())
            job = self._jobs.get(job_id)
            if job is None or job["status"] != "running" or job.get("locked_by") != worker_id:
                return False
            job.update(status=status, error=error, locked_by=None, locked_at=None, completed_at=now, updated_at=now)
            return True

    async def get_job(self, job_id: str, strict: bool = False) -> Optional[Dict[str, Any]]:
        """Look up a ticket. With strict=True, store failures PROPAGATE
        instead of reading as None - None means exactly "no such ticket".
        Fail-closed consumers (the continue-ownership gate) need the
        distinction: during a store outage, "no ticket" must not be
        inferred from "could not look" - that inference reopens the
        cross-door double-execution race the gate exists to close.
        In-memory cannot fail, so both modes behave identically."""
        async with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job is not None else None

    async def count_queued_jobs(self) -> int:
        async with self._lock:
            return sum(1 for j in self._jobs.values() if j["status"] == "queued")

    # -- Operations surface (DLQ, requeue, stats, retention) ---------------

    async def list_jobs(
        self,
        status: Optional[Union[str, List[str]]] = None,
        limit: int = 20,
        page: int = 1,
        sort_by: Optional[str] = "created_at",
        sort_order: Optional[str] = "desc",
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Paginated job listing: (page of jobs, total matching count).

        status accepts one value or a list (match any). An unknown sort_by is
        silently ignored (the list-API convention); None-valued sort fields
        group together rather than erroring. Sorting by updated_at falls back
        to created_at when updated_at is None, matching the DB adapters."""
        statuses = [status] if isinstance(status, str) else status
        async with self._lock:
            jobs = [dict(j) for j in self._jobs.values() if statuses is None or j["status"] in statuses]
        total_count = len(jobs)
        if sort_by and jobs and sort_by in jobs[0]:

            def sort_value(job: Dict[str, Any]) -> Any:
                value = job.get(sort_by)
                if value is None and sort_by == "updated_at":
                    value = job.get("created_at")
                return value

            jobs.sort(
                key=lambda j: (sort_value(j) is None, sort_value(j)),
                reverse=(sort_order != "asc"),
            )
        start = max(page - 1, 0) * limit
        return jobs[start : start + limit], total_count

    async def requeue_job(self, job_id: str) -> bool:
        """Operator requeue for a terminally failed/cancelled job: grants
        exactly one more execution by raising max_attempts to attempt + 1."""
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job["status"] not in ("failed", "cancelled"):
                return False
            now = int(time.time())
            job.update(
                status="queued",
                max_attempts=job["attempt"] + 1,
                available_at=now,
                locked_by=None,
                locked_at=None,
                completed_at=None,
                updated_at=now,
            )
            return True

    async def continue_job(self, job_id: str, continue_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Continuation CAS: flip the EXISTING paused ticket back to queued,
        mirroring requeue_job's transition. No new rows, ever - id == run_id
        is load-bearing. The ticket's submit-time payload fields are kept and
        payload["continue"] is REPLACED WHOLESALE with this continue's inputs
        (never accumulated across pause cycles). Budget grant: exactly one
        more execution (max_attempts = attempt + 1), regardless of the
        configured retry budget - a continuation is user-triggered and must
        never silently re-run.

        Returns {"outcome": "queued" | "attach" | "conflict", "job": row}:
        - queued: the CAS won; the merged row is returned.
        - attach: the ticket is already queued/running (double-click
          idempotency, free from the CAS) - the caller attaches to it; this
          click's inputs are discarded.
        - conflict: terminal ticket or no ticket; job is the row or None.
        """
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job["status"] in ("completed", "failed", "cancelled"):
                return {"outcome": "conflict", "job": dict(job) if job is not None else None}
            if job["status"] in ("queued", "running"):
                return {"outcome": "attach", "job": dict(job)}
            now = int(time.time())
            payload = dict(job.get("payload") or {})
            payload["continue"] = dict(continue_payload)
            job.update(
                status="queued",
                payload=payload,
                max_attempts=job["attempt"] + 1,
                available_at=now,
                locked_by=None,
                locked_at=None,
                completed_at=None,
                updated_at=now,
            )
            return {"outcome": "queued", "job": dict(job)}

    async def queue_stats(self) -> Dict[str, Any]:
        async with self._lock:
            now = int(time.time())
            counts: Dict[str, int] = {}
            oldest_queued: Optional[int] = None
            for job in self._jobs.values():
                counts[job["status"]] = counts.get(job["status"], 0) + 1
                if job["status"] == "queued":
                    age = now - job["created_at"]
                    oldest_queued = age if oldest_queued is None else max(oldest_queued, age)
            return {"counts": counts, "oldest_queued_age_seconds": oldest_queued}

    async def cleanup_jobs(self, older_than_seconds: int = 86400) -> int:
        """Delete terminal jobs whose completed_at is older than the retention
        window. Returns the number of rows removed. Paused tickets are
        deliberately EXEMPT: they must outlive arbitrary human latency to stay
        continuable; cancelling the run is the remedy for abandoned ones."""
        async with self._lock:
            cutoff = int(time.time()) - older_than_seconds
            to_delete = [
                jid
                for jid, j in self._jobs.items()
                if j["status"] in ("completed", "failed", "cancelled")
                and j.get("completed_at") is not None
                and j["completed_at"] <= cutoff
            ]
            for jid in to_delete:
                del self._jobs[jid]
            return len(to_delete)
