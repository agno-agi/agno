"""Every event ends: with a result, or with the reason it has none. None is taken up for ever."""

import httpx
import pytest

from agno.db.schemas.triggers import EVENT_FAILED, EVENT_RUNNING, EVENT_SUCCESS
from agno.triggers import Trigger
from tests.unit.triggers.conftest import age_claim, call, comment_payload, issue_payload

INSTRUCTION = "Triage this issue: label it and comment."


def triage(github, agent, **options):
    return [
        Trigger(
            name="triage-issues",
            on=github.on("issues.opened"),
            continue_on="issue_comment.created",
            agent=agent,
            input=INSTRUCTION,
            **options,
        )
    ]


async def test_an_event_that_cannot_be_handled_fails_and_lets_the_next_one_run(make_os):
    os = await make_os(triage)
    await os.deliver(issue_payload())
    await os.deliver(issue_payload(number=8), delivery="d-2")

    # Something in handling the first event raises, and would raise every time it is tried.
    describe = os.github.describe

    def broken(event):
        if event.number == 7:
            raise KeyError("title")
        return describe(event)

    os.github.describe = broken
    await os.run_events()

    # It ends as failed, with what was raised, instead of being taken up again and again.
    first, second = await os.events()
    assert first["status"] == EVENT_FAILED
    assert first["error"] == "the event could not be handled: KeyError: 'title'"
    assert first["completed_at"] is not None and first["run_id"] is None
    assert second["status"] == EVENT_SUCCESS
    assert len(os.model.inputs) == 1


async def test_a_reply_behind_an_event_that_cannot_be_handled_is_not_held_for_ever(make_os):
    os = await make_os(triage)
    await os.deliver(issue_payload())
    await os.deliver(comment_payload(), event="issue_comment", delivery="d-2")
    os.github.load = lambda stored: (_ for _ in ()).throw(ValueError("the stored event cannot be read"))

    await os.run_events()

    opened, reply = await os.events()
    assert opened["status"] == EVENT_FAILED and "the stored event cannot be read" in opened["error"]
    # The reply was taken in its turn. It fails the same way, and it ends.
    assert reply["status"] == EVENT_FAILED


async def test_an_earlier_run_that_stays_unreadable_ends_the_event_after_its_timeout(make_os):
    os = await make_os(lambda github, agent: triage(github, agent, timeout_seconds=600))
    await os.deliver(issue_payload())
    await os.run_events()
    (row,) = await os.events()
    assert row["status"] == EVENT_SUCCESS

    # A replacement worker cannot read the run, now or later.
    await os.lose_claim(row["id"])
    os.fail_reads(times=100000, status_code=503)
    await os.run_events()
    (waiting,) = await os.events()
    assert waiting["status"] == EVENT_RUNNING and waiting["error"].startswith("waiting: ")
    since = waiting["event"]["run_unread_since"]

    # While the trigger's timeout has not passed since the first failed read, it keeps waiting.
    await age_claim(os.db, row["id"], 121)
    await os.run_events()
    (waiting,) = await os.events()
    assert waiting["status"] == EVENT_RUNNING and waiting["event"]["run_unread_since"] == since

    # After it, the event ends. Nothing is known about the run, so nothing is started in its place.
    stored = dict(waiting["event"])
    stored["run_unread_since"] = since - 601
    await call(os.db, "update_trigger_event", row["id"], event=stored)
    await age_claim(os.db, row["id"], 121)
    await os.run_events()
    (ended,) = await os.events()
    assert ended["status"] == EVENT_FAILED
    assert ended["error"] == (
        f"Run {row['run_id']}, started by an earlier worker, could not be read for 600s; the event was not run again"
    )
    assert ended["run_id"] == row["run_id"] and len(os.model.inputs) == 1


class LosingAnswers(httpx.AsyncBaseTransport):
    """The way to the app, where the answer to the first run request is lost after the app took it."""

    def __init__(self, app, error):
        self.inner = httpx.ASGITransport(app=app)
        self.error = error
        self.lost = 0

    async def handle_async_request(self, request):
        if request.method == "POST" and request.url.path.endswith("/runs") and self.lost == 0:
            self.lost += 1
            if not isinstance(self.error, httpx.ConnectError):
                # The app accepted the run. Only the answer never arrived.
                await self.inner.handle_async_request(request)
            raise self.error
        return await self.inner.handle_async_request(request)


