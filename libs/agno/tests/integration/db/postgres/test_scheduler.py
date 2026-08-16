"""Scheduler integration tests against a live PostgreSQL.

Mirrors tests/integration/db/sqlite/test_scheduler.py's Studio-namespace
coverage (the filter code is shared, the backends are not) and adds a real
thread-contention claim race. No mocks: the DB at localhost:5532 must be up,
and if it is not these tests ERROR rather than skip.
"""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import text

from agno.db.postgres import PostgresDb
from agno.db.schemas.scheduler import STUDIO_SCHEDULE_MANAGED_BY, ScheduleNameConflictError

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"


@pytest.fixture
def db():
    schema = f"test_scheduler_pg_{uuid.uuid4().hex[:8]}"
    database = PostgresDb(db_url=DB_URL, db_schema=schema)
    yield database
    with database.Session() as session, session.begin():
        session.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


def _make_schedule(**overrides):
    now = int(time.time())
    d = {
        "id": str(uuid.uuid4()),
        "name": f"test-schedule-{uuid.uuid4().hex[:6]}",
        "description": "Integration test schedule",
        "method": "POST",
        "endpoint": "/agents/a1/runs",
        "payload": None,
        "cron_expr": "0 9 * * *",
        "timezone": "UTC",
        "timeout_seconds": 3600,
        "max_retries": 0,
        "retry_delay_seconds": 60,
        "enabled": True,
        "next_run_at": now + 3600,
        "locked_by": None,
        "locked_at": None,
        "created_at": now,
        "updated_at": None,
    }
    d.update(overrides)
    return d


def test_generic_and_studio_names_are_isolated_per_actor(db):
    generic = _make_schedule(name="shared-name")
    studio_a = _make_schedule(
        name="shared-name",
        managed_by=STUDIO_SCHEDULE_MANAGED_BY,
        owner_actor_id="actor-a",
    )
    studio_b = _make_schedule(
        name="shared-name",
        managed_by=STUDIO_SCHEDULE_MANAGED_BY,
        owner_actor_id="actor-b",
    )
    db.create_schedule(generic)
    db.create_schedule(studio_a)
    db.create_schedule(studio_b)

    assert db.get_schedule_by_name("shared-name", exclude_managed_by=STUDIO_SCHEDULE_MANAGED_BY)["id"] == generic["id"]
    assert (
        db.get_schedule_by_name(
            "shared-name",
            managed_by=STUDIO_SCHEDULE_MANAGED_BY,
            owner_actor_id="actor-a",
        )["id"]
        == studio_a["id"]
    )
    with pytest.raises(ScheduleNameConflictError):
        db.create_schedule(
            _make_schedule(
                name="shared-name",
                managed_by=STUDIO_SCHEDULE_MANAGED_BY,
                owner_actor_id="actor-a",
            )
        )


def test_list_excludes_studio_before_count_and_pagination(db):
    studio = _make_schedule(
        name="aaa-studio-hidden",
        created_at=3,
        managed_by=STUDIO_SCHEDULE_MANAGED_BY,
        owner_actor_id="studio-actor",
        target_type="agent",
        target_id="studio-agent",
    )
    ordinary_first = _make_schedule(name="bbb-ordinary-first", created_at=2)
    ordinary_second = _make_schedule(name="ccc-ordinary-second", created_at=1)
    db.create_schedule(studio)
    db.create_schedule(ordinary_first)
    db.create_schedule(ordinary_second)

    # Positive first: the studio row exists and IS visible without the filter,
    # so the exclusions below cannot pass vacuously.
    unfiltered, unfiltered_count = db.get_schedules()
    assert studio["id"] in {schedule["id"] for schedule in unfiltered}
    assert unfiltered_count == 3

    page_one, total_count = db.get_schedules(
        limit=1,
        page=1,
        exclude_managed_by=STUDIO_SCHEDULE_MANAGED_BY,
    )
    page_two, second_total_count = db.get_schedules(
        limit=1,
        page=2,
        exclude_managed_by=STUDIO_SCHEDULE_MANAGED_BY,
    )

    assert total_count == second_total_count == 2
    assert [schedule["id"] for schedule in page_one] == [ordinary_first["id"]]
    assert [schedule["id"] for schedule in page_two] == [ordinary_second["id"]]


def test_concurrent_claim_due_schedule_grants_each_schedule_exactly_once(db):
    """8 workers race for 3 due schedules; every schedule is claimed exactly once.

    Two rounds on purpose: round one runs against empty lock state, round two
    against rows carrying the lock/release history the first round wrote.
    """
    now = int(time.time())
    schedule_ids = []
    for i in range(3):
        schedule = _make_schedule(name=f"due-{i}", next_run_at=now - 5)
        db.create_schedule(schedule)
        schedule_ids.append(schedule["id"])

    workers = 8
    for round_no in (1, 2):
        ready = Barrier(workers)

        def claim(worker_idx):
            ready.wait(timeout=10)
            row = db.claim_due_schedule(f"worker-{round_no}-{worker_idx}")
            return None if row is None else row["id"]

        with ThreadPoolExecutor(max_workers=workers) as executor:
            outcomes = list(executor.map(claim, range(workers)))

        claimed = [claimed_id for claimed_id in outcomes if claimed_id is not None]
        assert sorted(claimed) == sorted(schedule_ids), (
            f"round {round_no}: expected each of {len(schedule_ids)} schedules claimed exactly once, "
            f"got {outcomes}"
        )

        for schedule_id in schedule_ids:
            assert db.release_schedule(schedule_id, next_run_at=now - 5) is True
