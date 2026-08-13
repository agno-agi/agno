"""Redis queue-store lease math is anchored to the SERVER clock.

The Postgres store anchors lease decisions to the database's NOW() with a
loud doctrine comment; the Redis store judged staleness on each worker's
wall clock. A replica whose clock runs fast beyond the grace saw healthy
leases as expired and swept live runs - the sweep steals the lock, so the
victim's completion was fenced out and the run reported failed despite
finishing (and with multi-attempt budgets, a false sweep means duplicate
side-effect execution). All ownership decisions now read Redis TIME.
"""

from types import SimpleNamespace

import pytest

fakeredis = pytest.importorskip("fakeredis", reason="fakeredis not installed")

from agno.db.redis import RedisDb  # noqa: E402
from agno.db.schemas.jobs import QueuedJob  # noqa: E402


def make_job(job_id: str = "r1") -> dict:
    return QueuedJob(
        id=job_id,
        component_type="agent",
        component_id="a1",
        session_id="s1",
        payload={"input": "hello"},
        max_attempts=1,
    ).to_dict()


@pytest.fixture()
def db():
    return RedisDb(redis_client=fakeredis.FakeRedis(), db_prefix="clk")


def _skew_local_clock(monkeypatch, offset_seconds: float) -> None:
    """Skew the module-local wall clock the queue section used to trust."""
    import time as real_time

    real = real_time.time
    monkeypatch.setattr(
        "agno.db.redis.redis.time",
        SimpleNamespace(time=lambda: real() + offset_seconds),
    )


class TestSkewedWorkerCannotSweepHealthyLease:
    def test_sweep_detector_ignores_fast_local_clock(self, db, monkeypatch):
        db.enqueue_job(make_job("r1"))
        assert db.claim_job("w1", lock_grace_seconds=60) is not None

        _skew_local_clock(monkeypatch, 3600)

        stale = db.sweep_exhausted_jobs(lock_grace_seconds=60)
        assert stale == [], (
            f"a healthy just-claimed lease was judged stale by a skewed WORKER clock: {stale} - "
            "staleness must be measured on the Redis server's clock"
        )

    def test_acquire_sweep_refuses_healthy_lease_under_skew(self, db, monkeypatch):
        db.enqueue_job(make_job("r1"))
        assert db.claim_job("w1", lock_grace_seconds=60) is not None

        _skew_local_clock(monkeypatch, 3600)

        assert db.acquire_sweep("r1", "sweeper", 60) is False, (
            "a skewed replica stole a healthy lease - the steal fences out the live "
            "worker's completion and falsely fails the run"
        )

    def test_genuinely_stale_lease_is_still_sweepable(self, db):
        """No false negatives either: grace 0 makes the fresh claim stale on
        ANY clock - the sweep path must keep working."""
        db.enqueue_job(make_job("r1"))
        assert db.claim_job("w1", lock_grace_seconds=60) is not None

        stale = db.sweep_exhausted_jobs(lock_grace_seconds=0)
        assert [j["id"] for j in stale] == ["r1"]
        assert db.acquire_sweep("r1", "sweeper", 0) is True
