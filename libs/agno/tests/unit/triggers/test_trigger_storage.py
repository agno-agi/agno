"""Trigger storage on the four SQL adapters: one row for each delivery and trigger, one run at a
time for each key in the order events arrived, and a claim that lives only while it is renewed."""

import time

import pytest
from sqlalchemy import text

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.triggers import (
    EVENT_IGNORED,
    EVENT_PENDING,
    EVENT_RUNNING,
    EVENT_SUCCESS,
    HANDLED_EVENT_STATUSES,
    NO_TRIGGER_ID,
    StoredTrigger,
    TriggerEvent,
    new_trigger_event_id,
)
from tests.unit.triggers.conftest import call


def trigger_row(name="triage", **overrides):
    return StoredTrigger(
        id=f"trg-{name}",
        name=name,
        source_id="github",
        events=["issues.opened"],
        continue_on=["issue_comment.created"],
        filters={"allow": "members"},
        target_type="agent",
        target_id="engineer",
        input="Triage this issue.",
        **overrides,
    ).to_dict()


def event_row(delivery="d-1", trigger_id="trg-triage", key="agno-agi/agno#7", **overrides):
    return TriggerEvent(
        id=new_trigger_event_id(),
        source_id="github",
        delivery_id=delivery,
        trigger_id=trigger_id,
        kind="issues.opened",
        event_key=key,
        event={"repository": "agno-agi/agno", "issue": {"number": 7}},
        **overrides,
    ).to_dict()


async def age_claim(db, event_id, seconds):
    """Move an event's claim into the past, as if its worker had stopped renewing it."""
    table = await call(db, "_get_table", table_type="trigger_events")
    statement = text(f"UPDATE {table.fullname} SET claimed_at = claimed_at - :seconds WHERE id = :id")
    if isinstance(db, AsyncBaseDb):
        async with db.async_session_factory() as sess, sess.begin():
            await sess.execute(statement, {"seconds": seconds, "id": event_id})
    else:
        with db.Session() as sess, sess.begin():
            sess.execute(statement, {"seconds": seconds, "id": event_id})


async def test_reads_before_the_tables_exist_create_nothing(db):
    assert await call(db, "get_trigger", "missing") is None
    assert await call(db, "get_triggers") == ([], 0)
    assert await call(db, "get_trigger_events") == ([], 0)
    assert await call(db, "claim_trigger_event", "worker") is None
    assert await call(db, "_get_table", table_type="triggers") is None
    assert await call(db, "_get_table", table_type="trigger_events") is None


async def test_trigger_round_trip(db):
    created = await call(db, "create_trigger", trigger_row())
    assert created["id"] == "trg-triage"

    stored = await call(db, "get_trigger", "trg-triage")
    assert stored["events"] == ["issues.opened"]
    assert stored["continue_on"] == ["issue_comment.created"]
    assert stored["filters"] == {"allow": "members"}
    assert stored["enabled"] is True

    assert (await call(db, "get_trigger_by_name", "triage"))["id"] == "trg-triage"
    assert await call(db, "get_trigger_by_name", "triage", user_id="alice") is None

    updated = await call(db, "update_trigger", "trg-triage", enabled=False, disabled_reason="not_declared")
    assert updated["enabled"] is False and updated["disabled_reason"] == "not_declared"
    assert updated["updated_at"] is not None

    rows, total = await call(db, "get_triggers", source_id="github", enabled=True)
    assert rows == [] and total == 0
    rows, total = await call(db, "get_triggers", source_id="github")
    assert [row["id"] for row in rows] == ["trg-triage"] and total == 1


async def test_update_trigger_refuses_the_owner_and_the_id(db):
    await call(db, "create_trigger", trigger_row())
    with pytest.raises(ValueError, match="cannot modify"):
        await call(db, "update_trigger", "trg-triage", user_id=None, id="other")
    with pytest.raises(ValueError, match="cannot modify"):
        await call(db, "update_trigger", "trg-triage", created_at=1)


