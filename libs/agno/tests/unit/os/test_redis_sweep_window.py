"""Redis sweep detection pages the whole stale range.

The old fixed scan window (num=limit*2) made exhausted jobs invisible on
every tick when that many stale-but-reclaimable jobs sat ahead of them in
the running zset - after a mass crash under a retry budget, terminal
failures were starved indefinitely by the reclaim backlog in front.
"""

import json
import time

import pytest

fakeredis = pytest.importorskip("fakeredis", reason="fakeredis not installed")

from agno.db.redis import RedisDb  # noqa: E402
from agno.db.schemas.jobs import QueuedJob  # noqa: E402


def _seed_stale_running(db: RedisDb, job_id: str, score: int, attempt: int, max_attempts: int, locked_at: int) -> None:
    job = QueuedJob(
        id=job_id, component_type="agent", component_id="a1", session_id="s1", payload={}, max_attempts=max_attempts
    ).to_dict()
    job.update(status="running", locked_by="w-dead", locked_at=locked_at, attempt=attempt)
    db.redis_client.set(db._q_job_key(job_id), json.dumps(job))
    db.redis_client.zadd(db._q_key("running"), {job_id: score})


def test_exhausted_job_behind_many_reclaimables_is_found():
    db = RedisDb(redis_client=fakeredis.FakeRedis(), db_prefix="sweepwin")
    stale_at = int(time.time()) - 1000

    # 45 stale RECLAIMABLE jobs (attempt < max_attempts) with earlier zset
    # scores - more than the old fixed window of limit*2 = 40
    for i in range(45):
        _seed_stale_running(db, f"reclaim-{i:03d}", score=stale_at + i, attempt=1, max_attempts=2, locked_at=stale_at)
    # One stale EXHAUSTED job behind them all
    _seed_stale_running(db, "exhausted-1", score=stale_at + 100, attempt=1, max_attempts=1, locked_at=stale_at)

    swept = db.sweep_exhausted_jobs(lock_grace_seconds=60, limit=20)

    assert "exhausted-1" in [j["id"] for j in swept], (
        "an exhausted job behind the reclaim backlog must still be detected - the fixed window starved it on every tick"
    )


def test_limit_is_still_respected():
    db = RedisDb(redis_client=fakeredis.FakeRedis(), db_prefix="sweepwin2")
    stale_at = int(time.time()) - 1000
    for i in range(30):
        _seed_stale_running(db, f"exhausted-{i:03d}", score=stale_at + i, attempt=1, max_attempts=1, locked_at=stale_at)

    swept = db.sweep_exhausted_jobs(lock_grace_seconds=60, limit=20)
    assert len(swept) == 20


def test_healthy_leases_are_not_swept():
    db = RedisDb(redis_client=fakeredis.FakeRedis(), db_prefix="sweepwin3")
    now = int(time.time())
    _seed_stale_running(db, "healthy-1", score=now, attempt=1, max_attempts=1, locked_at=now)

    assert db.sweep_exhausted_jobs(lock_grace_seconds=60, limit=20) == []
