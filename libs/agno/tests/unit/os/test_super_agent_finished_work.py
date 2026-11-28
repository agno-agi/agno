"""When work a Super Agent conversation started ends, the conversation gets one run that reports it and
changes nothing."""

import asyncio
import json
import time

import pytest

from agno.agent import Agent
from agno.db.schemas.scheduler import (
    FINISHED_WORK_REPORT_METADATA_KEY,
    REQUESTED_FROM_METADATA_KEY,
    RESERVED_RUN_METADATA_KEYS,
)
from agno.db.sqlite import SqliteDb
from agno.job_queue import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.os import AgentOS, CompanyConfig, OSManager
from agno.os.authz import Authorization
from agno.os.authz.provider import AuthorizationContext
from agno.os.authz.scope_provider import ScopeAuthorizationProvider
from agno.os.job_queue import QueueWorker
from agno.os.manager import finished_work, linked_work
from agno.os.manager.finished_work import (
    FINISHED_WORK_LABEL,
    FINISHED_WORK_REPORT_LIMIT,
    READ_TOOLS,
    FinishedWorkReports,
)
from agno.os.manager.linked_work import LINKED_WORK_KEY
from agno.registry import Registry
from agno.run import RunContext
from agno.run import background as run_background
from agno.run.authorization import (
    FINISHED_WORK_REPORT_REFUSAL,
    RunAuthorization,
    authorization_scope,
    current_authorization,
)
from agno.run.background import await_background_runs
from agno.workflow import Step, StepInput, StepOutput, Workflow
from tests.unit.os.test_mini_agent_tasks import ScriptedModel

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")

SECRET = "finished-work-tests-secret-at-least-32-bytes"
SCOPES = [
    *(f"agents:{name}:run" for name in ("writer", "writer-2", "writer-3", "writer-4", "writer-5")),
    "workflows:investigator:run",
    "teams:superagent:run",
    "tasks:read",
    "tasks:write",
    "wiki:read",
]
CHAT = "chat"

GATES: dict = {}
SEEN: dict = {}


WRITERS = ["writer", "writer-2", "writer-3", "writer-4", "writer-5"]


class Gated(ScriptedModel):
    """A model that waits for its gate before it replies, or fails where the test says so."""

    def __init__(self, gate="writer"):
        super().__init__()
        self.gate = gate

    async def ainvoke(self, messages, tools=None, **kwargs):
        await GATES[self.gate].wait()
        if SEEN.get("writer_fails"):
            raise RuntimeError("the writer broke")
        return self.invoke(messages, tools=tools, **kwargs)


async def investigate(step_input: StepInput) -> StepOutput:
    await GATES["investigator"].wait()
    return StepOutput(content="The export fails on the old role.")


class Chat(ScriptedModel):
    """Super Agent's model. Each run takes the next script; it records what each run was sent and offered."""

    def __init__(self):
        super().__init__()
        self.scripts: list = []
        self.runs: list = []
        # How many requests have reached the chat gate and wait there.
        self.held = 0

    def invoke(self, messages, tools=None, **kwargs):
        fresh = [m for m in messages if not m.from_history and m.role != "system"]
        if not any(m.role == "tool" for m in fresh):
            # The first request of a run.
            self.script = self.scripts.pop(0) if self.scripts else []
            self.runs.append(
                {
                    "sent": [str(m.content) for m in fresh if m.role == "user"],
                    "offered": {tool["function"]["name"] for tool in tools or []},
                    "authority": current_authorization(),
                }
            )
        system = [m for m in messages if m.role == "system"]
        return super().invoke(system + fresh, tools)

    async def ainvoke(self, messages, tools=None, **kwargs):
        if GATES.get("chat") is not None:
            self.held += 1
            await GATES["chat"].wait()
        return self.invoke(messages, tools=tools, **kwargs)


class System:
    """An AgentOS with Super Agent, a gated agent and a gated workflow, told when work ends."""

    def __init__(self, tmp_path, queue=False, authorization=False, user_isolation=False, company=False, **manager):
        self.db = SqliteDb(db_file=str(tmp_path / "os.db"))
        self.writers = [Agent(id=name, name=name.title(), model=Gated(name), db=self.db) for name in WRITERS]
        self.writer = self.writers[0]
        self.investigator = Workflow(
            id="investigator", name="Investigator", db=self.db, steps=[Step(name="investigate", executor=investigate)]
        )
        self.chat = Chat()
        self.os = AgentOS(
            id="finished-work",
            db=self.db,
            agents=self.writers,
            workflows=[self.investigator],
            registry=Registry(agents=self.writers, workflows=[self.investigator]),
            manager=OSManager(model=self.chat, access_docs=False, **manager),
            telemetry=False,
            **({"company": CompanyConfig()} if company else {}),
            **({"user_isolation": True} if user_isolation else {}),
            **(
                {"authorization": Authorization(verification_keys=[SECRET], algorithm="HS256")} if authorization else {}
            ),
        )
        self.app = self.os.get_app()
        self.os._manager_app = self.app
        self.reports = FinishedWorkReports(self.os, self.app)
        run_background._requester_listeners.append(self.reports)
        self.queue = None
        if queue:
            by_id = {writer.id: writer for writer in self.writers}
            by_id["investigator"] = self.investigator

            def resolve(kind, component_id, *a, **k):
                # Super Agent runs on a copy of the served Team, as the AgentOS queue and routes run it.
                return self.os.manager.deep_copy() if component_id == "superagent" else by_id[component_id]

            self.queue = QueueWorker(
                InMemoryQueueStore(),
                resolve,
                QueueConfig(durable=True),
                authorization_app=self.app,
            )
            self.app.state.queue_worker = self.queue
            if company:
                self.queue._company_db = self.db
        if company:
            # The Company lifespan publishes the app to Super Agent's tools; these tests have no lifespan.
            self.os._company_app = self.app
        self.authorization = authorization
        self.jobs: list = []

    def close(self):
        run_background._requester_listeners.remove(self.reports)
        self.db.close()

    def authority(self, user="alice", scopes=None):
        if not self.authorization:
            return None
        return RunAuthorization(
            ScopeAuthorizationProvider(),
            AuthorizationContext(principal_id=user, scopes=SCOPES if scopes is None else scopes, claims={"sub": user}),
        )

    async def say(self, message, *script, user="alice", session=CHAT):
        """One turn of the person: Super Agent calls the scripted tools, then replies."""
        self.chat.scripts.append(list(script))
        authority = self.authority(user)
        with authorization_scope(lambda: authority):
            return await self.os.manager.arun(message, user_id=user, session_id=session)

    async def say_held(self, message, **turn):
        """Start a turn of the person and return once it is held at the chat gate: its messages are
        built, with the work as it stood then, and its reply has not been written. A fixed wait in
        its place lets a slow machine end the work before the turn has read it."""
        GATES["chat"] = asyncio.Event()
        before = self.chat.held
        going = asyncio.ensure_future(self.say(message, **turn))
        for _ in range(4000):
            if self.chat.held > before:
                return going
            assert not going.done(), "the turn ended before it reached the chat gate"
            await asyncio.sleep(0.005)
        raise AssertionError("the turn did not reach the chat gate")

    async def start(self, kind="agent", component="writer", **turn):
        """The person asks for a background run. Returns its run id."""
        call = ("start_background_run", {"component_type": kind, "component_id": component, "message": "Go"})
        run = await self.say("Start it", call, **turn)
        receipt = json.loads(run.tools[0].result)
        assert receipt.get("started") is True, receipt
        return receipt["run_id"]

    async def work(self):
        """Take every queued run, as the queue worker does. Each executes as a task of its own."""
        claimed = 0
        while self.queue is not None:
            job = await self.queue.store.claim_job(self.queue.worker_id, self.queue.config.lock_grace_seconds)
            if job is None:
                break
            self.jobs.append(asyncio.ensure_future(self.queue._execute_claimed(job)))
            claimed += 1
        return claimed

    async def settle(self):
        """Wait until nothing moves: no run to take, none ending, no notice or finished-work report in flight.

        A run still held at its gate stays held, and is not waited for.
        """
        quiet, before = 0, None
        while quiet < 25:
            claimed = await self.work()
            await asyncio.sleep(0.01)
            now = (
                len([job for job in self.jobs if not job.done()]),
                len([task for task in run_background._background_tasks if not task.done()]),
                len(_workflows_going()),
                len(run_background._requester_notices),
            )
            quiet = quiet + 1 if not claimed and now == before else 0
            before = now

    async def finish(self, *names):
        for name in names or ("writer",):
            GATES[name].set()
        await self.settle()

    def turns(self, session=CHAT):
        """The conversation's stored turns, oldest first."""
        rows, _ = self.db.get_runs(session_id=session, deserialize=False)
        return [row for row in rows if row.get("parent_run_id") is None]

    def reports_stored(self, session=CHAT):
        return [row for row in self.turns(session) if finished_work._is_report(row)]

    def row(self, run_id):
        return self.db.get_run(run_id, deserialize=False)


def _workflows_going():
    from agno.workflow.workflow import _workflow_background_tasks

    return [task for task in _workflow_background_tasks if not task.done()]


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    GATES.clear()
    SEEN.clear()
    finished_work._latest_run.clear()
    monkeypatch.setattr(finished_work, "SETTLE_SECONDS", 0.02)
    # The scripted test models stand in for a provider that is sent the linked-work block.
    monkeypatch.setattr(linked_work, "_delivers", lambda model: not getattr(model, "unlisted", False))
    yield


