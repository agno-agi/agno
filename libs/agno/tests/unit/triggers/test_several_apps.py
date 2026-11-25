"""Several AgentOS apps on one database, and several replicas of one: each app's triggers and
schedules are its own, and replicas of one app share its work."""

import asyncio

from agno.db.schemas.triggers import CODE_MANAGED, EVENT_PENDING, EVENT_SUCCESS
from agno.os.app import trigger_lifespan
from agno.scheduler import ScheduleManager
from agno.triggers import Schedule, Trigger, TriggerManager
from tests.unit.triggers.conftest import RecordingModel, issue_payload

INSTRUCTION = "Triage this issue: label it and comment."


def triage(github, agent, **options):
    return [Trigger(name="triage-issues", on=github.on("issues.opened"), agent=agent, input=INSTRUCTION, **options)]


def nothing(github, agent):
    return []


def nightly(github, agent):
    return [Trigger(name="nightly-report", on=Schedule("0 2 * * *"), agent=agent, input="Write the report.")]


async def test_an_agentos_with_another_id_leaves_these_triggers_and_events_alone(make_os):
    first = await make_os(triage, os_options={"id": "first-os"})
    second = await make_os(nothing, declare_now=False, os_options={"id": "second-os"})
    await first.deliver(issue_payload())

    # The second AgentOS starts on the same database, with a GitHub source and no trigger. Its
    # startup runs, and so does its poller.
    async with trigger_lifespan(second.app, second.agent_os):
        await asyncio.sleep(0.3)

    # The first one's trigger is still on, and its event was not taken.
    (trigger,) = await TriggerManager(first.db).alist()
    assert trigger.enabled and trigger.disabled_reason is None
    (row,) = await first.events()
    assert row["status"] == EVENT_PENDING and row["claimed_by"] is None
    assert second.model.inputs == []

    await first.run_events()
    (row,) = await first.events()
    assert row["status"] == EVENT_SUCCESS


async def test_a_delivery_matches_only_the_triggers_of_the_agentos_that_received_it(make_os):
    first = await make_os(triage, os_options={"id": "first-os"})
    second = await make_os(nothing, os_options={"id": "second-os"})

    answer = await second.deliver(issue_payload())

    assert answer.status_code == 202
    assert answer.json()["status"] == "ignored"
    (row,) = await second.events()
    assert row["reason"] == "no trigger listens for issues.opened"

    assert (await first.deliver(issue_payload(), delivery="d-2")).json()["status"] == "accepted"


async def test_replicas_of_one_agentos_share_its_work(make_os):
    model = RecordingModel()
    one = await make_os(triage, model=model, os_options={"id": "the-os"})
    two = await make_os(triage, model=model, os_options={"id": "the-os"})

    # One replica receives the delivery, the other runs it.
    await one.deliver(issue_payload())
    await two.run_events()

    (row,) = await one.events()
    assert row["status"] == EVENT_SUCCESS
    assert len(model.inputs) == 1
    # Both declare the trigger; it is one row, and neither turned it off.
    (trigger,) = await TriggerManager(one.db).alist()
    assert trigger.enabled


async def test_a_code_trigger_with_no_agentos_id_is_never_turned_off(make_os):
    os = await make_os(nothing, declare_now=False, os_options={"id": "the-os"})
    # A row written before triggers recorded which AgentOS declared them.
    old = await TriggerManager(os.db).acreate(
        name="from-before",
        source_id=os.github.id,
        events=["issues.opened"],
        target_type="agent",
        target_id="engineer",
        input=INSTRUCTION,
        provenance={"managed_by": CODE_MANAGED},
    )

    await os.start()

    # Nobody declares it now, and nobody can say whose it was: it is left as it is.
    kept = await TriggerManager(os.db).aget(old.id)
    assert kept is not None and kept.enabled and kept.disabled_reason is None