async def test_a_run_request_whose_answer_is_lost_is_not_sent_again(make_os):
    os = await make_os(lambda github, agent: triage(github, agent, max_retries=2, retry_delay_seconds=0))
    transport = LosingAnswers(os.app, httpx.ReadError("connection reset"))
    os.runtime.executor._client = httpx.AsyncClient(transport=transport, timeout=30)
    await os.deliver(issue_payload())

    await os.run_events()
    # Let the run the app accepted finish.
    for _ in range(100):
        if len(os.model.inputs) >= 1 and os.model.running == 0:
            break
        import asyncio

        await asyncio.sleep(0.01)

    # The app may have started the run, and it did. Sending the request again would start a second.
    (row,) = await os.events()
    assert len(os.model.inputs) == 1
    assert row["status"] == EVENT_FAILED and row["attempt"] == 1
    assert row["error"] == (
        "the run request got no answer and may have been accepted (ReadError: connection reset); "
        "the event was not run again"
    )


async def test_a_run_request_that_never_reached_the_app_is_sent_again(make_os):
    os = await make_os(lambda github, agent: triage(github, agent, max_retries=2, retry_delay_seconds=0))
    transport = LosingAnswers(os.app, httpx.ConnectError("connection refused"))
    os.runtime.executor._client = httpx.AsyncClient(transport=transport, timeout=30)
    await os.deliver(issue_payload())

    await os.run_events()

    # Nothing was connected to, so nothing was started: the trigger's retry is safe.
    (row,) = await os.events()
    assert row["status"] == EVENT_SUCCESS and row["attempt"] == 2
    assert len(os.model.inputs) == 1