@pytest.fixture(params=[False, True], ids=["in-memory", "durable-queue"])
def system(request, tmp_path):
    value = System(tmp_path, queue=request.param)
    yield value
    value.close()


@pytest.fixture
def plain(tmp_path):
    value = System(tmp_path)
    yield value
    value.close()


def scenario(steps):
    """Run a test's steps on one event loop, with a gate for each gated component."""

    async def run():
        for name in [*WRITERS, "investigator"]:
            GATES[name] = asyncio.Event()
        try:
            return await steps()
        finally:
            for gate in GATES.values():
                if gate is not None:
                    gate.set()
            await await_background_runs(timeout=5)
            for task in [*run_background._requester_notices, *asyncio.all_tasks()]:
                if task is not asyncio.current_task():
                    task.cancel()

    return asyncio.run(run())


def content(row):
    return str((row.get("run_data") or {}).get("content"))


def sent(row):
    run_input = (row.get("run_data") or {}).get("input")
    return str(run_input.get("input_content") if isinstance(run_input, dict) else run_input)


# ----------------------------------------------------------------- it fires


def test_a_finished_background_run_gives_the_conversation_a_finished_work_report(system):
    async def steps():
        run_id = await system.start()
        assert system.reports_stored() == []
        system.chat.scripts.append([("check_background_run", {"run_id": run_id})])
        await system.finish()
        return run_id, system.turns(), system.row(run_id)

    run_id, turns, work = scenario(steps)
    assert work["status"] == "COMPLETED"
    assert len(turns) == 2
    report = turns[1]
    assert report["status"] == "COMPLETED" and report["user_id"] == "alice"
    assert sent(report).startswith(FINISHED_WORK_LABEL + ". The person did not write this")
    assert f'Background run of agent "Writer" (run {run_id}): finished.' in sent(report)
    assert report["run_data"]["metadata"][FINISHED_WORK_REPORT_METADATA_KEY] == {
        "kind": "run",
        "id": run_id,
        "status": "COMPLETED",
    }
    # The reply is the model's, made from the result it read with a tool.
    assert '"status": "COMPLETED"' in content(report)


def test_a_run_started_through_a_workflow_is_reported_too(system):
    async def steps():
        run_id = await system.start("workflow", "investigator")
        await system.finish("investigator")
        return run_id, system.reports_stored()

    run_id, reports = scenario(steps)
    assert len(reports) == 1
    assert f'Background run of workflow "Investigator" (run {run_id}): finished.' in sent(reports[0])


def test_a_failed_run_is_reported_as_failed(system):
    async def steps():
        SEEN["writer_fails"] = True
        run_id = await system.start()
        await system.finish()
        return system.row(run_id), system.reports_stored()

    work, reports = scenario(steps)
    assert work["status"] == "ERROR" and len(reports) == 1
    assert "): failed." in sent(reports[0])
    assert reports[0]["run_data"]["metadata"][FINISHED_WORK_REPORT_METADATA_KEY]["status"] == "ERROR"


def test_a_cancelled_run_is_reported_as_cancelled(system):
    async def steps():
        run_id = await system.start()
        if system.queue is not None:
            # Still waiting on the queue: the ticket is cancelled before any worker takes it.
            assert await system.queue.acancel_queued(run_id) is True
        else:
            await asyncio.sleep(0.05)
            await system.writer.acancel_run(run_id)
        await system.finish()
        return system.row(run_id), system.reports_stored()

    work, reports = scenario(steps)
    assert work["status"] == "CANCELLED" and len(reports) == 1
    assert "): cancelled." in sent(reports[0])


def test_a_run_that_pauses_for_a_person_is_reported_as_paused(system):
    from agno.tools import tool

    @tool(requires_confirmation=True)
    def publish() -> str:
        """Publish the page."""
        return "published"

    async def steps():
        system.writer.tools = [publish]
        system.writer.model.script = [("publish", {})]
        run_id = await system.start()
        await system.finish()
        return system.row(run_id), system.reports_stored()

    work, reports = scenario(steps)
    assert work["status"] == "PAUSED" and len(reports) == 1
    assert "): paused for a person." in sent(reports[0])


def test_a_task_run_that_ends_is_reported_and_the_task_stays_in_review(tmp_path):
    system = System(tmp_path, queue=True, company=True)

    async def steps():
        add = {"title": "Draft", "brief": "Write", "start": True, "executor_type": "agent", "executor_id": "writer"}
        run = await system.say("Do the draft task now", ("add_company_task", add))
        listed = (await system.os.manager.aget_session_state(session_id=CHAT))[LINKED_WORK_KEY]
        task_id = listed[0]["id"]
        assert "Queued" in run.tools[0].result, run.tools[0].result
        system.chat.scripts.append([("get_company_task_status", {"task_id": task_id})])
        await system.finish()
        return task_id, system.db.get_task(task_id), system.reports_stored()

    task_id, task, reports = scenario(steps)
    system.close()
    assert len(reports) == 1
    assert f"Task {task_id}: its run {task['job_id']} is finished." in sent(reports[0])
    assert reports[0]["run_data"]["metadata"][FINISHED_WORK_REPORT_METADATA_KEY] == {
        "kind": "task",
        "id": task_id,
        "status": "COMPLETED",
    }
    # The finished-work report read the Task and decided nothing: it still waits for the person's review.
    assert task["status"] == "in_review"
    assert '"status": "in_review"' in content(reports[0])


# ----------------------------------------------------------------- it does not fire