async def test_a_schedule_no_trigger_declared_is_left_alone(make_os):
    os = await make_os(triage)
    schedules = ScheduleManager(os.db)
    # An ordinary schedule whose run metadata happens to name a trigger.
    ordinary = await schedules.acreate(
        name="weekly-digest",
        cron="0 9 * * 1",
        endpoint="/agents/engineer/runs",
        payload={"message": "Write the digest.", "metadata": {"trigger_name": "weekly-digest"}},
    )

    await os.start()

    kept = await schedules.aget(ordinary.id)
    assert kept is not None and kept.enabled and kept.disabled_reason is None


async def test_two_replicas_registering_a_schedule_at_once_both_start(make_os):
    one = await make_os(nightly, os_options={"id": "the-os"})
    two = await make_os(nightly, declare_now=False, os_options={"id": "the-os"})

    # The second replica read the schedule as absent just before the first one stored it.
    read = two.db.get_schedule_by_name
    stale = [None]

    def read_once_stale(name, user_id=None):
        return stale.pop() if stale else read(name, user_id=user_id)

    two.db.get_schedule_by_name = read_once_stale
    await two.start()

    rows = [schedule for schedule in await ScheduleManager(one.db).alist_all() if schedule.name == "nightly-report"]
    assert len(rows) == 1 and rows[0].enabled


async def test_a_trigger_with_no_agentos_id_becomes_the_property_of_the_one_that_declares_it(make_os):
    os = await make_os(nothing, declare_now=False, os_options={"id": "the-os"})
    old = await TriggerManager(os.db).acreate(
        name="triage-issues",
        source_id=os.github.id,
        events=["issues.opened"],
        target_type="agent",
        target_id="engineer",
        input="An older instruction.",
        provenance={"managed_by": CODE_MANAGED},
    )
    assert old.os_id is None

    declares = await make_os(triage, os_options={"id": "the-os"})

    (trigger,) = await TriggerManager(declares.db).alist()
    assert trigger.id == old.id
    assert trigger.os_id == "the-os" and trigger.input == INSTRUCTION


async def test_the_id_triggers_are_stored_under(make_os):
    from agno.db.schemas.triggers import UNNAMED_OS_ID

    given = await make_os(triage, os_options={"id": "given-id"})
    named = await make_os(nothing, declare_now=False, os_options={"name": "Support OS"})
    neither = await make_os(nothing, declare_now=False)

    assert given.agent_os._trigger_os_id == "given-id"
    # A name gives the same id on every start. A random id does not, so it is not used.
    assert named.agent_os._trigger_os_id == named.agent_os.id
    assert neither.agent_os._trigger_os_id == UNNAMED_OS_ID and neither.agent_os.id != UNNAMED_OS_ID

    (trigger,) = await TriggerManager(given.db).alist()
    assert trigger.os_id == "given-id"


async def test_an_agentos_with_no_id_still_turns_off_the_triggers_it_stopped_declaring(make_os):
    from agno.db.schemas.triggers import NOT_DECLARED_REASON, UNNAMED_OS_ID

    os = await make_os(triage)
    (trigger,) = await TriggerManager(os.db).alist()
    assert trigger.os_id == UNNAMED_OS_ID

    # The next version of the code declares nothing. It starts with a new random id.
    later = await make_os(nothing)

    (trigger,) = await TriggerManager(later.db).alist()
    assert trigger.enabled is False and trigger.disabled_reason == NOT_DECLARED_REASON


async def test_a_schedule_a_trigger_declared_is_turned_off_only_by_its_own_agentos(make_os):
    from agno.db.schemas.triggers import NOT_DECLARED_REASON
    from agno.triggers.runtime import schedule_manager_of

    first = await make_os(nightly, os_options={"id": "first-os"})
    schedules = ScheduleManager(first.db)
    (schedule,) = [row for row in await schedules.alist_all() if row.name == "nightly-report"]
    assert schedule.managed_by == schedule_manager_of("first-os")

    # Another AgentOS on the database declares no trigger.
    await make_os(nothing, os_options={"id": "second-os"})
    assert (await schedules.aget(schedule.id)).enabled

    # The AgentOS that declared it stops declaring it.
    await make_os(nothing, os_options={"id": "first-os"})
    stopped = await schedules.aget(schedule.id)
    assert stopped.enabled is False and stopped.disabled_reason == NOT_DECLARED_REASON