async def test_trigger_names_are_unique_for_each_owner(db):
    await call(db, "create_trigger", trigger_row())
    with pytest.raises(Exception):
        await call(db, "create_trigger", {**trigger_row(), "id": "trg-second"})
    # Another owner may use the same name.
    await call(db, "create_trigger", {**trigger_row(), "id": "trg-alice", "user_id": "alice"})
    assert (await call(db, "get_trigger_by_name", "triage", user_id="alice"))["id"] == "trg-alice"
    assert (await call(db, "get_trigger_by_name", "triage"))["id"] == "trg-triage"


async def test_delete_trigger_removes_its_events(db):
    await call(db, "create_trigger", trigger_row())
    await call(db, "create_trigger_event", event_row())
    await call(db, "create_trigger_event", event_row(delivery="d-2", trigger_id="trg-other"))

    assert await call(db, "delete_trigger", "trg-triage") is True
    assert await call(db, "get_trigger", "trg-triage") is None
    rows, total = await call(db, "get_trigger_events")
    assert [row["trigger_id"] for row in rows] == ["trg-other"] and total == 1
    assert await call(db, "delete_trigger", "trg-triage") is False


async def test_a_delivery_is_stored_once_for_each_trigger(db):
    assert await call(db, "create_trigger_event", event_row()) is True
    # The same delivery for the same trigger: a redelivery.
    assert await call(db, "create_trigger_event", event_row()) is False
    # The same delivery for another trigger is its own row.
    assert await call(db, "create_trigger_event", event_row(trigger_id="trg-other")) is True
    # A delivery that matched no trigger is also stored once.
    ignored = dict(trigger_id=NO_TRIGGER_ID, status=EVENT_IGNORED, reason="no trigger listens for push")
    assert await call(db, "create_trigger_event", event_row(delivery="d-9", **ignored)) is True
    assert await call(db, "create_trigger_event", event_row(delivery="d-9", **ignored)) is False

    rows, total = await call(db, "get_trigger_events")
    assert total == 3


async def test_a_refused_insert_that_is_not_a_duplicate_raises(db):
    await call(db, "create_trigger_event", event_row())
    broken = event_row(delivery="d-2")
    broken["status"] = None
    with pytest.raises(Exception):
        await call(db, "create_trigger_event", broken)


async def test_claim_takes_the_oldest_pending_event_once(db):
    first, second = event_row(delivery="d-1", key=None), event_row(delivery="d-2", key=None)
    await call(db, "create_trigger_event", first)
    await call(db, "create_trigger_event", second)

    claimed = await call(db, "claim_trigger_event", "claim-a")
    assert claimed["id"] == first["id"]
    assert claimed["status"] == EVENT_RUNNING and claimed["claimed_by"] == "claim-a"
    assert claimed["claimed_at"] is not None

    # Events without a key do not wait for each other.
    assert (await call(db, "claim_trigger_event", "claim-b"))["id"] == second["id"]
    assert await call(db, "claim_trigger_event", "claim-c") is None


async def test_ignored_events_are_never_claimed(db):
    await call(db, "create_trigger_event", event_row(status=EVENT_IGNORED, reason="not watched"))
    assert await call(db, "claim_trigger_event", "claim-a") is None


async def test_one_run_at_a_time_for_each_key_in_order(db):
    first, second = event_row(delivery="d-1"), event_row(delivery="d-2")
    other_issue = event_row(delivery="d-3", key="agno-agi/agno#8")
    for row in (first, second, other_issue):
        await call(db, "create_trigger_event", row)

    assert (await call(db, "claim_trigger_event", "claim-a"))["id"] == first["id"]
    # The second event for issue 7 waits; the event for issue 8 runs.
    assert (await call(db, "claim_trigger_event", "claim-b"))["id"] == other_issue["id"]
    assert await call(db, "claim_trigger_event", "claim-c") is None

    await call(db, "update_trigger_event", first["id"], held_by="claim-a", status=EVENT_SUCCESS)
    assert (await call(db, "claim_trigger_event", "claim-c"))["id"] == second["id"]


async def test_the_same_key_on_another_trigger_does_not_wait(db):
    first = event_row(delivery="d-1")
    other_trigger = event_row(delivery="d-1", trigger_id="trg-other")
    await call(db, "create_trigger_event", first)
    await call(db, "create_trigger_event", other_trigger)

    assert (await call(db, "claim_trigger_event", "claim-a"))["id"] == first["id"]
    assert (await call(db, "claim_trigger_event", "claim-b"))["id"] == other_trigger["id"]


