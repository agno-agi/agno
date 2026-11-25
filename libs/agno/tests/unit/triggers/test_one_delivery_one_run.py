"""One delivery starts one run: once a run is recorded for an event, no second run is submitted
unless that run is known to have failed or been cancelled."""

import asyncio

import httpx

from agno.db.schemas.triggers import EVENT_FAILED, EVENT_PENDING, EVENT_RUNNING, EVENT_SUCCESS
from agno.triggers import Trigger
from tests.unit.triggers.conftest import RecordingModel, age_claim, call, issue_payload

INSTRUCTION = "Triage this issue: label it and comment."


def triage(github, agent, **options):
    return [Trigger(name="triage-issues", on=github.on("issues.opened"), agent=agent, input=INSTRUCTION, **options)]


async def until(condition, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        assert asyncio.get_running_loop().time() < deadline, "timed out waiting"
        await asyncio.sleep(0.01)


async def recorded_run(os, timeout=5.0):
    """The only event, once the run it started is recorded on it."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        (row,) = await os.events()
        if row["run_id"]:
            return row
        assert asyncio.get_running_loop().time() < deadline, "timed out waiting for the run to be recorded"
        await asyncio.sleep(0.01)


async def test_a_worker_that_lost_its_claim_starts_no_run(make_os):
    entered, release = asyncio.Event(), asyncio.Event()
    prepared, completed = [], []

    async def prepare(event):
        prepared.append(event.number)
        if len(prepared) == 1:
            # The first worker is held here, long enough for its claim to be taken.
            entered.set()
            await release.wait()

    def on_complete(event, run):
        completed.append(run.run_id)

    os = await make_os(lambda github, agent: triage(github, agent, prepare=prepare, on_complete=on_complete))
    await os.deliver(issue_payload())

    assert await os.runtime.poller.poll_once() == 1
    await entered.wait()
    (row,) = await os.events()

    # Its claim expires, and a second worker takes the event and handles it to the end.
    await age_claim(os.db, row["id"], 121)
    second = await call(os.db, "claim_trigger_event", "second-worker:1", 120)
    assert second is not None and second["id"] == row["id"]
    await os.runtime.executor.execute_event(second, os.db, os.runtime)

    # The first worker comes back. It no longer holds the event, so it starts nothing.
    release.set()
    await os.run_events()
    (row,) = await os.events()
    assert row["status"] == EVENT_SUCCESS
    assert len(os.model.inputs) == 1
    assert len(completed) == 1


async def test_a_worker_that_lost_its_claim_during_the_run_reports_nothing(make_os):
    completed = []
    model = RecordingModel()
    model.gate = asyncio.Event()
    os = await make_os(
        lambda github, agent: triage(github, agent, on_complete=lambda event, run: completed.append(run.run_id)),
        model=model,
    )
    await os.deliver(issue_payload())

    assert await os.runtime.poller.poll_once() == 1
    await until(lambda: model.running == 1)
    row = await recorded_run(os)

    # The first worker is still following its run when its claim expires and a second worker takes
    # the event. The run has not stopped, so the second worker starts nothing and leaves the event.
    await age_claim(os.db, row["id"], 121)
    second = await call(os.db, "claim_trigger_event", "second-worker:1", 120)
    assert second is not None
    await os.runtime.executor.execute_event(second, os.db, os.runtime)
    assert len(model.inputs) == 1

    # The run ends. The first worker sees it, and reports nothing: the event is no longer its own.
    model.gate.set()
    await os.run_events()
    assert completed == []
    (row,) = await os.events()
    assert row["status"] == EVENT_RUNNING and row["claimed_by"] == "second-worker:1"

    # A later attempt settles the event, and its end is reported once.
    await age_claim(os.db, row["id"], 121)
    await os.run_events()
    (row,) = await os.events()
    assert row["status"] == EVENT_SUCCESS
    assert len(completed) == 1
    assert model.most_at_once == 1


async def test_an_earlier_run_still_going_is_replaced_only_once_it_has_stopped(make_os):
    model = RecordingModel()
    model.gate = asyncio.Event()
    os = await make_os(triage, model=model)
    await os.deliver(issue_payload())

    assert await os.runtime.poller.poll_once() == 1
    await until(lambda: model.running == 1)
    first_run = (await recorded_run(os))["run_id"]

    # The process shuts down while the run is going, and hands the event back.
    await os.runtime.poller.stop()
    (row,) = await os.events()
    assert row["status"] == EVENT_PENDING and row["run_id"] == first_run

    # After the restart the run it left is asked to stop. Until it is seen to have stopped, nothing
    # is started in its place and the event keeps its claim.
    os.runtime.executor._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=os.app), timeout=30)
    await os.run_events()
    (row,) = await os.events()
    assert row["status"] == EVENT_RUNNING and row["claimed_by"] is not None
    assert row["run_id"] == first_run
    assert row["error"].startswith("waiting: ")
    assert len(model.inputs) == 1

    # The run stops. A later attempt sees that, and only then is the event run again.
    model.gate.set()
    await until(lambda: model.running == 0)
    await age_claim(os.db, row["id"], 121)
    await os.run_events()
    (row,) = await os.events()
    assert (await os.run({**row, "run_id": first_run}))["status"] == "CANCELLED"
    assert row["status"] == EVENT_SUCCESS
    assert row["run_id"] != first_run
    assert row["error"] is None
    # Two runs, one after the other, never at once.
    assert len(model.inputs) == 2
    assert model.most_at_once == 1


async def test_a_run_that_outlives_its_timeout_is_not_submitted_again(make_os):
    model = RecordingModel()
    model.gate = asyncio.Event()
    os = await make_os(
        lambda github, agent: triage(github, agent, timeout_seconds=1, max_retries=1, retry_delay_seconds=0),
        model=model,
    )
    await os.deliver(issue_payload())

    # The run is accepted and is still going when its timeout passes. It cannot be seen to stop.
    await os.run_events()
    # The retry the trigger allows is for a run known to have failed: this one may still be alive.
    assert len(model.inputs) == 1
    assert model.most_at_once == 1
    (row,) = await os.events()
    assert row["status"] == EVENT_FAILED
    assert "timeout" in row["error"] and "not run again" in row["error"]


async def test_a_failed_read_of_the_earlier_run_is_tried_again(make_os):
    os = await make_os(triage)
    await os.deliver(issue_payload())
    await os.run_events()
    (row,) = await os.events()
    assert row["status"] == EVENT_SUCCESS and len(os.model.inputs) == 1

    # A replacement worker looks the run up, and the first answer is a failure.
    await os.lose_claim(row["id"])
    os.fail_reads(times=1, status_code=503)
    await os.run_events()

    (again,) = await os.events()
    assert again["status"] == EVENT_SUCCESS
    assert again["run_id"] == row["run_id"]
    assert len(os.model.inputs) == 1


async def test_an_earlier_run_that_cannot_be_read_leaves_the_event_claimed(make_os):
    os = await make_os(triage)
    await os.deliver(issue_payload())
    await os.run_events()
    (row,) = await os.events()

    await os.lose_claim(row["id"])
    os.fail_reads(times=1000, status_code=503)
    await os.run_events()

    # Nobody knows how the run ended, so no second one is started. The event waits for a later attempt.
    (again,) = await os.events()
    assert again["status"] == EVENT_RUNNING and again["claimed_by"] is not None
    assert again["run_id"] == row["run_id"]
    assert len(os.model.inputs) == 1


async def test_a_recovered_event_reads_its_run_before_prepare(make_os):
    prepared = []

    def prepare(event):
        prepared.append(event.number)
        # Asked a second time, it would decline the event.
        return None if len(prepared) == 1 else False

    os = await make_os(lambda github, agent: triage(github, agent, prepare=prepare))
    await os.deliver(issue_payload())
    await os.run_events()
    (row,) = await os.events()
    assert row["status"] == EVENT_SUCCESS

    await os.lose_claim(row["id"])
    await os.run_events()

    # The run already completed: that is the event's result, and prepare is not asked again.
    (again,) = await os.events()
    assert again["status"] == EVENT_SUCCESS
    assert again["run_id"] == row["run_id"]
    assert len(prepared) == 1
    assert len(os.model.inputs) == 1
