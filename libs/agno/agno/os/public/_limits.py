"""Atomic PostgreSQL admission shared by every replica in a namespace."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Optional

from sqlalchemy import text

from agno.utils.bounded import BoundedWorkers, WorkBudget

WORKERS = BoundedWorkers(16, "public-admission")


@dataclass(frozen=True)
class RateLimit:
    client_per_minute: int
    global_per_minute: int
    client_per_day: Optional[int] = None
    global_per_day: Optional[int] = None

    def __post_init__(self):
        for value in (self.client_per_minute, self.global_per_minute, self.client_per_day, self.global_per_day):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value <= 0):
                raise ValueError("Rate limits must be positive integers")


@dataclass(frozen=True)
class Admission:
    allowed: bool
    retry_after: Optional[int] = None
    reason: Optional[str] = None


class _Denied(Exception):
    def __init__(self, decision: Admission):
        self.decision = decision


DEFAULT_LIMITS = {
    "run": RateLimit(10, 50, 80, 3000),
    "cancel": RateLimit(10, 30, 50, 1000),
    "mcp": RateLimit(600, 1200, 5000, 20000),
    "feedback": RateLimit(3, 30, 10, 500),
}


class PublicLimiter:
    def __init__(self, engine: Any, namespace: str, limits: Optional[Dict[str, RateLimit]] = None):
        from agno.db.postgres._bounded import bounded_engine

        self.engine = bounded_engine(engine, capacity=8)
        self.namespace = namespace
        self.limits = {**DEFAULT_LIMITS, **(limits or {})}
        if set(self.limits) != set(DEFAULT_LIMITS) or any(not isinstance(v, RateLimit) for v in self.limits.values()):
            raise ValueError("Unknown public rate-limit bucket or invalid RateLimit")
        self.ready = False

    def _prepare(self, *, budget: WorkBudget) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("SET LOCAL statement_timeout = '2500ms'"))
            conn.execute(text("SELECT pg_advisory_xact_lock(7148274142891)"))
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS public.agno_public_limits ("
                    "key text PRIMARY KEY, minute bigint NOT NULL, minute_count bigint NOT NULL, "
                    "day date NOT NULL, day_count bigint NOT NULL, updated_at timestamptz NOT NULL)"
                )
            )
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS agno_public_limits_updated ON public.agno_public_limits(updated_at)")
            )
            self._cleanup(conn)
        self.ready = True

    async def _aprepare(self) -> None:
        await WORKERS.run(self._prepare, seconds=3)

    @staticmethod
    def _cleanup(conn: Any) -> None:
        conn.execute(
            text(
                "WITH stale AS (SELECT key FROM public.agno_public_limits "
                "WHERE updated_at < now() - interval '7 days' ORDER BY updated_at "
                "FOR UPDATE SKIP LOCKED LIMIT 500) DELETE FROM public.agno_public_limits l "
                "USING stale WHERE l.key=stale.key"
            )
        )

    def _consume(self, bucket: str, *, client_id: str, cost: int, budget: WorkBudget) -> Admission:
        if not self.ready:
            raise ValueError("PublicSurface limiter is not prepared")
        if bucket not in self.limits or not isinstance(client_id, str) or len(client_id.encode()) > 256:
            raise ValueError("Invalid rate-limit bucket or client identity")
        if isinstance(cost, bool) or not isinstance(cost, int) or not 1 <= cost <= 100:
            raise ValueError("Invalid rate-limit cost")
        limit = self.limits[bucket]
        digest = hashlib.sha256((client_id or "unknown").encode()).hexdigest()
        checks = [
            ("global", limit.global_per_minute, limit.global_per_day),
            ("client:" + digest, limit.client_per_minute, limit.client_per_day),
        ]
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text("SELECT set_config('statement_timeout', :ms, true), set_config('lock_timeout', :ms, true)"),
                    {"ms": str(max(1, int(min(2.5, budget.remaining()) * 1000)))},
                )
                for subject, minute_limit, daily in checks:
                    day_limit = daily or 2**62
                    if cost > min(minute_limit, day_limit):
                        raise _Denied(Admission(False, 60, "rate_limited"))
                    key = self.namespace + ":" + bucket + ":" + subject
                    row = conn.execute(
                        text("""WITH current_window AS (
                        SELECT floor(extract(epoch FROM transaction_timestamp()) / 60)::bigint AS minute,
                        (transaction_timestamp() AT TIME ZONE 'UTC')::date AS day
                    ) INSERT INTO public.agno_public_limits AS l
                    (key, minute, minute_count, day, day_count, updated_at)
                    SELECT :key, minute, :cost, day, :cost, now() FROM current_window
                    ON CONFLICT(key) DO UPDATE SET minute=EXCLUDED.minute, day=EXCLUDED.day,
                        minute_count=(CASE WHEN l.minute=EXCLUDED.minute THEN l.minute_count ELSE 0 END)+:cost,
                        day_count=(CASE WHEN l.day=EXCLUDED.day THEN l.day_count ELSE 0 END)+:cost, updated_at=now()
                    WHERE (CASE WHEN l.minute=EXCLUDED.minute THEN l.minute_count ELSE 0 END)+:cost<=:minute_limit
                      AND (CASE WHEN l.day=EXCLUDED.day THEN l.day_count ELSE 0 END)+:cost<=:day_limit
                    RETURNING minute_count"""),
                        {"key": key, "cost": cost, "minute_limit": minute_limit, "day_limit": day_limit},
                    ).first()
                    if row is None:
                        reset = conn.execute(
                            text("""SELECT CASE WHEN day=(now() AT TIME ZONE 'UTC')::date
                            AND day_count+:cost>:day_limit THEN
                              ceil(extract(epoch FROM (date_trunc('day', now() AT TIME ZONE 'UTC')+interval '1 day'-(now() AT TIME ZONE 'UTC'))))
                            ELSE 60-mod(floor(extract(epoch FROM now()))::bigint,60) END
                            FROM public.agno_public_limits WHERE key=:key"""),
                            {"key": key, "cost": cost, "day_limit": day_limit},
                        ).scalar_one()
                        raise _Denied(Admission(False, max(1, int(reset)), "rate_limited"))
                    if subject == "global" and row[0] == cost:
                        self._cleanup(conn)
        except _Denied as exc:
            return exc.decision
        return Admission(True)

    def consume(self, bucket: str, *, client_id: str, cost: int = 1) -> Admission:
        """Consume client/global allowance atomically; database failure raises before dispatch."""
        return WORKERS.run_sync(self._consume, bucket, client_id=client_id, cost=cost, seconds=3)

    async def aconsume(self, bucket: str, *, client_id: str, cost: int = 1) -> Admission:
        """Consume allowance without blocking the event loop."""
        return await WORKERS.run(self._consume, bucket, client_id=client_id, cost=cost, seconds=3)