@pytest.mark.parametrize("status", [500, 404])
async def test_a_run_request_the_app_refuses_is_retried(make_os, status):
    os = await make_os(lambda github, agent: triage(github, agent, max_retries=1, retry_delay_seconds=0))
    inner = httpx.ASGITransport(app=os.app)
    refused = []

    async def answer(request):
        if request.method == "POST" and request.url.path.endswith("/runs") and not refused:
            refused.append(request)
            return httpx.Response(status, json={"detail": "refused"})
        return await inner.handle_async_request(request)

    class Refusing(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return await answer(request)

    os.runtime.executor._client = httpx.AsyncClient(transport=Refusing(), timeout=30)
    await os.deliver(issue_payload())
    await os.run_events()

    (row,) = await os.events()
    assert row["status"] == EVENT_SUCCESS and row["attempt"] == 2
    assert len(os.model.inputs) == 1


# ------------------------------------------------- what a takeover, or a shutdown, must not undo


async def test_a_run_that_had_already_failed_uses_the_retries_the_trigger_allows(make_os):
    from tests.unit.triggers.conftest import RecordingModel

    model = RecordingModel(fail_first=1)
    os = await make_os(lambda github, agent: triage(github, agent, max_retries=0), model=model)
    await os.deliver(issue_payload())
    await os.run_events()
    (row,) = await os.events()
    assert row["status"] == EVENT_FAILED and row["attempt"] == 1 and len(model.inputs) == 1

    # The worker stopped before it recorded that failure. Another worker takes the event over.
    await os.lose_claim(row["id"])
    await os.run_events()

    # The failed run was the one attempt the trigger allows. Taking the event over does not earn another.
    (again,) = await os.events()
    assert again["status"] == EVENT_FAILED and again["run_id"] == row["run_id"]
    assert len(model.inputs) == 1


async def test_a_trigger_turned_off_after_its_run_started_still_records_that_run(make_os):
    import asyncio

    from agno.triggers import TriggerManager
    from tests.unit.triggers.conftest import RecordingModel

    model = RecordingModel()
    model.gate = asyncio.Event()
    os = await make_os(triage, model=model)
    await os.deliver(issue_payload())
    assert await os.runtime.poller.poll_once() == 1
    while not (await os.events())[0]["run_id"]:
        await asyncio.sleep(0.01)
    first_run = (await os.events())[0]["run_id"]

    # The process stops mid-run, and the next version of the code no longer has the trigger on.
    await os.runtime.poller.stop()
    (trigger,) = await TriggerManager(os.db).alist()
    await TriggerManager(os.db).adisable(trigger.id)
    os.fail_reads(times=0)
    model.gate.set()
    await os.run_events()

    # The run was started while the trigger was on. Its result is recorded; it is not thrown away.
    (row,) = await os.events()
    assert row["status"] == EVENT_SUCCESS and row["run_id"] == first_run
    assert row["output"] == {"content": "done", "content_type": "str"}
    assert len(model.inputs) == 1


async def test_a_run_is_read_where_it_was_started_after_the_trigger_is_pointed_elsewhere(make_os):
    import asyncio

    from agno.triggers import TriggerManager
    from tests.unit.triggers.conftest import RecordingModel

    model = RecordingModel()
    model.gate = asyncio.Event()
    os = await make_os(triage, model=model)
    await os.deliver(issue_payload())
    assert await os.runtime.poller.poll_once() == 1
    while not (await os.events())[0]["run_id"]:
        await asyncio.sleep(0.01)
    first_run = (await os.events())[0]["run_id"]
    await os.runtime.poller.stop()

    # The trigger now runs another agent. The run in flight was started on the first one.
    (trigger,) = await TriggerManager(os.db).alist()
    await call(os.db, "update_trigger", trigger.id, target_id="another-agent")
    os.fail_reads(times=0)
    model.gate.set()
    await os.run_events()

    (row,) = await os.events()
    assert row["status"] == EVENT_SUCCESS and row["run_id"] == first_run
    assert len(model.inputs) == 1


class HoldingAnswers(httpx.AsyncBaseTransport):
    """The way to the app, where the answer to a run request is held back after the app took it."""

    def __init__(self, app):
        import asyncio

        self.inner = httpx.ASGITransport(app=app)
        self.taken = asyncio.Event()
        self.release = asyncio.Event()

    async def handle_async_request(self, request):
        response = await self.inner.handle_async_request(request)
        if request.method == "POST" and request.url.path.endswith("/runs"):
            self.taken.set()
            await self.release.wait()
        return response


async def test_a_worker_stopped_while_its_run_request_is_in_flight_does_not_hand_the_event_back(make_os):
    import asyncio

    os = await make_os(lambda github, agent: triage(github, agent, max_retries=2, retry_delay_seconds=0))
    transport = HoldingAnswers(os.app)
    os.runtime.executor._client = httpx.AsyncClient(transport=transport, timeout=30)
    await os.deliver(issue_payload())

    # The app has accepted the run. The worker has not heard back when the process stops.
    assert await os.runtime.poller.poll_once() == 1
    await transport.taken.wait()
    await os.runtime.poller.stop()
    for _ in range(100):
        if os.model.inputs and os.model.running == 0:
            break
        await asyncio.sleep(0.01)

    # Nothing says whether the run was accepted, and it was. Handing the event back would start a second.
    (row,) = await os.events()
    assert row["status"] == EVENT_FAILED
    assert row["error"] == (
        "the worker stopped while the run request was in flight, and the run may have been accepted; "
        "the event was not run again"
    )
    os.fail_reads(times=0)
    await os.run_events()
    assert len(os.model.inputs) == 1


async def test_a_run_that_could_not_be_recorded_at_first_is_recorded_while_it_runs(make_os):
    import asyncio

    from tests.unit.triggers.conftest import RecordingModel

    model = RecordingModel()
    model.gate = asyncio.Event()
    os = await make_os(triage, model=model)
    await os.deliver(issue_payload())
    write, failures = os.db.update_trigger_event, []

    def failing_once(event_id, held_by=None, **fields):
        if "run_id" in fields and not failures:
            failures.append(fields["run_id"])
            raise RuntimeError("database is locked")
        return write(event_id, held_by=held_by, **fields)

    os.db.update_trigger_event = failing_once
    assert await os.runtime.poller.poll_once() == 1

    # The write of the run's id failed once and was tried again. The event names its run while the
    # run is still going, so a worker that took the event over now would find it.
    for _ in range(200):
        (row,) = await os.events()
        if row["run_id"]:
            break
        await asyncio.sleep(0.01)
    assert failures and row["run_id"] == failures[0] and row["status"] == EVENT_RUNNING
    assert model.running == 1

    model.gate.set()
    await os.run_events()
    (row,) = await os.events()
    assert row["status"] == EVENT_SUCCESS and row["run_id"] == failures[0]


async def test_a_reply_received_by_a_replica_with_a_slower_clock_still_follows_its_issue(make_os, monkeypatch):
    from agno.db.schemas import triggers as schema
    from tests.unit.triggers.conftest import RecordingModel

    model = RecordingModel()
    one = await make_os(triage, model=model)
    two = await make_os(triage, model=model)
    await one.deliver(issue_payload())
    (opened,) = await one.events()

    # The reply arrives at a replica whose clock is a minute behind.
    behind = int(opened["id"].split("_")[1]) - 60_000_000_000
    monkeypatch.setattr(schema, "_last_timestamp", 0)
    monkeypatch.setattr(schema.time, "time_ns", lambda: behind)
    await two.deliver(comment_payload(), event="issue_comment", delivery="d-2")
    monkeypatch.undo()

    # It is stored after the issue it replies to, and runs after it.
    first, second = await one.events()
    assert (first["kind"], second["kind"]) == ("issues.opened", "issue_comment.created")
    await one.run_events()
    first, second = await one.events()
    assert first["status"] == EVENT_SUCCESS and second["status"] == EVENT_SUCCESS
    assert second["session_id"] == first["session_id"] and len(model.inputs) == 2
