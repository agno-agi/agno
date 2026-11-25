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


# ------------------------------------------------------------------- several apps on one database


async def test_a_trigger_keeps_the_agentos_it_belongs_to(db):
    await call(db, "create_trigger", trigger_row("mine", os_id="first-os"))
    await call(db, "create_trigger", trigger_row("theirs", os_id="second-os"))
    await call(db, "create_trigger", trigger_row("anyones"))

    assert (await call(db, "get_trigger", "trg-mine"))["os_id"] == "first-os"
    assert (await call(db, "get_trigger", "trg-anyones"))["os_id"] is None

    # An AgentOS takes its own triggers and the ones tied to no AgentOS.
    rows, total = await call(db, "get_triggers", os_id="first-os")
    assert total == 2 and {row["name"] for row in rows} == {"mine", "anyones"}
    rows, total = await call(db, "get_triggers")
    assert total == 3

    # A row with no AgentOS can be given one.
    await call(db, "update_trigger", "trg-anyones", os_id="second-os")
    rows, total = await call(db, "get_triggers", os_id="first-os")
    assert {row["name"] for row in rows} == {"mine"}


async def test_a_claim_takes_only_events_whose_trigger_the_agentos_takes(db):
    await call(db, "create_trigger", trigger_row("mine", os_id="first-os"))
    await call(db, "create_trigger", trigger_row("theirs", os_id="second-os"))
    await call(db, "create_trigger", trigger_row("anyones"))
    theirs = event_row("d-1", trigger_id="trg-theirs", key=None)
    mine = event_row("d-2", trigger_id="trg-mine", key=None)
    anyones = event_row("d-3", trigger_id="trg-anyones", key=None)
    for row in (theirs, mine, anyones):
        assert await call(db, "create_trigger_event", row)

    # The oldest event belongs to another AgentOS: it is passed over, however long it waits.
    first = await call(db, "claim_trigger_event", "first:1", 120, os_id="first-os")
    second = await call(db, "claim_trigger_event", "first:2", 120, os_id="first-os")
    assert [first["id"], second["id"]] == [mine["id"], anyones["id"]]
    assert await call(db, "claim_trigger_event", "first:3", 120, os_id="first-os") is None

    # The AgentOS it belongs to takes it, as a second replica of that AgentOS would.
    assert (await call(db, "claim_trigger_event", "second:1", 120, os_id="second-os"))["id"] == theirs["id"]


async def test_a_claim_for_an_agentos_before_any_trigger_is_stored_takes_nothing(db):
    assert await call(db, "create_trigger_event", event_row("d-1", key=None))

    assert await call(db, "claim_trigger_event", "first:1", 120, os_id="first-os") is None
    # With no AgentOS named, any event is taken.
    assert await call(db, "claim_trigger_event", "anyone:1", 120) is not None


async def test_events_can_be_listed_by_whether_they_started_a_run(db):
    started = event_row("d-1", status=EVENT_SUCCESS, run_id="run-1")
    declined = event_row("d-2", status="skipped")
    for row in (started, declined):
        assert await call(db, "create_trigger_event", row)

    rows, total = await call(db, "get_trigger_events", event_key="agno-agi/agno#7", started_run=True)
    assert total == 1 and rows[0]["id"] == started["id"]
    rows, total = await call(db, "get_trigger_events", event_key="agno-agi/agno#7", started_run=False)
    assert total == 1 and rows[0]["id"] == declined["id"]
    assert (await call(db, "get_trigger_events", event_key="agno-agi/agno#7"))[1] == 2


async def test_trigger_names_are_unique_within_one_agentos(db):
    def named_triage(row_id, **fields):
        return {**trigger_row(row_id, **fields), "name": "triage"}

    await call(db, "create_trigger", named_triage("first", os_id="first-os"))
    await call(db, "create_trigger", named_triage("second", os_id="second-os"))
    await call(db, "create_trigger", named_triage("anyones"))
    await call(db, "create_trigger", named_triage("alice", os_id="first-os", user_id="alice"))

    # The name is looked up where the trigger belongs.
    assert (await call(db, "get_trigger_by_name", "triage", os_id="first-os"))["id"] == "trg-first"
    assert (await call(db, "get_trigger_by_name", "triage", os_id="second-os"))["id"] == "trg-second"
    assert (await call(db, "get_trigger_by_name", "triage"))["id"] == "trg-anyones"
    assert (await call(db, "get_trigger_by_name", "triage", user_id="alice", os_id="first-os"))["id"] == "trg-alice"
    assert await call(db, "get_trigger_by_name", "triage", user_id="alice", os_id="second-os") is None

    # A second one of the name in the same AgentOS, for the same owner, is refused.
    for again in (
        named_triage("first-again", os_id="first-os"),
        named_triage("anyones-again"),
        named_triage("alice-again", os_id="first-os", user_id="alice"),
    ):
        with pytest.raises(Exception):
            await call(db, "create_trigger", again)
    assert (await call(db, "get_triggers"))[1] == 4


async def test_a_claim_cannot_write_to_an_event_once_it_has_ended(db):
    row = event_row("d-1")
    assert await call(db, "create_trigger_event", row)
    claimed = await call(db, "claim_trigger_event", "worker:1", 120)
    assert claimed["id"] == row["id"]

    # The worker records the end. Its claim stays named on the row.
    ended = await call(db, "update_trigger_event", row["id"], held_by="worker:1", status=EVENT_SUCCESS)
    assert ended["status"] == EVENT_SUCCESS and ended["claimed_by"] == "worker:1"

    # A late write by that same claim, such as handing the event back on shutdown, changes nothing.
    assert await call(db, "update_trigger_event", row["id"], held_by="worker:1", status=EVENT_PENDING) is None
    assert (await call(db, "get_trigger_event", row["id"]))["status"] == EVENT_SUCCESS
    # A write that names no claim is the caller's own business.
    assert await call(db, "update_trigger_event", row["id"], reason="noted") is not None


async def test_a_trigger_tied_to_no_agentos_is_given_to_one_once(db):
    await call(db, "create_trigger", trigger_row("unmarked"))

    assert await call(db, "adopt_trigger", "trg-unmarked", "first-os") is True
    # It belongs to one now. A second taker gets nothing and changes nothing.
    assert await call(db, "adopt_trigger", "trg-unmarked", "second-os") is False
    assert (await call(db, "get_trigger", "trg-unmarked"))["os_id"] == "first-os"
    assert await call(db, "adopt_trigger", "trg-missing", "first-os") is False


async def test_a_claim_takes_only_events_of_the_sources_named(db):
    await call(db, "create_trigger", trigger_row("anyones"))
    elsewhere = {**event_row("d-1", trigger_id="trg-anyones", key=None), "source_id": "github/other"}
    here = event_row("d-2", trigger_id="trg-anyones", key=None)
    for row in (elsewhere, here):
        assert await call(db, "create_trigger_event", row)

    # The oldest event came from a source this AgentOS does not have. It is passed over.
    taken = await call(db, "claim_trigger_event", "first:1", 120, os_id="first-os", source_ids=["github"])
    assert taken["id"] == here["id"]
    assert await call(db, "claim_trigger_event", "first:2", 120, os_id="first-os", source_ids=["github"]) is None
    other = await call(db, "claim_trigger_event", "second:1", 120, os_id="second-os", source_ids=["github/other"])
    assert other["id"] == elsewhere["id"]