async def test_a_schedule_stored_before_its_trigger_marked_it_is_marked_when_declared(make_os):
    from agno.triggers.runtime import schedule_manager_of

    os = await make_os(nothing, declare_now=False, os_options={"id": "the-os"})
    schedules = ScheduleManager(os.db)
    old = await schedules.acreate(
        name="nightly-report",
        cron="0 2 * * *",
        endpoint="/agents/engineer/runs",
        payload={"message": "Write the report.", "metadata": {"trigger_name": "nightly-report"}},
    )
    assert old.managed_by is None

    await make_os(nightly, os_options={"id": "the-os"})

    (schedule,) = [row for row in await schedules.alist_all() if row.name == "nightly-report"]
    assert schedule.id == old.id and schedule.managed_by == schedule_manager_of("the-os")


async def test_two_apps_that_declare_the_same_name_each_have_their_own_trigger(make_os):
    first_model, second_model = RecordingModel(), RecordingModel()
    first = await make_os(lambda github, agent: triage(github, agent), model=first_model, os_options={"id": "first-os"})
    second = await make_os(
        lambda github, agent: [
            Trigger(name="triage-issues", on=github.on("issues.opened"), agent=agent, input="The second app's.")
        ],
        model=second_model,
        os_options={"id": "second-os"},
    )

    rows = sorted(await TriggerManager(first.db).alist(), key=lambda row: row.os_id)
    assert [(row.name, row.os_id, row.enabled) for row in rows] == [
        ("triage-issues", "first-os", True),
        ("triage-issues", "second-os", True),
    ]
    assert rows[0].id != rows[1].id and rows[0].input == INSTRUCTION and rows[1].input == "The second app's."

    # Each runs its own, with its own instruction.
    await first.deliver(issue_payload())
    await second.deliver(issue_payload(), delivery="d-2")
    await first.run_events()
    await second.run_events()
    assert len(first_model.inputs) == 1 and first_model.inputs[0].startswith(INSTRUCTION)
    assert len(second_model.inputs) == 1 and second_model.inputs[0].startswith("The second app's.")

    # One stops declaring it. Only its own row is turned off.
    await make_os(nothing, os_options={"id": "second-os"})
    rows = sorted(await TriggerManager(first.db).alist(), key=lambda row: row.os_id)
    assert [(row.os_id, row.enabled) for row in rows] == [("first-os", True), ("second-os", False)]


async def test_a_trigger_with_no_agentos_id_is_adopted_by_the_first_app_that_declares_its_name(make_os):
    os = await make_os(nothing, declare_now=False, os_options={"id": "first-os"})
    old = await TriggerManager(os.db).acreate(
        name="triage-issues",
        source_id=os.github.id,
        events=["issues.opened"],
        target_type="agent",
        target_id="engineer",
        input="An older instruction.",
        provenance={"managed_by": CODE_MANAGED},
    )

    await make_os(triage, os_options={"id": "first-os"})
    await make_os(triage, os_options={"id": "second-os"})

    # The first app took the row that had no id. The second got a row of its own.
    rows = sorted(await TriggerManager(os.db).alist(), key=lambda row: row.os_id)
    assert [row.os_id for row in rows] == ["first-os", "second-os"]
    assert rows[0].id == old.id and rows[1].id != old.id