def test_work_that_names_no_conversation_tells_nobody(system, monkeypatch):
    import httpx

    told = []
    monkeypatch.setattr(run_background, "notify_requester", lambda *a, **k: told.append(a))
    reads = []
    if system.queue is not None:
        get_job = system.queue.store.get_job

        async def counted(job_id):
            reads.append(job_id)
            return await get_job(job_id)

        monkeypatch.setattr(system.queue.store, "get_job", counted)

    async def steps():
        # A run a client started through the route, as any background run is.
        # It carries metadata of its own, and tries to name a conversation: the route strips that key.
        metadata = json.dumps({"ticket": 7, REQUESTED_FROM_METADATA_KEY: {"session_id": CHAT, "team_id": "superagent"}})
        form = {
            "message": "Go",
            "stream": "false",
            "background": "true",
            "session_id": "elsewhere",
            "metadata": metadata,
        }
        transport = httpx.ASGITransport(app=system.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://agentos") as client:
            response = await client.post("/agents/writer/runs", data=form)
        assert response.status_code == 202, response.text
        reads.clear()
        await system.finish()
        return system.row(response.json()["run_id"])

    work = scenario(steps)
    assert work["status"] == "COMPLETED" and work["run_data"]["metadata"] == {"ticket": 7}
    assert told == [] and not run_background._requester_notices
    # The ticket of such a run is not read again to find out how it ended.
    assert reads == []


def test_a_request_cannot_name_a_conversation_or_mark_itself(plain):
    assert {REQUESTED_FROM_METADATA_KEY, FINISHED_WORK_REPORT_METADATA_KEY} <= RESERVED_RUN_METADATA_KEYS
    from agno.os.utils import stamp_component_version

    forged = {
        FINISHED_WORK_REPORT_METADATA_KEY: {"kind": "run"},
        REQUESTED_FROM_METADATA_KEY: {"session_id": CHAT},
        "a": 1,
    }
    kwargs = {"metadata": forged}
    stamp_component_version(kwargs, None)
    assert kwargs["metadata"] == {"a": 1}


def test_a_conversation_that_does_not_list_the_work_is_not_told(plain):
    async def steps():
        run_id = await plain.start()
        notify = run_background.notify_requester
        run_background.notify_requester = lambda *a, **k: None
        try:
            await plain.finish()
        finally:
            run_background.notify_requester = notify
        asked = {"session_id": CHAT, "run_id": "r", "team_id": "superagent", "user_id": "alice"}
        ended = {"kind": "run", "id": run_id, "status": "COMPLETED"}
        # A run that names the conversation, which the conversation never started.
        await plain.reports(asked, {**ended, "id": "not-listed"}, None)
        # A Task under the id of a run the conversation did start.
        await plain.reports(asked, {**ended, "kind": "task"}, None)
        # A conversation that does not exist, and work that says another team asked for it.
        await plain.reports({**asked, "session_id": "nowhere"}, ended, None)
        await plain.reports({**asked, "team_id": "crew"}, ended, None)
        await plain.settle()
        none = len(plain.reports_stored())
        # A conversation of the same id that is not Super Agent's.
        session = plain.db.get_session(CHAT, deserialize=False)
        read = FinishedWorkReports._read

        async def another_teams(db, session_id):
            _, rows = await read(db, session_id)
            return {**session, "team_id": "crew"}, rows

        plain.reports._read = another_teams
        await plain.reports(asked, ended, None)
        await plain.settle()
        other = len(plain.reports_stored())
        del plain.reports._read
        # The run the conversation started, told as it is.
        await plain.reports(asked, ended, None)
        await plain.settle()
        return none, other, len(plain.reports_stored())

    assert scenario(steps) == (0, 0, 1)


def test_the_switch_off_starts_no_finished_work_report(tmp_path):
    system = System(tmp_path, report_finished_work=False)

    async def steps():
        run_id = await system.start()
        await system.finish()
        return system.row(run_id), system.turns()

    work, turns = scenario(steps)
    system.close()
    assert work["status"] == "COMPLETED" and len(turns) == 1
    assert OSManager().report_finished_work is True


# ----------------------------------------------------------------- only when idle


@pytest.mark.parametrize("stored_when_it_starts", [True, False])
def test_a_conversation_with_a_turn_going_is_not_interrupted(system, stored_when_it_starts):
    # Super Agent stores a turn as running when it starts. With that off, only this process knows
    # the turn is going, and that alone must hold the report back.
    system.os.manager._store_run_in_flight = stored_when_it_starts

    async def steps():
        run_id = await system.start()
        turn = await system.say_held("What is 17 times 23?")
        assert [finished_work._status(row) for row in system.turns()][1:] == (
            ["RUNNING"] if stored_when_it_starts else []
        )
        await system.finish()
        assert system.row(run_id)["status"] == "COMPLETED"
        assert system.reports_stored() == []
        GATES["chat"].set()
        await turn
        GATES["chat"] = None
        await system.settle()
        # The finish is shown on the person's next message instead.
        await system.say("Anything else?")
        await system.settle()
        return system.reports_stored(), system.chat.runs[-1]["sent"]

    reports, shown = scenario(steps)
    assert reports == []
    assert "Changed since your last turn." in shown[0] and shown[1] == "Anything else?"


def test_a_turn_going_when_the_work_ends_means_no_finished_work_report_even_if_it_ends_at_once(system, monkeypatch):
    monkeypatch.setattr(finished_work, "SETTLE_SECONDS", 0.6)

    async def steps():
        run_id = await system.start()
        turn = await system.say_held("What is 17 times 23?")
        GATES["writer"].set()
        for _ in range(300):
            await system.work()
            if system.row(run_id)["status"] == "COMPLETED":
                break
            await asyncio.sleep(0.01)
        # Long enough for the notice to look at the conversation, far less than the wait for other work.
        await asyncio.sleep(0.1)
        # The person's turn ends right after the work did, well before the wait for other work is over.
        GATES["chat"].set()
        await turn
        GATES["chat"] = None
        await asyncio.sleep(1.0)
        await system.settle()
        return system.row(run_id)["status"], system.reports_stored()

    assert scenario(steps) == ("COMPLETED", [])


def test_two_runs_ending_together_get_one_finished_work_report_that_shows_both(system):
    async def steps():
        await system.start()
        await system.start("workflow", "investigator")
        await system.finish("writer", "investigator")
        return system.reports_stored(), system.chat.runs[-1]["sent"]

    reports, shown = scenario(steps)
    assert len(reports) == 1
    block, note = shown
    assert block.count("Changed since your last turn.") == 2
    assert 'agent "Writer"' in block and 'workflow "Investigator"' in block
    assert note.startswith(FINISHED_WORK_LABEL)


def test_work_that_ends_a_moment_later_is_reported_by_the_same_finished_work_report(system, monkeypatch):
    monkeypatch.setattr(finished_work, "SETTLE_SECONDS", 0.6)

    async def steps():
        first = await system.start()
        await system.start("workflow", "investigator")
        GATES["writer"].set()
        for _ in range(300):
            await system.work()
            if system.row(first)["status"] == "COMPLETED":
                break
            await asyncio.sleep(0.01)
        # The second ends after the first was told, inside the wait for other work.
        await asyncio.sleep(0.15)
        GATES["investigator"].set()
        await system.settle()
        await asyncio.sleep(1.0)
        await system.settle()
        return system.reports_stored(), system.chat.runs[-1]["sent"]

    reports, shown = scenario(steps)
    assert len(reports) == 1
    assert shown[0].count("Changed since your last turn.") == 2


def test_a_finished_work_report_ending_starts_no_other(system):
    async def steps():
        await system.start()
        await system.finish()
        told = []
        notify = run_background.notify_requester
        run_background.notify_requester = lambda *a, **k: told.append(a)
        try:
            await system.settle()
        finally:
            run_background.notify_requester = notify
        return system.reports_stored(), told

    reports, told = scenario(steps)
    assert len(reports) == 1 and told == []
    # The finished-work report names no conversation as having asked for it.
    assert REQUESTED_FROM_METADATA_KEY not in reports[0]["run_data"]["metadata"]


def test_work_reported_once_is_not_reported_again(system):
    async def steps():
        run_id = await system.start()
        await system.finish()
        asked = {"session_id": CHAT, "run_id": "r", "team_id": "superagent", "user_id": "alice"}
        # The same end told a second time, as a sweep on another server could.
        await system.reports(asked, {"kind": "run", "id": run_id, "status": "COMPLETED"}, None)
        await system.settle()
        return system.reports_stored()

    assert len(scenario(steps)) == 1


def test_no_more_than_the_limit_while_nobody_speaks(system):
    assert FINISHED_WORK_REPORT_LIMIT == 3

    async def steps():
        for name in WRITERS:
            await system.start("agent", name)
        for name in WRITERS:
            await system.finish(name)
        before = len(system.reports_stored())
        # The person speaks: what they were not told is in the block, and the count starts again.
        await system.say("What happened?")
        shown = system.chat.runs[-1]["sent"][0]
        await system.start("workflow", "investigator")
        await system.finish("investigator")
        return before, shown, len(system.reports_stored())

    before, shown, after = scenario(steps)
    assert before == FINISHED_WORK_REPORT_LIMIT
    assert shown.count("Changed since your last turn.") == len(WRITERS) - FINISHED_WORK_REPORT_LIMIT
    assert after == FINISHED_WORK_REPORT_LIMIT + 1


def test_stored_runs_decide_busy_and_the_count():
    now = time.time()

    def row(status, **more):
        return {"status": status, "created_at": now, "run_data": {}, "run_id": "r", **more}

    assert finished_work._busy([row("COMPLETED"), row("ERROR"), row("CANCELLED")], now) is False
    for status in ("PENDING", "RUNNING", "PAUSED"):
        assert finished_work._busy([row(status), row("COMPLETED")], now) is True
    # A run its server lost is stored as going for ever. A paused run waits for a person however long.
    old = now - finished_work._LOST_AFTER_SECONDS - 1
    assert finished_work._busy([row("RUNNING", created_at=old)], now) is False
    assert finished_work._busy([row("PENDING", created_at=old, updated_at=old)], now) is False
    assert finished_work._busy([row("PAUSED", created_at=old)], now) is True
    # A paused turn waits only until the person speaks again. A finished-work report after it is not the person.
    spoke = row("COMPLETED", run_data={"input": {"input_content": "Hello"}})
    report = row("COMPLETED", run_data={"metadata": {FINISHED_WORK_REPORT_METADATA_KEY: {"kind": "run"}}})
    member = row("COMPLETED", run_data={}, parent_run_id="a-member-run")
    assert finished_work._busy([spoke, row("PAUSED")], now) is False
    assert finished_work._busy([report, member, row("PAUSED")], now) is True
    assert finished_work._busy([row("RUNNING"), spoke, row("PAUSED")], now) is True

    marked = {"metadata": {FINISHED_WORK_REPORT_METADATA_KEY: {"kind": "run"}}}
    labelled = {"input": {"input_content": FINISHED_WORK_LABEL + ". The person did not write this"}}
    person = {"input": {"input_content": "Hello"}}
    rows = [
        row("COMPLETED", run_data=marked),
        row("COMPLETED", run_data={}, parent_run_id="a-member-run"),
        row("CANCELLED", run_data=labelled),
        row("COMPLETED", run_data=person, run_id="the-persons-run"),
        row("COMPLETED", run_data=marked),
    ]
    assert finished_work._given(rows) == (2, "the-persons-run")
    assert finished_work._given([]) == (0, "")


# ----------------------------------------------------------------- it reads and reports only


def marked(session=CHAT, user="alice", authority=None):
    mark = {FINISHED_WORK_REPORT_METADATA_KEY: {"kind": "run", "id": "r", "status": "COMPLETED"}}
    return RunContext(
        run_id="report", session_id=session, user_id=user, session_state={}, metadata=mark, authorization=authority
    )


def all_tools(team, async_mode=True):
    from agno.tools import Toolkit

    found = {}
    for tool in team.tools:
        if isinstance(tool, Toolkit):
            found.update(tool.get_async_functions() if async_mode else tool.get_functions())
    return found


REFUSED = {
    # Runs and starts
    "run_agent",
    "run_team",
    "run_workflow",
    "start_background_run",
    # Platform checks that reach outside the stored records
    "run_diagnostics",
    # Company writes
    "update_company_details",
    "confirm_company_details",
    "add_goal_source",
    "read_goal_source",
    "intake_goal_source",
    "create_company_goal",
    "create_goal_routine",
    "propose_company_project",
    "propose_company_task",
    "edit_company_project",
    "edit_company_task",
    "update_company_task_context",
    # Decisions that are a person's
    "add_company_task",
    "move_company_task",
    "start_company_task",
    "message_company_task",
    "approve_company_project",
    "accept_company_task",
    "review_company_task",
    "turn_on_routine_auto_accept",
    "turn_off_routine_auto_accept",
    # File writes
    "write_company_file",
    "save_company_page",
    "delete_company_file",
}


@pytest.fixture
def company(tmp_path):
    value = System(tmp_path, queue=True, company=True, root=str(tmp_path))
    yield value
    value.close()


@pytest.mark.parametrize("async_mode", [True, False], ids=["async", "sync"])
def test_every_tool_of_super_agent_is_either_a_read_or_refused(company, async_mode):
    tools = all_tools(company.os.manager, async_mode)
    # The whole list: a tool added to Super Agent later fails here until it is classified.
    assert set(tools) == REFUSED | (READ_TOOLS & set(tools))
    assert REFUSED.isdisjoint(READ_TOOLS)
    called = []

    def ran(**arguments):
        called.append(arguments)
        return "ran"

    for name in sorted(REFUSED | {"delegate_task_to_member", "update_user_memory", "a_tool_added_by_the_app"}):
        assert finished_work.finished_work_gate(name, ran, {"a": 1}, marked()) == FINISHED_WORK_REPORT_REFUSAL, name
    assert called == []
    for name in sorted(READ_TOOLS):
        assert finished_work.finished_work_gate(name, ran, {"a": 1}, marked()) == "ran", name
    assert len(called) == len(READ_TOOLS)
    # Every other run is untouched.
    person = RunContext(run_id="r", session_id=CHAT, user_id="alice", session_state={}, metadata={"a": 1})
    assert finished_work.finished_work_gate("accept_company_task", ran, {}, person) == "ran"
    assert finished_work.finished_work_gate("accept_company_task", ran, {}, None) == "ran"


@pytest.mark.parametrize("async_mode", [True, False], ids=["async", "sync"])
def test_a_finished_work_report_is_offered_only_reads_and_no_member(company, async_mode):
    hook = next(h for h in company.os.manager.pre_hooks if isinstance(h, finished_work.FinishedWorkBoundary))
    report = marked()
    if async_mode:
        asyncio.run(hook.async_check(run_context=report, team=company.os.manager))
    else:
        hook.check(run_context=report, team=company.os.manager)
    offered = {function.name for function in report.tools}
    assert offered == READ_TOOLS & set(all_tools(company.os.manager, async_mode))
    assert {"check_background_run", "get_company_task_status", "read_company_file", "read_file"} <= offered
    assert not any(function.requires_confirmation for function in report.tools)
    assert report.members == []
    # A run of the person keeps the team's own tools and members.
    person = RunContext(run_id="r", session_id=CHAT, user_id="alice", session_state={})
    hook.check(run_context=person, team=company.os.manager)
    assert person.tools is None and person.members is None
    assert finished_work._latest_run[CHAT] == ("r", False)


def test_the_gate_is_on_a_report_finished_work_own_team_and_never_on_the_served_one(company):
    team = company.os.manager
    boundary = next(hook for hook in team.pre_hooks if isinstance(hook, finished_work.FinishedWorkBoundary))
    assert team.tool_hooks is None and boundary.served() is team
    assert not company.writer.tool_hooks and not company.os._manager.builder.tool_hooks
    # A finished-work report runs on a copy of the Team, as every request and queued run does: the copy gets the gate.
    copy = team.deep_copy()
    copied = next(hook for hook in copy.pre_hooks if isinstance(hook, finished_work.FinishedWorkBoundary))
    assert copied.served() is team
    copied.check(run_context=marked(), team=copy)
    assert copy.tool_hooks == [finished_work.finished_work_gate] and team.tool_hooks is None
    # The copy also reads the stored state again each time it saves; the served Team saves as it always did.
    assert {"save_session", "asave_session"} <= set(vars(copy)) and "asave_session" not in vars(team)
    # A turn of the person on a copy, and a finished-work report run on the served Team itself, leave hooks alone.
    other = team.deep_copy()
    copied.check(run_context=RunContext(run_id="r", session_id=CHAT, user_id="alice", session_state={}), team=other)
    boundary.check(run_context=marked(), team=team)
    assert other.tool_hooks is None and team.tool_hooks is None
    assert "asave_session" not in vars(other) and "asave_session" not in vars(team)


@pytest.mark.parametrize("reports", [True, False], ids=["finished-work reports on", "finished-work reports off"])
def test_a_tools_own_hooks_still_run_on_the_persons_turns(tmp_path, reports):
    from agno.tools import tool

    audited = []

    def audit(function_name, function_call, arguments):
        audited.append(function_name)
        return function_call(**arguments)

    @tool(tool_hooks=[audit])
    def lookup(key: str) -> str:
        """Look a key up."""
        return "value of " + key

    system = System(tmp_path, tools=[lookup], report_finished_work=reports)

    async def steps():
        first = await system.say("Look it up", ("lookup", {"key": "a"}))
        # Also after a finished-work report ran in the conversation.
        await system.start()
        await system.finish()
        second = await system.say("Again", ("lookup", {"key": "b"}))
        return first.tools[0].result, second.tools[0].result, len(system.reports_stored())

    assert scenario(steps) == ("value of a", "value of b", 1 if reports else 0)
    system.close()
    assert audited == ["lookup", "lookup"]


PERSON_ONLY = [
    ("add_company_task", {"title": "T", "brief": "B", "start": True}),
    ("move_company_task", {"task_id": "t", "project_id": "p"}),
    ("start_company_task", {"task_id": "t"}),
    ("message_company_task", {"task_id": "t", "message": "Add a section on permissions"}),
    ("approve_company_project", {"project_id": "p", "reason": "ok"}),
    ("accept_company_task", {"task_id": "t", "executor_type": "agent", "executor_id": "writer", "reason": "ok"}),
    ("review_company_task", {"task_id": "t", "decision": "complete", "reason": "ok"}),
    ("turn_on_routine_auto_accept", {"routine_id": "r"}),
    ("turn_off_routine_auto_accept", {"routine_id": "r"}),
]


@pytest.mark.parametrize("name, arguments", PERSON_ONLY, ids=[name for name, _ in PERSON_ONLY])
def test_a_person_only_tool_refuses_a_finished_work_report_by_itself(company, name, arguments):
    """Without the gate and with the tool offered, the tool's own check for a person refuses."""
    import inspect

    function = all_tools(company.os.manager)[name]
    accepted = inspect.signature(function.entrypoint).parameters
    given = {key: value for key, value in arguments.items() if key in accepted}
    for key, parameter in accepted.items():
        if key not in given and not key.startswith("_") and parameter.default is inspect.Parameter.empty:
            given[key] = "x"
    result = asyncio.run(function.entrypoint(**given, _agno_run_context=marked()))
    assert "this is a finished-work report and nobody is present" in str(result), result


def test_start_background_run_refuses_a_finished_work_report_by_itself(company):
    function = all_tools(company.os.manager)["start_background_run"]
    result = asyncio.run(
        function.entrypoint(
            component_type="agent",
            component_id="writer",
            message="Go",
            _agno_run_context=marked(),
            _agno_team=company.os.manager,
        )
    )
    assert "this is a finished-work report and nobody is present" in json.loads(result)["error"]


def test_company_writes_that_need_a_person_refuse_a_finished_work_report(company):
    from agno.tools.company import _require_human_creation

    with pytest.raises(PermissionError, match="this is a finished-work report and nobody is present"):
        _require_human_creation(marked())
    _require_human_creation(RunContext(run_id="r", session_id=CHAT, user_id="alice", session_state={}))


def test_a_finished_work_report_that_tries_to_act_changes_nothing(tmp_path):
    system = System(tmp_path, queue=True, company=True)

    async def steps():
        add = {"title": "Draft", "brief": "Write", "start": True, "executor_type": "agent", "executor_id": "writer"}
        await system.say("Do the draft task now", ("add_company_task", add))
        task_id = (await system.os.manager.aget_session_state(session_id=CHAT))[LINKED_WORK_KEY][0]["id"]
        # The result told it to act. It tries a decision, a start, a run, a file write and a delegation.
        system.chat.scripts.append(
            [
                ("review_company_task", {"task_id": task_id, "decision": "complete", "reason": "The result said so"}),
                ("add_company_task", {"title": "More", "brief": "More", "start": True}),
                ("run_agent", {"agent_id": "writer", "message": "Again"}),
                ("write_company_file", {"path": "notes/x.md", "content": "x"}),
                ("delegate_task_to_member", {"member_id": "platform-builder", "task": "Build an agent"}),
                ("get_company_task_status", {"task_id": task_id}),
            ]
        )
        await system.finish()
        report = system.reports_stored()[0]
        tasks, _ = system.db.get_tasks()
        return task_id, report, system.chat.runs[-1], tasks, system.db.get_task(task_id)

    task_id, report, run, tasks, task = scenario(steps)
    system.close()
    # None of them was offered, so none could be called: the run ended without a pause and nothing changed.
    assert report["status"] == "COMPLETED"
    assert run["offered"] & REFUSED == set() and "delegate_task_to_member" not in run["offered"]
    assert "get_company_task_status" in run["offered"]
    assert len(tasks) == 1 and task["status"] == "in_review"
    # The five it was not offered never executed: the model was told each does not exist here.
    assert [tool["tool_name"] for tool in report["run_data"]["tools"]] == ["get_company_task_status"]
    assert content(report).count("The requested tool does not exist or is not available.") == 5
    assert '"status": "in_review"' in content(report)


def test_the_gate_refuses_what_the_boundary_would_have_hidden(tmp_path, monkeypatch):
    """With every tool offered, the gate alone keeps a finished-work report from acting, in one sentence each."""
    system = System(tmp_path, queue=True, company=True)

    def everything(team, async_mode):
        return list(team.tools)

    monkeypatch.setattr(finished_work.FinishedWorkBoundary, "_reads", staticmethod(everything))

    async def steps():
        add = {"title": "Draft", "brief": "Write", "start": True, "executor_type": "agent", "executor_id": "writer"}
        await system.say("Do the draft task now", ("add_company_task", add))
        system.chat.scripts.append(
            [
                ("add_company_task", {"title": "More", "brief": "More", "start": True}),
                ("run_agent", {"agent_id": "writer", "message": "Again"}),
                ("write_company_file", {"path": "notes/x.md", "content": "x"}),
            ]
        )
        await system.finish()
        tasks, _ = system.db.get_tasks()
        return system.reports_stored()[0], tasks

    report, tasks = scenario(steps)
    system.close()
    assert len(tasks) == 1 and report["status"] == "COMPLETED"
    results = [tool["result"] for tool in report["run_data"]["tools"]]
    assert results == [FINISHED_WORK_REPORT_REFUSAL] * 3


def test_the_prompt_says_what_a_finished_work_report_is():
    from agno.os.manager.prompts import MANAGER_INSTRUCTIONS

    assert f'A message that starts "{FINISHED_WORK_LABEL}"' in MANAGER_INSTRUCTIONS
    assert "report what ended and what waits on the\n  person, and change nothing" in MANAGER_INSTRUCTIONS


def test_the_note_carries_no_result_text(system):
    async def steps():
        system.writer.model.script = []
        run_id = await system.start()
        await system.finish()
        return system.row(run_id), system.reports_stored()[0]

    work, report = scenario(steps)
    assert content(work) == "done"
    lines = sent(report).split("\n")
    assert len(lines) == 3 and len(sent(report)) < 900
    assert "Change nothing" in lines[2] and "Read each result with your tools" in lines[2]
    assert 'report every item that "Work started from this conversation" marks' in lines[2]


# ----------------------------------------------------------------- whose authority


@pytest.mark.parametrize("queue", [False, True], ids=["in-memory", "durable-queue"])
def test_a_finished_work_report_runs_as_the_person_with_their_saved_authority(tmp_path, queue):
    system = System(tmp_path, queue=queue, authorization=True)

    async def steps():
        await system.start()
        await system.finish()
        return system.reports_stored(), system.chat.runs[-1]["authority"]

    reports, authority = scenario(steps)
    system.close()
    assert len(reports) == 1 and reports[0]["user_id"] == "alice"
    assert authority.context.principal_id == "alice" and authority.context.scopes == SCOPES
    assert authority.service_account is False and authority.scheduled is False


def test_work_with_no_saved_authority_starts_nothing_where_permissions_are_checked(tmp_path):
    system = System(tmp_path, authorization=True)

    async def steps():
        run_id = await system.start()
        notify = run_background.notify_requester
        run_background.notify_requester = lambda *a, **k: None
        try:
            await system.finish()
        finally:
            run_background.notify_requester = notify
        asked = {"session_id": CHAT, "run_id": "r", "team_id": "superagent", "user_id": "alice"}
        work = {"kind": "run", "id": run_id, "status": "COMPLETED"}
        alice = system.authority().snapshot()
        # No authority, a service account's, a schedule's, another person's: none of them is the person's own.
        await system.reports(asked, work, None)
        await system.reports(asked, work, {**alice, "service_account": True})
        await system.reports(asked, work, {**alice, "scheduled": True})
        await system.reports(asked, work, {**alice, "company_executor": True})
        await system.reports(asked, work, system.authority("bob").snapshot())
        # A run that says another person asked for it.
        await system.reports({**asked, "user_id": "bob"}, work, alice)
        await system.settle()
        none = len(system.reports_stored())
        await system.reports(asked, work, alice)
        await system.settle()
        return none, len(system.reports_stored())

    assert scenario(steps) == (0, 1)
    system.close()


@pytest.mark.parametrize("queue", [False, True], ids=["in-memory", "durable-queue"])
def test_under_user_isolation_the_finished_work_report_is_the_persons(tmp_path, queue):
    system = System(tmp_path, queue=queue, user_isolation=True)

    async def steps():
        await system.start()
        await system.start("workflow", "investigator", user="bob", session="bobs-chat")
        await system.finish("writer", "investigator")
        return system.reports_stored(), system.reports_stored("bobs-chat")

    alice, bob = scenario(steps)
    system.close()
    assert [row["user_id"] for row in alice] == ["alice"] and [row["user_id"] for row in bob] == ["bob"]
    assert 'agent "Writer"' in sent(alice[0]) and 'workflow "Investigator"' in sent(bob[0])


def test_under_user_isolation_a_conversation_with_no_person_is_not_told(tmp_path):
    system = System(tmp_path, user_isolation=True)
    session = {"team_id": "superagent", "user_id": None}
    assert system.reports._authority(system.os, None, session["user_id"]) == (None, False)
    assert system.reports._authority(system.os, None, "alice") == (None, True)
    system.close()


# ----------------------------------------------------------------- a failure in the notice


@pytest.mark.parametrize("failure", ["raises", "hangs", "start-raises"])
def test_a_failing_notice_leaves_the_work_as_it_was(system, monkeypatch, failure):
    async def outcome():
        run_id = await system.start()
        await system.finish()
        ticket = await system.queue.store.get_job(run_id) if system.queue is not None else None
        row = system.row(run_id)
        kept = {key: row["run_data"].get(key) for key in ("status", "content")}
        return row["status"], kept, (ticket or {}).get("status"), (ticket or {}).get("attempt")

    hung = asyncio.Event() if False else None

    async def broken(requested_from, work, authority):
        if failure == "raises":
            raise RuntimeError("the notice broke")
        await asyncio.Event().wait()

    async def steps():
        if failure == "start-raises":

            async def refuse(*args, **kwargs):
                raise RuntimeError("the route broke")

            monkeypatch.setattr(FinishedWorkReports, "_start", refuse)
        else:
            run_background._requester_listeners.insert(0, broken)
        try:
            started = time.monotonic()
            result = await asyncio.wait_for(outcome(), timeout=20)
            return result, time.monotonic() - started
        finally:
            if broken in run_background._requester_listeners:
                run_background._requester_listeners.remove(broken)
            for task in list(run_background._requester_notices):
                task.cancel()

    assert hung is None
    result, seconds = scenario(steps)
    assert result[0] == "COMPLETED" and result[1] == {"status": "COMPLETED", "content": "done"}
    if system.queue is not None:
        # Settled once, on its first attempt: nothing ran the work again.
        assert result[2:] == ("completed", 1)
    assert seconds < 15


def test_the_notice_returns_before_its_listeners_run(plain):
    async def steps():
        order = []

        async def slow(requested_from, work, authority):
            await asyncio.sleep(0.05)
            order.append("listener")

        run_background._requester_listeners.append(slow)
        try:
            run_background.notify_requester({"session_id": "s"}, {"kind": "run", "id": "r"}, None)
            order.append("returned")
            await asyncio.wait(list(run_background._requester_notices))
        finally:
            run_background._requester_listeners.remove(slow)
        # Nothing that names no conversation starts a task at all.
        run_background.notify_requester(None, {"kind": "run", "id": "r"}, None)
        run_background.notify_requester({}, {"kind": "run", "id": "r"}, None)
        return order, len(run_background._requester_notices)

    assert scenario(steps) == (["returned", "listener"], 0)


def test_the_lifespan_registers_the_listener_and_takes_it_away(tmp_path):
    from fastapi.testclient import TestClient

    system = System(tmp_path)
    before = list(run_background._requester_listeners)
    with TestClient(system.app):
        added = [item for item in run_background._requester_listeners if item not in before]
        assert len(added) == 1 and isinstance(added[0], FinishedWorkReports)
    assert run_background._requester_listeners == before
    system.close()


# ----------------------------------------------------------------- while a finished-work report is going


class HeldReports(Chat):
    """Super Agent's model, which holds a finished-work report at GATES["report"] and lets every other run through."""

    async def ainvoke(self, messages, tools=None, **kwargs):
        fresh = [m for m in messages if not m.from_history and m.role == "user"]
        if any(str(m.content).startswith(FINISHED_WORK_LABEL) for m in fresh):
            if GATES.get("report") is not None:
                await GATES["report"].wait()
        elif GATES.get("chat") is not None:
            self.held += 1
            await GATES["chat"].wait()
        return self.invoke(messages, tools=tools, **kwargs)


@pytest.fixture(params=[False, True], ids=["in-memory", "durable-queue"])
def held(request, tmp_path):
    value = System(tmp_path, queue=request.param)
    value.chat = HeldReports()
    value.os.manager.model = value.chat
    yield value
    value.close()


def listed(system):
    session = system.db.get_session(CHAT, deserialize=False)
    entries = ((session.get("session_data") or {}).get("session_state") or {}).get(LINKED_WORK_KEY, [])
    return {entry.get("component_id"): entry.get("shown") for entry in entries}


def test_a_message_sent_while_a_finished_work_report_is_going_keeps_the_work_it_starts(held, monkeypatch):
    monkeypatch.setattr(finished_work, "_REPORT_POLL_SECONDS", 0.02)

    async def steps():
        GATES["report"] = asyncio.Event()
        await held.start()
        await held.finish("writer")
        going = [row["status"] for row in held.reports_stored()]
        # The person cannot see that a finished-work report is going, and asks for more work.
        second = await held.start("workflow", "investigator")
        after_the_turn = listed(held)
        # The finished-work report ends after the person's turn did.
        GATES["report"].set()
        await held.settle()
        after_the_update = listed(held)
        await held.finish("investigator")
        await asyncio.sleep(0.2)
        await held.settle()
        check = await held.say("Did it finish?", ("check_background_run", {"run_id": second}))
        return going, after_the_turn, after_the_update, len(held.reports_stored()), json.loads(check.tools[0].result)

    going, after_the_turn, after_the_update, reports, checked = scenario(steps)
    assert going[0] in ("PENDING", "RUNNING")
    assert after_the_turn == {"writer": "COMPLETED", "investigator": "LIVE"}
    # The finished-work report, which loaded the state before that turn, kept the run the person started.
    assert after_the_update == {"writer": "COMPLETED", "investigator": "LIVE"}
    assert reports == 2 and checked.get("status") == "COMPLETED", checked


def test_the_state_a_finished_work_report_saves_is_the_stored_one_with_its_own_marks():
    stored = {
        "session_data": {
            "session_state": {
                "other": "kept",
                LINKED_WORK_KEY: [
                    {"kind": "run", "id": "a", "shown": "LIVE", "changed_in": None, "name": "stored name"},
                    {"kind": "run", "id": "b", "shown": "COMPLETED", "changed_in": "the-persons-turn"},
                    {"kind": "run", "id": "new", "shown": "LIVE", "changed_in": None},
                ],
            }
        }
    }

    class Session:
        session_data = {
            "kept": True,
            "session_state": {
                "other": "stale",
                LINKED_WORK_KEY: [
                    # Shown by this finished-work report.
                    {"kind": "run", "id": "a", "shown": "COMPLETED", "changed_in": "report", "name": "old"},
                    # Loaded as running and not marked by it: a turn of the person has since reported it.
                    {"kind": "run", "id": "b", "shown": "LIVE", "changed_in": None},
                    {"kind": "run", "id": "gone", "shown": "COMPLETED", "changed_in": None},
                ],
            },
        }

    session = Session()
    # The finished-work report has replied.
    session.get_run = lambda run_id: type("Run", (), {"status": "COMPLETED"})()
    loaded = session.session_data["session_state"]
    finished_work._keep_stored_state(session, stored, "report")
    # The same dictionary, which the run also holds, now has the stored state with this run's marks.
    assert session.session_data["session_state"] is loaded and session.session_data["kept"] is True
    assert loaded == {
        "other": "kept",
        LINKED_WORK_KEY: [
            {"kind": "run", "id": "a", "shown": "COMPLETED", "changed_in": "report", "name": "stored name"},
            {"kind": "run", "id": "b", "shown": "COMPLETED", "changed_in": "the-persons-turn"},
            {"kind": "run", "id": "new", "shown": "LIVE", "changed_in": None},
        ],
    }
    # Nothing readable stored: the run's own state stands.
    before = dict(loaded)
    finished_work._keep_stored_state(session, None, "report")
    finished_work._keep_stored_state(session, {"session_data": {}}, "report")
    assert loaded == before


class FailingReports(HeldReports):
    """Holds a finished-work report, then fails it where its reply would be."""

    async def ainvoke(self, messages, tools=None, **kwargs):
        fresh = [m for m in messages if not m.from_history and m.role == "user"]
        report = any(str(m.content).startswith(FINISHED_WORK_LABEL) for m in fresh)
        result = await super().ainvoke(messages, tools=tools, **kwargs)
        if report and SEEN.get("report_fails"):
            raise RuntimeError("the model broke")
        return result


@pytest.mark.parametrize("ending", ["fails", "is cancelled"])
def test_a_finished_work_report_that_does_not_finish_keeps_the_work_a_turn_started(held, monkeypatch, ending):
    monkeypatch.setattr(finished_work, "_REPORT_POLL_SECONDS", 0.02)
    held.chat = FailingReports()
    held.os.manager.model = held.chat

    async def steps():
        GATES["report"] = asyncio.Event()
        SEEN["report_fails"] = ending == "fails"
        await held.start()
        await held.finish("writer")
        second = await held.start("workflow", "investigator")
        if ending == "is cancelled":
            report = held.reports_stored()[0]["run_id"]
            await held.os.manager.acancel_run(report)
        GATES["report"].set()
        await held.settle()
        SEEN["report_fails"] = False
        ended = [row["status"] for row in held.reports_stored()]
        after = listed(held)
        await held.finish("investigator")
        await asyncio.sleep(0.2)
        await held.settle()
        check = await held.say("Did it finish?", ("check_background_run", {"run_id": second}))
        return ended, after, json.loads(check.tools[0].result)

    ended, after, checked = scenario(steps)
    assert ended[0] in ("ERROR", "CANCELLED")
    assert after.get("investigator") == "LIVE"
    assert checked.get("status") == "COMPLETED", checked


def test_a_finish_the_person_was_told_in_their_own_turn_is_not_reported_again(held, monkeypatch):
    monkeypatch.setattr(finished_work, "_REPORT_POLL_SECONDS", 0.02)

    async def steps():
        GATES["report"] = asyncio.Event()
        await held.start()
        await held.start("workflow", "investigator")
        await held.finish("writer")
        # The second run ends while the finished-work report for the first is going, and the person asks.
        await held.finish("investigator")
        await held.say("Status?")
        told = held.chat.runs[-1]["sent"][0].count("Changed since your last turn.")
        GATES["report"].set()
        await held.settle()
        await asyncio.sleep(0.3)
        await held.settle()
        after = listed(held)
        await held.say("Thanks")
        return told, after, len(held.reports_stored()), held.chat.runs[-1]["sent"]

    told, after, reports, last = scenario(steps)
    assert told == 2
    # The finished-work report loaded the second run as running. It did not put that back over the turn's mark.
    assert after == {"writer": "COMPLETED", "investigator": "COMPLETED"}
    assert reports == 1
    assert not any("Changed since your last turn." in message for message in last)


def test_work_that_ends_while_a_finished_work_report_is_going_gets_one_of_its_own(held, monkeypatch):
    monkeypatch.setattr(finished_work, "_REPORT_POLL_SECONDS", 0.02)

    async def steps():
        GATES["report"] = asyncio.Event()
        await held.start()
        second = await held.start("workflow", "investigator")
        await held.finish("writer")
        # The second run ends while the first finished-work report, which called it running, is still going.
        await held.finish("investigator")
        during = len(held.reports_stored())
        GATES["report"].set()
        await held.settle()
        await asyncio.sleep(0.3)
        await held.settle()
        shown = [run["sent"] for run in held.chat.runs if run["sent"][-1].startswith(FINISHED_WORK_LABEL)]
        return held.row(second)["status"], shown[0][0], during, held.reports_stored(), shown[-1]

    ended, first_block, during, reports, last = scenario(steps)
    assert ended == "COMPLETED" and during == 1
    assert 'agent "Writer"' in first_block and "finished" in first_block
    assert first_block.count("Changed since your last turn.") == 1
    # It called the second run queued or running. The order of the two lines is not fixed.
    investigator = next(line for line in first_block.split("\n") if 'workflow "Investigator"' in line)
    assert "Changed since your last turn." not in investigator and "finished" not in investigator
    assert len(reports) == 2
    assert 'workflow "Investigator"' in sent(reports[1])
    assert last[0].count("Changed since your last turn.") == 1 and 'workflow "Investigator"' in last[0]


def test_work_a_going_finished_work_report_will_show_gets_no_second_one(held, monkeypatch):
    monkeypatch.setattr(finished_work, "_REPORT_POLL_SECONDS", 0.02)

    async def steps():
        GATES["report"] = asyncio.Event()
        for name in WRITERS[:3]:
            await held.start("agent", name)
        await held.finish("writer")
        # Two more end while the first finished-work report is going. One finished-work report reports both.
        await held.finish("writer-2", "writer-3")
        GATES["report"].set()
        await held.settle()
        await asyncio.sleep(0.3)
        await held.settle()
        return held.reports_stored(), held.chat.runs[-1]["sent"][0]

    reports, block = scenario(steps)
    assert len(reports) == 2
    assert block.count("Changed since your last turn.") == 2


def test_a_turn_of_the_person_while_a_notice_waits_means_no_finished_work_report(held, monkeypatch):
    monkeypatch.setattr(finished_work, "_REPORT_POLL_SECONDS", 0.02)

    async def steps():
        GATES["report"] = asyncio.Event()
        await held.start()
        await held.start("workflow", "investigator")
        await held.finish("writer")
        await held.finish("investigator")
        # The person speaks while the second notice waits for the first finished-work report.
        turn = await held.say_held("What is 17 times 23?")
        GATES["report"].set()
        await held.settle()
        count = len(held.reports_stored())
        GATES["chat"].set()
        await turn
        GATES["chat"] = None
        await held.settle()
        return count, len(held.reports_stored())

    assert scenario(steps) == (1, 1)


# ----------------------------------------------------------------- the two paths that told nobody


def test_a_paused_run_approved_in_the_foreground_is_reported_when_it_finishes(plain):
    import httpx

    from agno.tools import tool

    @tool(requires_confirmation=True)
    def publish() -> str:
        """Publish the page."""
        return "published"

    async def steps():
        plain.writer.tools = [publish]
        plain.writer.model.script = [("publish", {})]
        run_id = await plain.start()
        await plain.finish()
        paused = plain.row(run_id)
        tools = [{**item, "confirmed": True} for item in paused["run_data"]["tools"]]
        # The person approves it on the run's own page: the continue runs in that request.
        transport = httpx.ASGITransport(app=plain.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://agentos") as client:
            response = await client.post(
                f"/agents/writer/runs/{run_id}/continue",
                data={"tools": json.dumps(tools), "session_id": paused["session_id"], "stream": "false"},
            )
        assert response.status_code == 200, response.text
        await plain.settle()
        await asyncio.sleep(0.2)
        await plain.settle()
        return paused["status"], plain.row(run_id)["status"], [sent(u).split("\n")[1] for u in plain.reports_stored()]

    paused, ended, reports = scenario(steps)
    assert (paused, ended) == ("PAUSED", "COMPLETED")
    assert len(reports) == 2
    assert reports[0].endswith("paused for a person.") and reports[1].endswith("finished.")


def test_a_continue_that_names_no_conversation_tells_nobody(plain, monkeypatch):
    told = []
    monkeypatch.setattr(run_background, "notify_requester", lambda *a, **k: told.append(a))

    class Component:
        async def aget_run_output(self, run_id, session_id=None):
            return type("Run", (), {"metadata": {"a": 1}, "status": "COMPLETED", "run_id": run_id})()

    asyncio.run(run_background.anotify_continued_run_requester(Component(), "r", "s"))
    assert told == []
    # With nothing listening, the continued run is not read at all.
    read = []

    class Counted:
        async def aget_run_output(self, run_id, session_id=None):
            read.append(run_id)

    listening = list(run_background._requester_listeners)
    run_background._requester_listeners.clear()
    try:
        asyncio.run(run_background.anotify_continued_run_requester(Counted(), "r", "s"))
    finally:
        run_background._requester_listeners.extend(listening)
    assert read == []


def test_an_in_memory_workflow_with_a_workflow_agent_is_reported(plain):
    from agno.workflow.agent import WorkflowAgent

    async def step(step_input: StepInput) -> StepOutput:
        return StepOutput(content="stepped")

    flow = Workflow(
        id="answerer",
        name="Answerer",
        db=plain.db,
        agent=WorkflowAgent(model=ScriptedModel()),
        steps=[Step(name="s", executor=step)],
    )
    plain.os.workflows.append(flow)
    plain.os.registry.workflows.append(flow)

    async def steps():
        run_id = await plain.start("workflow", "answerer")
        await plain.settle()
        await asyncio.sleep(0.2)
        await plain.settle()
        return plain.row(run_id)["status"], [sent(u).split("\n")[1] for u in plain.reports_stored()]

    status, reports = scenario(steps)
    assert status == "COMPLETED"
    assert reports == [next(iter(reports), "")] and reports[0].startswith('Background run of workflow "Answerer"')
    assert reports[0].endswith("finished.")


# ----------------------------------------------------------------- round two of the review


def notices(system):
    """How each stored finished-work report worded what ended."""
    return [sent(report).split("\n")[1].split("): ")[-1] for report in system.reports_stored()]


def test_a_workflow_agent_that_runs_its_workflow_is_reported(plain):
    from agno.workflow.agent import WorkflowAgent

    async def step(step_input: StepInput) -> StepOutput:
        return StepOutput(content="stepped")

    flow = Workflow(
        id="answerer",
        name="Answerer",
        db=plain.db,
        agent=WorkflowAgent(model=ScriptedModel([("run_workflow", {"query": "go"})])),
        steps=[Step(name="s", executor=step)],
    )
    plain.os.workflows.append(flow)
    plain.os.registry.workflows.append(flow)

    async def steps():
        run_id = await plain.start("workflow", "answerer")
        await plain.settle()
        await asyncio.sleep(0.2)
        await plain.settle()
        row = plain.row(run_id)
        return row["status"], str(row["run_data"].get("content")), notices(plain)

    assert scenario(steps) == ("COMPLETED", "stepped", ["finished."])


def confirmations():
    from agno.tools import tool

    @tool(requires_confirmation=True)
    def publish() -> str:
        """Publish the page."""
        return "published"

    @tool(requires_confirmation=True)
    def announce() -> str:
        """Announce it."""
        return "announced"

    return [publish, announce]


async def approve(system, run_id, **form):
    """Approve what a paused Writer run waits on, through its continue route."""
    import httpx

    paused = system.row(run_id)
    tools = [{**item, "confirmed": True} for item in paused["run_data"]["tools"]]
    if system.queue is not None:
        # The queue owns the continuation of a run it executed.
        form = {"background": "true", **form}
    transport = httpx.ASGITransport(app=system.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://agentos") as client:
        response = await client.post(
            f"/agents/writer/runs/{run_id}/continue",
            data={"tools": json.dumps(tools), "session_id": paused["session_id"], "stream": "false", **form},
        )
    # Answered in the request without the queue, accepted for the queue with it.
    assert response.status_code in (200, 202), response.text


def test_a_run_that_pauses_again_after_an_approval_is_reported_again(system):
    plain = system

    async def steps():
        plain.writer.tools = confirmations()
        plain.writer.model.script = [("publish", {}), ("announce", {})]
        run_id = await plain.start()
        await plain.finish()
        await approve(plain, run_id)
        await plain.settle()
        await asyncio.sleep(0.2)
        await plain.settle()
        second = plain.row(run_id)["status"], notices(plain)
        await approve(plain, run_id)
        await plain.settle()
        await asyncio.sleep(0.2)
        await plain.settle()
        return second, plain.row(run_id)["status"], notices(plain)

    second, ended, reports = scenario(steps)
    assert second == ("PAUSED", ["paused for a person.", "paused for a person."])
    assert ended == "COMPLETED" and reports[-1] == "finished." and len(reports) == 3


def test_a_pause_told_twice_without_a_continue_is_reported_once(plain):
    async def steps():
        plain.writer.tools = confirmations()[:1]
        plain.writer.model.script = [("publish", {})]
        run_id = await plain.start()
        await plain.finish()
        asked = {"session_id": CHAT, "run_id": "r", "team_id": "superagent", "user_id": "alice"}
        await plain.reports(asked, {"kind": "run", "id": run_id, "status": "PAUSED"}, None)
        await plain.settle()
        return notices(plain)

    assert scenario(steps) == ["paused for a person."]


def test_an_approval_through_the_resumable_streaming_continue_is_shown_on_the_next_message(plain):
    """That route has a producer of its own in the agent and team run code, which tells nobody. The
    finish is not lost: the person's next message shows it."""

    async def steps():
        plain.writer.tools = confirmations()[:1]
        plain.writer.model.script = [("publish", {})]
        run_id = await plain.start()
        await plain.finish()
        await approve(plain, run_id, stream="true", background="true")
        for _ in range(200):
            if plain.row(run_id)["status"] == "COMPLETED":
                break
            await asyncio.sleep(0.02)
        await plain.settle()
        await asyncio.sleep(0.3)
        await plain.settle()
        reports = notices(plain)
        await plain.say("Anything new?")
        return plain.row(run_id)["status"], reports, plain.chat.runs[-1]["sent"][0]

    status, reports, block = scenario(steps)
    assert (status, reports) == ("COMPLETED", ["paused for a person."])
    assert 'agent "Writer"' in block and "finished" in block and "Changed since your last turn." in block


def test_an_application_tool_named_like_a_read_is_not_offered_in_a_finished_work_report(tmp_path):
    from agno.tools import tool

    called = []

    @tool
    def read_file(path: str) -> str:
        """Read a file, the application's own way."""
        called.append(path)
        return "content of " + path

    system = System(tmp_path, tools=[read_file])

    async def steps():
        await system.say("Read", ("read_file", {"path": "a"}))
        await system.start()
        system.chat.scripts.append([("read_file", {"path": "b"})])
        await system.finish()
        return system.chat.runs[-1]["offered"], content(system.reports_stored()[0])

    offered, reply = scenario(steps)
    system.close()
    # It ran on the person's turn. A finished-work report is offered the framework's own reads only.
    assert called == ["a"]
    assert "read_file" not in offered and "check_background_run" in offered
    assert "The requested tool does not exist or is not available." in reply


def test_a_confirmation_the_person_talked_past_does_not_silence_the_conversation(tmp_path):
    from agno.tools import tool

    @tool(requires_confirmation=True)
    def decide() -> str:
        """Decide it."""
        return "decided"

    system = System(tmp_path, tools=[decide])

    async def steps():
        paused = await system.say("Decide it", ("decide", {}))
        # The person says something else: they have moved on, and work that ends is reported.
        await system.say("Never mind, leave it")
        await system.start()
        await system.finish()
        return paused.status.value, [row["status"] for row in system.turns()][:1], len(system.reports_stored())

    paused, first, reports = scenario(steps)
    system.close()
    assert (paused, first) == ("PAUSED", ["PAUSED"])
    assert reports == 1


# ----------------------------------------------------------------- the last review


def test_a_conversation_deleted_while_a_finished_work_report_runs_stays_deleted(held):
    async def steps():
        GATES["report"] = asyncio.Event()
        await held.start()
        await held.finish("writer")
        going = [row["status"] for row in held.reports_stored()]
        # The person deletes the conversation while the finished-work report is going.
        assert held.db.delete_session(CHAT) is True
        gone = held.db.get_session(CHAT, deserialize=False)
        GATES["report"].set()
        await held.settle()
        return going, gone, held.db.get_session(CHAT, deserialize=False)

    going, gone, after = scenario(steps)
    assert going[0] in ("PENDING", "RUNNING") and gone is None
    assert after is None


def test_a_conversation_renamed_while_a_finished_work_report_runs_keeps_its_name(held):
    async def steps():
        GATES["report"] = asyncio.Event()
        await held.start()
        await held.finish("writer")
        await held.os.manager.aset_session_name(session_id=CHAT, session_name="Export failure")
        GATES["report"].set()
        await held.settle()
        stored = held.db.get_session(CHAT, deserialize=False)
        return stored["session_data"].get("session_name"), len(held.reports_stored()), listed(held)

    name, reports, entries = scenario(steps)
    assert name == "Export failure"
    assert reports == 1 and entries == {"writer": "COMPLETED"}


@pytest.mark.parametrize("ending", ["fails", "is cancelled"])
def test_a_finished_work_report_that_does_not_reply_leaves_the_finish_unreported(held, ending):
    held.chat = FailingReports()
    held.os.manager.model = held.chat

    async def steps():
        GATES["report"] = asyncio.Event()
        SEEN["report_fails"] = ending == "fails"
        await held.start()
        await held.finish("writer")
        if ending == "is cancelled":
            await held.os.manager.acancel_run(held.reports_stored()[0]["run_id"])
        GATES["report"].set()
        await held.settle()
        SEEN["report_fails"] = False
        ended = [row["status"] for row in held.reports_stored()]
        after = listed(held)
        # Nobody was told, so the person's next message still shows the finish as new.
        await held.say("What changed?")
        return ended, after, held.chat.runs[-1]["sent"][0]

    ended, after, block = scenario(steps)
    assert ended[0] in ("ERROR", "CANCELLED")
    assert after == {"writer": "LIVE"}
    assert 'agent "Writer"' in block and "Changed since your last turn." in block


def test_the_merge_carries_marks_only_once_the_finished_work_report_has_replied():
    def stored():
        entry = {"kind": "run", "id": "a", "shown": "LIVE", "changed_in": None}
        return {"session_data": {"session_name": "New name", "session_state": {LINKED_WORK_KEY: [entry]}}}

    class Session:
        def __init__(self, status):
            self.status = status
            entry = {"kind": "run", "id": "a", "shown": "COMPLETED", "changed_in": "report"}
            self.session_data = {
                "session_name": "Old name",
                "session_metrics": {"total_tokens": 7},
                "session_state": {LINKED_WORK_KEY: [entry]},
            }

        def get_run(self, run_id):
            return type("Run", (), {"status": self.status})() if run_id == "report" else None

    for status, shown in (("COMPLETED", "COMPLETED"), ("ERROR", "LIVE"), ("CANCELLED", "LIVE"), ("RUNNING", "LIVE")):
        session = Session(status)
        finished_work._keep_stored_state(session, stored(), "report")
        assert session.session_data["session_state"][LINKED_WORK_KEY][0]["shown"] == shown, status
        # The name the conversation stored meanwhile is kept, and the totals stay this run's own.
        assert session.session_data["session_name"] == "New name"
        assert session.session_data["session_metrics"] == {"total_tokens": 7}


@pytest.mark.parametrize("async_mode", [True, False], ids=["async", "sync"])
def test_a_read_that_asks_for_a_confirmation_is_not_offered_in_a_finished_work_report(tmp_path, async_mode):
    from agno.tools.workspace import Workspace

    asks = Workspace(root=str(tmp_path), allowed=["list"], confirm=["read", "search"])
    plain_reads = Workspace(root=str(tmp_path))
    offered = finished_work.FinishedWorkBoundary._reads(type("Team", (), {"tools": [asks]})(), async_mode)
    assert [function.name for function in offered] == ["list_files"]
    offered = finished_work.FinishedWorkBoundary._reads(type("Team", (), {"tools": [plain_reads]})(), async_mode)
    assert {function.name for function in offered} == {"read_file", "list_files", "search_content"}


def test_a_finished_work_report_that_saves_before_it_ends_still_marks_what_it_showed():
    """A run that checkpoints saves while it is still running. Its marks wait for the save after its reply."""

    def stored():
        entry = {"kind": "run", "id": "a", "shown": "LIVE", "changed_in": None}
        return {"session_data": {"session_state": {LINKED_WORK_KEY: [entry]}}}

    class Session:
        status = "RUNNING"
        session_data = {
            "session_state": {
                LINKED_WORK_KEY: [{"kind": "run", "id": "a", "shown": "COMPLETED", "changed_in": "report"}]
            }
        }

        def get_run(self, run_id):
            return type("Run", (), {"status": self.status})()

    session, marks = Session(), {}
    finished_work._keep_stored_state(session, stored(), "report", marks)
    # Saved mid-run without the mark, which is kept aside.
    assert session.session_data["session_state"][LINKED_WORK_KEY][0]["shown"] == "LIVE"
    session.status = "COMPLETED"
    finished_work._keep_stored_state(session, stored(), "report", marks)
    assert session.session_data["session_state"][LINKED_WORK_KEY][0] == {
        "kind": "run",
        "id": "a",
        "shown": "COMPLETED",
        "changed_in": "report",
    }
    # A run that fails after a mid-run save still marks nothing.
    session, marks = Session(), {}
    finished_work._keep_stored_state(session, stored(), "report", marks)
    session.status = "ERROR"
    finished_work._keep_stored_state(session, stored(), "report", marks)
    assert session.session_data["session_state"][LINKED_WORK_KEY][0]["shown"] == "LIVE"


def test_a_checkpointing_finished_work_report_reports_two_finishes_once(tmp_path, monkeypatch):
    # Long enough for both runs to end inside the wait, so one finished-work report shows both.
    monkeypatch.setattr(finished_work, "SETTLE_SECONDS", 0.4)
    monkeypatch.setattr(finished_work, "_REPORT_POLL_SECONDS", 0.02)
    system = System(tmp_path)
    system.os.manager.checkpoint = "tool-batch"

    async def steps():
        first = await system.start()
        second = await system.start("workflow", "investigator")
        system.chat.scripts.append(
            [("check_background_run", {"run_id": first}), ("check_background_run", {"run_id": second})]
        )
        await system.finish("writer", "investigator")
        await asyncio.sleep(0.8)
        await system.settle()
        return len(system.reports_stored()), listed(system)

    reports, entries = scenario(steps)
    system.close()
    assert reports == 1
    assert entries == {"writer": "COMPLETED", "investigator": "COMPLETED"}


# ----------------------------------------------------------------- on the reworked linked work


def test_a_mark_set_by_a_tool_read_is_carried_over_too():
    """Linked work records a tool's read of a run as a receipt, not as a change shown in the block."""
    stored = {
        "session_data": {
            "session_state": {
                LINKED_WORK_KEY: [
                    {"kind": "run", "id": "a", "shown": "LIVE", "changed_in": None, "receipt_in": "the-start"},
                    {"kind": "run", "id": "b", "shown": "LIVE", "changed_in": None},
                ]
            }
        }
    }

    class Session:
        session_data = {
            "session_state": {
                LINKED_WORK_KEY: [
                    {"kind": "run", "id": "a", "shown": "COMPLETED", "changed_in": None, "receipt_in": "report"},
                    {"kind": "run", "id": "b", "shown": "COMPLETED", "changed_in": "report"},
                ]
            }
        }

        def get_run(self, run_id):
            return type("Run", (), {"status": "COMPLETED"})()

    session = Session()
    finished_work._keep_stored_state(session, stored, "report")
    assert session.session_data["session_state"][LINKED_WORK_KEY] == [
        {"kind": "run", "id": "a", "shown": "COMPLETED", "changed_in": None, "receipt_in": "report"},
        {"kind": "run", "id": "b", "shown": "COMPLETED", "changed_in": "report"},
    ]


def test_two_finishes_read_with_the_check_tool_are_reported_once(system, monkeypatch):
    monkeypatch.setattr(finished_work, "SETTLE_SECONDS", 0.4)
    monkeypatch.setattr(finished_work, "_REPORT_POLL_SECONDS", 0.02)

    async def steps():
        first = await system.start()
        second = await system.start("workflow", "investigator")
        system.chat.scripts.append(
            [("check_background_run", {"run_id": first}), ("check_background_run", {"run_id": second})]
        )
        await system.finish("writer", "investigator")
        await asyncio.sleep(0.8)
        await system.settle()
        await system.say("Thanks")
        return len(system.reports_stored()), listed(system), system.chat.runs[-1]["sent"]

    reports, entries, last = scenario(steps)
    assert reports == 1
    assert entries == {"writer": "COMPLETED", "investigator": "COMPLETED"}
    assert not any("Changed since your last turn." in message for message in last)


def test_a_model_that_is_not_sent_the_linked_work_gets_no_finished_work_report(system, monkeypatch):
    """Without the block a finished-work report has nothing to report from and nothing to mark."""
    read = []
    real = FinishedWorkReports._read

    async def counted(db, session_id):
        read.append(session_id)
        return await real(db, session_id)

    monkeypatch.setattr(FinishedWorkReports, "_read", staticmethod(counted))

    async def steps():
        run_id = await system.start()
        # Decided from the model Super Agent holds when the work ends.
        system.chat.unlisted = True
        await system.finish()
        without = len(system.reports_stored()), list(read), system.row(run_id)["status"]
        system.chat.unlisted = False
        asked = {"session_id": CHAT, "run_id": "r", "team_id": "superagent", "user_id": "alice"}
        await system.reports(asked, {"kind": "run", "id": run_id, "status": "COMPLETED"}, None)
        await system.settle()
        return without, len(system.reports_stored())

    without, after = scenario(steps)
    # Nothing was started and the conversation was not even read.
    assert without == (0, [], "COMPLETED")
    assert after == 1


def test_the_guard_is_linked_works_own_check():
    """The rule calls linked work's check, so it follows any change to which providers are sent the block."""
    import inspect

    source = inspect.getsource(FinishedWorkReports.__call__)
    assert "linked_work._delivers(manager.team.model)" in source
    assert linked_work._delivers(ScriptedModel()) is True
    unlisted = ScriptedModel()
    unlisted.unlisted = True
    assert linked_work._delivers(unlisted) is False
