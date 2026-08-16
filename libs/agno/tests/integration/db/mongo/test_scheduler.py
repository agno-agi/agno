"""Scheduler Studio-namespace tests against a live sync MongoDB.

Mirrors the sqlite/postgres namespace coverage for the Mongo backend. No
mocks: MongoDB at localhost:27017 must be up, and if it is not these tests
ERROR rather than skip.
"""

import time
import uuid

import pytest

from agno.db.schemas.scheduler import STUDIO_SCHEDULE_MANAGED_BY, ScheduleNameConflictError


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


def test_generic_and_studio_names_are_isolated_per_actor(mongo_db_real):
    db = mongo_db_real
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

    found = db.get_schedule_by_name("shared-name", exclude_managed_by=STUDIO_SCHEDULE_MANAGED_BY)
    assert found["id"] == generic["id"]
    scoped = db.get_schedule_by_name(
        "shared-name",
        managed_by=STUDIO_SCHEDULE_MANAGED_BY,
        owner_actor_id="actor-a",
    )
    assert scoped["id"] == studio_a["id"]
    with pytest.raises(ScheduleNameConflictError):
        db.create_schedule(
            _make_schedule(
                name="shared-name",
                managed_by=STUDIO_SCHEDULE_MANAGED_BY,
                owner_actor_id="actor-a",
            )
        )


def test_list_excludes_studio_before_count_and_pagination(mongo_db_real):
    db = mongo_db_real
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