async def test_a_renewed_claim_is_not_taken_and_a_stale_one_is(db):
    row = event_row()
    await call(db, "create_trigger_event", row)
    assert (await call(db, "claim_trigger_event", "claim-a", 120))["id"] == row["id"]

    # The run is long, and its worker keeps renewing: nobody else may take it.
    await age_claim(db, row["id"], 300)
    assert await call(db, "renew_trigger_event_claim", row["id"], "claim-a") is True
    assert await call(db, "claim_trigger_event", "claim-b", 120) is None

    # The worker stops. Once the claim is older than the limit, another worker takes the event.
    await age_claim(db, row["id"], 121)
    reclaimed = await call(db, "claim_trigger_event", "claim-b", 120)
    assert reclaimed["id"] == row["id"] and reclaimed["claimed_by"] == "claim-b"

    # The first worker has lost the event: it can neither renew nor write a result.
    assert await call(db, "renew_trigger_event_claim", row["id"], "claim-a") is False
    assert await call(db, "update_trigger_event", row["id"], held_by="claim-a", status=EVENT_SUCCESS) is None
    assert (await call(db, "get_trigger_event", row["id"]))["status"] == EVENT_RUNNING


async def test_a_stale_claim_still_holds_back_later_events_for_its_key(db):
    first, second = event_row(delivery="d-1"), event_row(delivery="d-2")
    await call(db, "create_trigger_event", first)
    await call(db, "create_trigger_event", second)
    await call(db, "claim_trigger_event", "claim-a", 120)
    await age_claim(db, first["id"], 121)

    # The abandoned first event is taken again before the second one runs.
    assert (await call(db, "claim_trigger_event", "claim-b", 120))["id"] == first["id"]
    assert await call(db, "claim_trigger_event", "claim-c", 120) is None


async def test_update_and_list_events(db):
    row = event_row()
    await call(db, "create_trigger_event", row)
    await call(db, "create_trigger_event", event_row(delivery="d-2", status=EVENT_IGNORED, reason="not allowed"))

    updated = await call(
        db,
        "update_trigger_event",
        row["id"],
        status=EVENT_SUCCESS,
        run_id="run-1",
        session_id="session-1",
        output={"content": "done"},
        completed_at=int(time.time()),
    )
    assert updated["run_id"] == "run-1" and updated["output"] == {"content": "done"}

    rows, total = await call(db, "get_trigger_events", trigger_id="trg-triage", statuses=[EVENT_IGNORED])
    assert total == 1 and rows[0]["reason"] == "not allowed"
    rows, total = await call(
        db,
        "get_trigger_events",
        trigger_id="trg-triage",
        event_key="agno-agi/agno#7",
        statuses=list(HANDLED_EVENT_STATUSES),
    )
    assert total == 1 and rows[0]["id"] == row["id"]
    rows, total = await call(db, "get_trigger_events", delivery_id="d-2")
    assert total == 1
    assert await call(db, "update_trigger_event", "missing", status=EVENT_SUCCESS) is None


async def test_delete_old_events_in_the_given_states_only(db):
    old = int(time.time()) - 8 * 86400
    old_ignored = event_row(delivery="d-1", status=EVENT_IGNORED, created_at=old)
    old_pending = event_row(delivery="d-2", status=EVENT_PENDING, created_at=old)
    new_ignored = event_row(delivery="d-3", status=EVENT_IGNORED)
    for row in (old_ignored, old_pending, new_ignored):
        await call(db, "create_trigger_event", row)

    deleted = await call(db, "delete_trigger_events", int(time.time()) - 7 * 86400, [EVENT_IGNORED])
    assert deleted == 1
    rows, _ = await call(db, "get_trigger_events")
    assert {row["id"] for row in rows} == {old_pending["id"], new_ignored["id"]}


async def test_event_ids_sort_in_the_order_they_were_made():
    ids = [new_trigger_event_id() for _ in range(200)]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_a_database_without_trigger_storage_says_so():
    class Other(BaseDb):
        pass

    for name in ("claim_trigger_event", "create_trigger_event", "get_triggers"):
        assert getattr(BaseDb, name) is getattr(Other, name)
        assert getattr(AsyncBaseDb, name) is not None