async def test_a_trigger_with_no_agentos_id_is_adopted_once(make_os):
    first = await make_os(nothing, declare_now=False, os_options={"id": "first-os"})
    second = await make_os(nothing, declare_now=False, os_options={"id": "second-os"})
    old = await TriggerManager(first.db).acreate(
        name="triage-issues",
        source_id=first.github.id,
        events=["issues.opened"],
        target_type="agent",
        target_id="engineer",
        input="An older instruction.",
        provenance={"managed_by": CODE_MANAGED},
    )
    first_declares = await make_os(triage, os_options={"id": "first-os"})

    # The second app read the row while it still had no id, just before the first one took it.
    read = second.db.get_trigger_by_name
    stale = [old.to_dict()]

    def read_once_stale(name, user_id=None, os_id=None):
        if os_id is None and stale:
            return stale.pop()
        return read(name, user_id=user_id, os_id=os_id)

    second_declares = await make_os(triage, declare_now=False, os_options={"id": "second-os"})
    second_declares.db.get_trigger_by_name = read_once_stale
    await second_declares.start()

    # The row stays the first app's. The second has a row of its own.
    rows = sorted(await TriggerManager(first.db).alist(), key=lambda row: row.os_id)
    assert [row.os_id for row in rows] == ["first-os", "second-os"]
    assert rows[0].id == old.id and rows[1].id != old.id
    assert (await first_declares.deliver(issue_payload())).json()["status"] == "accepted"


async def test_an_app_does_not_take_events_from_a_source_it_does_not_have(make_os):
    first = await make_os(nothing, os_options={"id": "first-os"})
    second = await make_os(nothing, os_options={"id": "second-os"}, prefix="/github-other")
    assert first.github.id == "github" and second.github.id == "github/github-other"
    # A trigger tied to no AgentOS, on the first app's source.
    await TriggerManager(first.db).acreate(
        name="shared",
        source_id="github",
        events=["issues.opened"],
        target_type="agent",
        target_id="engineer",
        input=INSTRUCTION,
    )
    await first.deliver(issue_payload())

    # The second app has no such source: it could only fail the event, so it leaves it.
    await second.run_events()
    (row,) = await first.events()
    assert row["status"] == EVENT_PENDING and row["claimed_by"] is None

    await first.run_events()
    (row,) = await first.events()
    assert row["status"] == EVENT_SUCCESS


async def test_a_schedule_managed_by_something_else_is_not_written_over(make_os):
    import pytest

    os = await make_os(nothing, declare_now=False, os_options={"id": "the-os"})
    schedules = ScheduleManager(os.db)
    theirs = await schedules.acreate(
        name="nightly-report",
        cron="0 5 * * *",
        endpoint="/agents/reporter/runs",
        payload={"message": "The builder's report."},
        provenance={"managed_by": "studio", "target_type": "agent", "target_id": "reporter"},
    )

    declares = await make_os(nightly, declare_now=False, os_options={"id": "the-os"})
    with pytest.raises(ValueError, match="schedule named 'nightly-report' on this database is managed by studio"):
        await declares.start()

    kept = await schedules.aget(theirs.id)
    assert kept.endpoint == "/agents/reporter/runs" and kept.cron_expr == "0 5 * * *"
    assert kept.payload["message"] == "The builder's report." and kept.managed_by == "studio"


async def test_two_apps_cannot_share_the_name_of_a_schedule_trigger(make_os):
    import pytest

    from agno.triggers.runtime import schedule_manager_of

    first = await make_os(nightly, os_options={"id": "first-os"})
    schedules = ScheduleManager(first.db)
    (mine,) = [row for row in await schedules.alist_all() if row.name == "nightly-report"]

    def other_report(github, agent):
        return [Trigger(name="nightly-report", on=Schedule("30 6 * * *"), agent=agent, input="The second app's.")]

    second = await make_os(other_report, declare_now=False, os_options={"id": "second-os"})
    with pytest.raises(ValueError, match="was declared by a trigger of AgentOS 'first-os'"):
        await second.start()

    # A schedule's name is unique in a database, so there is one row, and it is still the first app's.
    kept = await schedules.aget(mine.id)
    assert kept.cron_expr == "0 2 * * *" and kept.payload["message"] == "Write the report."
    assert kept.managed_by == schedule_manager_of("first-os") and kept.enabled
