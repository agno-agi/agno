"""When work a Super Agent conversation started ends, the conversation gets one run that reports it and
changes nothing."""

import asyncio
import json
import time

import pytest

from agno.agent import Agent
from agno.db.schemas.scheduler import (
    REQUESTED_FROM_METADATA_KEY,
    RESERVED_RUN_METADATA_KEYS,
    WORK_UPDATE_METADATA_KEY,
)
from agno.db.sqlite import SqliteDb
from agno.job_queue import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.os import AgentOS, CompanyConfig, OSManager
from agno.os.authz import Authorization
from agno.os.authz.provider import AuthorizationContext
from agno.os.authz.scope_provider import ScopeAuthorizationProvider
from agno.os.job_queue import QueueWorker
from agno.os.manager import work_update
from agno.os.manager.linked_work import LINKED_WORK_KEY
from agno.os.manager.work_update import (
    READ_TOOLS,
    WORK_UPDATE_LABEL,
    WORK_UPDATE_LIMIT,
    WorkUpdates,
)
from agno.registry import Registry
from agno.run import RunContext
from agno.run import background as run_background
from agno.run.authorization import (
    WORK_UPDATE_REFUSAL,
    RunAuthorization,
    authorization_scope,
    current_authorization,
)
from agno.run.background import await_background_runs
from agno.workflow import Step, StepInput, StepOutput, Workflow
from tests.unit.os.test_mini_agent_tasks import ScriptedModel

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")

SECRET = "work-update-tests-secret-at-least-32-bytes"
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
            id="work-updates",
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
        self.updates = WorkUpdates(self.os, self.app)
        run_background._requester_listeners.append(self.updates)
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
        run_background._requester_listeners.remove(self.updates)
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
        """Wait until nothing moves: no run to take, none ending, no notice or work update in flight.

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

    def updates_stored(self, session=CHAT):
        return [row for row in self.turns(session) if work_update._is_work_update(row)]

    def row(self, run_id):
        return self.db.get_run(run_id, deserialize=False)


def _workflows_going():
    from agno.workflow.workflow import _workflow_background_tasks

    return [task for task in _workflow_background_tasks if not task.done()]


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    GATES.clear()
    SEEN.clear()
    work_update._latest_run.clear()
    monkeypatch.setattr(work_update, "SETTLE_SECONDS", 0.02)
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


def test_a_finished_background_run_gives_the_conversation_a_work_update(system):
    async def steps():
        run_id = await system.start()
        assert system.updates_stored() == []
        system.chat.scripts.append([("check_background_run", {"run_id": run_id})])
        await system.finish()
        return run_id, system.turns(), system.row(run_id)

    run_id, turns, work = scenario(steps)
    assert work["status"] == "COMPLETED"
    assert len(turns) == 2
    update = turns[1]
    assert update["status"] == "COMPLETED" and update["user_id"] == "alice"
    assert sent(update).startswith(WORK_UPDATE_LABEL + ". The person did not write this")
    assert f'Background run of agent "Writer" (run {run_id}): finished.' in sent(update)
    assert update["run_data"]["metadata"][WORK_UPDATE_METADATA_KEY] == {
        "kind": "run",
        "id": run_id,
        "status": "COMPLETED",
    }
    # The reply is the model's, made from the result it read with a tool.
    assert '"status": "COMPLETED"' in content(update)


def test_a_run_started_through_a_workflow_is_reported_too(system):
    async def steps():
        run_id = await system.start("workflow", "investigator")
        await system.finish("investigator")
        return run_id, system.updates_stored()

    run_id, updates = scenario(steps)
    assert len(updates) == 1
    assert f'Background run of workflow "Investigator" (run {run_id}): finished.' in sent(updates[0])


def test_a_failed_run_is_reported_as_failed(system):
    async def steps():
        SEEN["writer_fails"] = True
        run_id = await system.start()
        await system.finish()
        return system.row(run_id), system.updates_stored()

    work, updates = scenario(steps)
    assert work["status"] == "ERROR" and len(updates) == 1
    assert "): failed." in sent(updates[0])
    assert updates[0]["run_data"]["metadata"][WORK_UPDATE_METADATA_KEY]["status"] == "ERROR"


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
        return system.row(run_id), system.updates_stored()

    work, updates = scenario(steps)
    assert work["status"] == "CANCELLED" and len(updates) == 1
    assert "): cancelled." in sent(updates[0])


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
        return system.row(run_id), system.updates_stored()

    work, updates = scenario(steps)
    assert work["status"] == "PAUSED" and len(updates) == 1
    assert "): paused for a person." in sent(updates[0])


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
        return task_id, system.db.get_task(task_id), system.updates_stored()

    task_id, task, updates = scenario(steps)
    system.close()
    assert len(updates) == 1
    assert f"Task {task_id}: its run {task['job_id']} is finished." in sent(updates[0])
    assert updates[0]["run_data"]["metadata"][WORK_UPDATE_METADATA_KEY] == {
        "kind": "task",
        "id": task_id,
        "status": "COMPLETED",
    }
    # The work update read the Task and decided nothing: it still waits for the person's review.
    assert task["status"] == "in_review"
    assert '"status": "in_review"' in content(updates[0])


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
    assert {REQUESTED_FROM_METADATA_KEY, WORK_UPDATE_METADATA_KEY} <= RESERVED_RUN_METADATA_KEYS
    from agno.os.utils import stamp_component_version

    forged = {WORK_UPDATE_METADATA_KEY: {"kind": "run"}, REQUESTED_FROM_METADATA_KEY: {"session_id": CHAT}, "a": 1}
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
        await plain.updates(asked, {**ended, "id": "not-listed"}, None)
        # A Task under the id of a run the conversation did start.
        await plain.updates(asked, {**ended, "kind": "task"}, None)
        # A conversation that does not exist, and work that says another team asked for it.
        await plain.updates({**asked, "session_id": "nowhere"}, ended, None)
        await plain.updates({**asked, "team_id": "crew"}, ended, None)
        await plain.settle()
        none = len(plain.updates_stored())
        # A conversation of the same id that is not Super Agent's.
        session = plain.db.get_session(CHAT, deserialize=False)
        read = WorkUpdates._read

        async def another_teams(db, session_id):
            _, rows = await read(db, session_id)
            return {**session, "team_id": "crew"}, rows

        plain.updates._read = another_teams
        await plain.updates(asked, ended, None)
        await plain.settle()
        other = len(plain.updates_stored())
        del plain.updates._read
        # The run the conversation started, told as it is.
        await plain.updates(asked, ended, None)
        await plain.settle()
        return none, other, len(plain.updates_stored())

    assert scenario(steps) == (0, 0, 1)


def test_the_switch_off_starts_no_work_update(tmp_path):
    system = System(tmp_path, work_updates=False)

    async def steps():
        run_id = await system.start()
        await system.finish()
        return system.row(run_id), system.turns()

    work, turns = scenario(steps)
    system.close()
    assert work["status"] == "COMPLETED" and len(turns) == 1
    assert OSManager().work_updates is True


# ----------------------------------------------------------------- only when idle


def test_a_conversation_with_a_turn_going_is_not_interrupted(system):
    async def steps():
        run_id = await system.start()
        GATES["chat"] = asyncio.Event()
        turn = asyncio.ensure_future(system.say("What is 17 times 23?"))
        await asyncio.sleep(0.05)
        # The person's turn is not stored yet: only this process knows it is going.
        assert len(system.turns()) == 1
        await system.finish()
        assert system.row(run_id)["status"] == "COMPLETED"
        assert system.updates_stored() == []
        GATES["chat"].set()
        await turn
        GATES["chat"] = None
        await system.settle()
        # The finish is shown on the person's next message instead.
        await system.say("Anything else?")
        await system.settle()
        return system.updates_stored(), system.chat.runs[-1]["sent"]

    updates, shown = scenario(steps)
    assert updates == []
    assert "Changed since your last turn." in shown[0] and shown[1] == "Anything else?"


def test_a_turn_going_when_the_work_ends_means_no_work_update_even_if_it_ends_at_once(system, monkeypatch):
    monkeypatch.setattr(work_update, "SETTLE_SECONDS", 0.6)

    async def steps():
        run_id = await system.start()
        GATES["chat"] = asyncio.Event()
        turn = asyncio.ensure_future(system.say("What is 17 times 23?"))
        await asyncio.sleep(0.05)
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
        return system.row(run_id)["status"], system.updates_stored()

    assert scenario(steps) == ("COMPLETED", [])


def test_two_runs_ending_together_get_one_work_update_that_shows_both(system):
    async def steps():
        await system.start()
        await system.start("workflow", "investigator")
        await system.finish("writer", "investigator")
        return system.updates_stored(), system.chat.runs[-1]["sent"]

    updates, shown = scenario(steps)
    assert len(updates) == 1
    block, note = shown
    assert block.count("Changed since your last turn.") == 2
    assert 'agent "Writer"' in block and 'workflow "Investigator"' in block
    assert note.startswith(WORK_UPDATE_LABEL)


def test_work_that_ends_a_moment_later_is_reported_by_the_same_work_update(system, monkeypatch):
    monkeypatch.setattr(work_update, "SETTLE_SECONDS", 0.6)

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
        return system.updates_stored(), system.chat.runs[-1]["sent"]

    updates, shown = scenario(steps)
    assert len(updates) == 1
    assert shown[0].count("Changed since your last turn.") == 2


def test_a_work_update_ending_starts_no_other(system):
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
        return system.updates_stored(), told

    updates, told = scenario(steps)
    assert len(updates) == 1 and told == []
    # The work update names no conversation as having asked for it.
    assert REQUESTED_FROM_METADATA_KEY not in updates[0]["run_data"]["metadata"]


def test_work_reported_once_is_not_reported_again(system):
    async def steps():
        run_id = await system.start()
        await system.finish()
        asked = {"session_id": CHAT, "run_id": "r", "team_id": "superagent", "user_id": "alice"}
        # The same end told a second time, as a sweep on another server could.
        await system.updates(asked, {"kind": "run", "id": run_id, "status": "COMPLETED"}, None)
        await system.settle()
        return system.updates_stored()

    assert len(scenario(steps)) == 1


def test_no_more_than_the_limit_while_nobody_speaks(system):
    assert WORK_UPDATE_LIMIT == 3

    async def steps():
        for name in WRITERS:
            await system.start("agent", name)
        for name in WRITERS:
            await system.finish(name)
        before = len(system.updates_stored())
        # The person speaks: what they were not told is in the block, and the count starts again.
        await system.say("What happened?")
        shown = system.chat.runs[-1]["sent"][0]
        await system.start("workflow", "investigator")
        await system.finish("investigator")
        return before, shown, len(system.updates_stored())

    before, shown, after = scenario(steps)
    assert before == WORK_UPDATE_LIMIT
    assert shown.count("Changed since your last turn.") == len(WRITERS) - WORK_UPDATE_LIMIT
    assert after == WORK_UPDATE_LIMIT + 1


def test_stored_runs_decide_busy_and_the_count():
    now = time.time()

    def row(status, **more):
        return {"status": status, "created_at": now, "run_data": {}, "run_id": "r", **more}

    assert work_update._busy([row("COMPLETED"), row("ERROR"), row("CANCELLED")], now) is False
    for status in ("PENDING", "RUNNING", "PAUSED"):
        assert work_update._busy([row(status), row("COMPLETED")], now) is True
    # A run its server lost is stored as going for ever. A paused run waits for a person however long.
    old = now - work_update._LOST_AFTER_SECONDS - 1
    assert work_update._busy([row("RUNNING", created_at=old)], now) is False
    assert work_update._busy([row("PENDING", created_at=old, updated_at=old)], now) is False
    assert work_update._busy([row("PAUSED", created_at=old)], now) is True
    # A paused turn waits only until the person speaks again. A work update after it is not the person.
    spoke = row("COMPLETED", run_data={"input": {"input_content": "Hello"}})
    update = row("COMPLETED", run_data={"metadata": {WORK_UPDATE_METADATA_KEY: {"kind": "run"}}})
    member = row("COMPLETED", run_data={}, parent_run_id="a-member-run")
    assert work_update._busy([spoke, row("PAUSED")], now) is False
    assert work_update._busy([update, member, row("PAUSED")], now) is True
    assert work_update._busy([row("RUNNING"), spoke, row("PAUSED")], now) is True

    marked = {"metadata": {WORK_UPDATE_METADATA_KEY: {"kind": "run"}}}
    labelled = {"input": {"input_content": WORK_UPDATE_LABEL + ". The person did not write this"}}
    person = {"input": {"input_content": "Hello"}}
    rows = [
        row("COMPLETED", run_data=marked),
        row("COMPLETED", run_data={}, parent_run_id="a-member-run"),
        row("CANCELLED", run_data=labelled),
        row("COMPLETED", run_data=person, run_id="the-persons-run"),
        row("COMPLETED", run_data=marked),
    ]
    assert work_update._given(rows) == (2, "the-persons-run")
    assert work_update._given([]) == (0, "")


# ----------------------------------------------------------------- it reads and reports only


def marked(session=CHAT, user="alice", authority=None):
    mark = {WORK_UPDATE_METADATA_KEY: {"kind": "run", "id": "r", "status": "COMPLETED"}}
    return RunContext(
        run_id="update", session_id=session, user_id=user, session_state={}, metadata=mark, authorization=authority
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
        assert work_update.work_update_gate(name, ran, {"a": 1}, marked()) == WORK_UPDATE_REFUSAL, name
    assert called == []
    for name in sorted(READ_TOOLS):
        assert work_update.work_update_gate(name, ran, {"a": 1}, marked()) == "ran", name
    assert len(called) == len(READ_TOOLS)
    # Every other run is untouched.
    person = RunContext(run_id="r", session_id=CHAT, user_id="alice", session_state={}, metadata={"a": 1})
    assert work_update.work_update_gate("accept_company_task", ran, {}, person) == "ran"
    assert work_update.work_update_gate("accept_company_task", ran, {}, None) == "ran"


@pytest.mark.parametrize("async_mode", [True, False], ids=["async", "sync"])
def test_a_work_update_is_offered_only_reads_and_no_member(company, async_mode):
    hook = next(h for h in company.os.manager.pre_hooks if isinstance(h, work_update.WorkUpdateBoundary))
    update = marked()
    if async_mode:
        asyncio.run(hook.async_check(run_context=update, team=company.os.manager))
    else:
        hook.check(run_context=update, team=company.os.manager)
    offered = {function.name for function in update.tools}
    assert offered == READ_TOOLS & set(all_tools(company.os.manager, async_mode))
    assert {"check_background_run", "get_company_task_status", "read_company_file", "read_file"} <= offered
    assert not any(function.requires_confirmation for function in update.tools)
    assert update.members == []
    # A run of the person keeps the team's own tools and members.
    person = RunContext(run_id="r", session_id=CHAT, user_id="alice", session_state={})
    hook.check(run_context=person, team=company.os.manager)
    assert person.tools is None and person.members is None
    assert work_update._latest_run[CHAT] == ("r", False)


def test_the_gate_is_on_a_work_updates_own_team_and_never_on_the_served_one(company):
    team = company.os.manager
    boundary = next(hook for hook in team.pre_hooks if isinstance(hook, work_update.WorkUpdateBoundary))
    assert team.tool_hooks is None and boundary.served() is team
    assert not company.writer.tool_hooks and not company.os._manager.builder.tool_hooks
    # A work update runs on a copy of the Team, as every request and queued run does: the copy gets the gate.
    copy = team.deep_copy()
    copied = next(hook for hook in copy.pre_hooks if isinstance(hook, work_update.WorkUpdateBoundary))
    assert copied.served() is team
    copied.check(run_context=marked(), team=copy)
    assert copy.tool_hooks == [work_update.work_update_gate] and team.tool_hooks is None
    # The copy also reads the stored state again each time it saves; the served Team saves as it always did.
    assert {"save_session", "asave_session"} <= set(vars(copy)) and "asave_session" not in vars(team)
    # A turn of the person on a copy, and a work update run on the served Team itself, leave hooks alone.
    other = team.deep_copy()
    copied.check(run_context=RunContext(run_id="r", session_id=CHAT, user_id="alice", session_state={}), team=other)
    boundary.check(run_context=marked(), team=team)
    assert other.tool_hooks is None and team.tool_hooks is None
    assert "asave_session" not in vars(other) and "asave_session" not in vars(team)


@pytest.mark.parametrize("updates", [True, False], ids=["work updates on", "work updates off"])
def test_a_tools_own_hooks_still_run_on_the_persons_turns(tmp_path, updates):
    from agno.tools import tool

    audited = []

    def audit(function_name, function_call, arguments):
        audited.append(function_name)
        return function_call(**arguments)

    @tool(tool_hooks=[audit])
    def lookup(key: str) -> str:
        """Look a key up."""
        return "value of " + key

    system = System(tmp_path, tools=[lookup], work_updates=updates)

    async def steps():
        first = await system.say("Look it up", ("lookup", {"key": "a"}))
        # Also after a work update ran in the conversation.
        await system.start()
        await system.finish()
        second = await system.say("Again", ("lookup", {"key": "b"}))
        return first.tools[0].result, second.tools[0].result, len(system.updates_stored())

    assert scenario(steps) == ("value of a", "value of b", 1 if updates else 0)
    system.close()
    assert audited == ["lookup", "lookup"]


PERSON_ONLY = [
    ("add_company_task", {"title": "T", "brief": "B", "start": True}),
    ("move_company_task", {"task_id": "t", "project_id": "p"}),
    ("start_company_task", {"task_id": "t"}),
    ("approve_company_project", {"project_id": "p", "reason": "ok"}),
    ("accept_company_task", {"task_id": "t", "executor_type": "agent", "executor_id": "writer", "reason": "ok"}),
    ("review_company_task", {"task_id": "t", "decision": "complete", "reason": "ok"}),
    ("turn_on_routine_auto_accept", {"routine_id": "r"}),
    ("turn_off_routine_auto_accept", {"routine_id": "r"}),
]


@pytest.mark.parametrize("name, arguments", PERSON_ONLY, ids=[name for name, _ in PERSON_ONLY])
def test_a_person_only_tool_refuses_a_work_update_by_itself(company, name, arguments):
    """Without the gate and with the tool offered, the tool's own check for a person refuses."""
    import inspect

    function = all_tools(company.os.manager)[name]
    accepted = inspect.signature(function.entrypoint).parameters
    given = {key: value for key, value in arguments.items() if key in accepted}
    for key, parameter in accepted.items():
        if key not in given and not key.startswith("_") and parameter.default is inspect.Parameter.empty:
            given[key] = "x"
    result = asyncio.run(function.entrypoint(**given, _agno_run_context=marked()))
    assert "this is a work update and nobody is present" in str(result), result


def test_start_background_run_refuses_a_work_update_by_itself(company):
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
    assert "this is a work update and nobody is present" in json.loads(result)["error"]


def test_company_writes_that_need_a_person_refuse_a_work_update(company):
    from agno.tools.company import _require_human_creation

    with pytest.raises(PermissionError, match="this is a work update and nobody is present"):
        _require_human_creation(marked())
    _require_human_creation(RunContext(run_id="r", session_id=CHAT, user_id="alice", session_state={}))


def test_a_work_update_that_tries_to_act_changes_nothing(tmp_path):
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
        update = system.updates_stored()[0]
        tasks, _ = system.db.get_tasks()
        return task_id, update, system.chat.runs[-1], tasks, system.db.get_task(task_id)

    task_id, update, run, tasks, task = scenario(steps)
    system.close()
    # None of them was offered, so none could be called: the run ended without a pause and nothing changed.
    assert update["status"] == "COMPLETED"
    assert run["offered"] & REFUSED == set() and "delegate_task_to_member" not in run["offered"]
    assert "get_company_task_status" in run["offered"]
    assert len(tasks) == 1 and task["status"] == "in_review"
    # The five it was not offered never executed: the model was told each does not exist here.
    assert [tool["tool_name"] for tool in update["run_data"]["tools"]] == ["get_company_task_status"]
    assert content(update).count("The requested tool does not exist or is not available.") == 5
    assert '"status": "in_review"' in content(update)


def test_the_gate_refuses_what_the_boundary_would_have_hidden(tmp_path, monkeypatch):
    """With every tool offered, the gate alone keeps a work update from acting, in one sentence each."""
    system = System(tmp_path, queue=True, company=True)

    def everything(team, async_mode):
        return list(team.tools)

    monkeypatch.setattr(work_update.WorkUpdateBoundary, "_reads", staticmethod(everything))

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
        return system.updates_stored()[0], tasks

    update, tasks = scenario(steps)
    system.close()
    assert len(tasks) == 1 and update["status"] == "COMPLETED"
    results = [tool["result"] for tool in update["run_data"]["tools"]]
    assert results == [WORK_UPDATE_REFUSAL] * 3


def test_the_prompt_says_what_a_work_update_is():
    from agno.os.manager.prompts import MANAGER_INSTRUCTIONS

    assert f'A message that starts "{WORK_UPDATE_LABEL}"' in MANAGER_INSTRUCTIONS
    assert "report what ended and what waits on the person, and change nothing" in MANAGER_INSTRUCTIONS


def test_the_note_carries_no_result_text(system):
    async def steps():
        system.writer.model.script = []
        run_id = await system.start()
        await system.finish()
        return system.row(run_id), system.updates_stored()[0]

    work, update = scenario(steps)
    assert content(work) == "done"
    lines = sent(update).split("\n")
    assert len(lines) == 3 and len(sent(update)) < 900
    assert "Change nothing" in lines[2] and "Read each result with your tools" in lines[2]
    assert 'report every item that "Work started from this conversation" marks' in lines[2]


# ----------------------------------------------------------------- whose authority


@pytest.mark.parametrize("queue", [False, True], ids=["in-memory", "durable-queue"])
def test_a_work_update_runs_as_the_person_with_their_saved_authority(tmp_path, queue):
    system = System(tmp_path, queue=queue, authorization=True)

    async def steps():
        await system.start()
        await system.finish()
        return system.updates_stored(), system.chat.runs[-1]["authority"]

    updates, authority = scenario(steps)
    system.close()
    assert len(updates) == 1 and updates[0]["user_id"] == "alice"
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
        await system.updates(asked, work, None)
        await system.updates(asked, work, {**alice, "service_account": True})
        await system.updates(asked, work, {**alice, "scheduled": True})
        await system.updates(asked, work, {**alice, "company_executor": True})
        await system.updates(asked, work, system.authority("bob").snapshot())
        # A run that says another person asked for it.
        await system.updates({**asked, "user_id": "bob"}, work, alice)
        await system.settle()
        none = len(system.updates_stored())
        await system.updates(asked, work, alice)
        await system.settle()
        return none, len(system.updates_stored())

    assert scenario(steps) == (0, 1)
    system.close()


@pytest.mark.parametrize("queue", [False, True], ids=["in-memory", "durable-queue"])
def test_under_user_isolation_the_work_update_is_the_persons(tmp_path, queue):
    system = System(tmp_path, queue=queue, user_isolation=True)

    async def steps():
        await system.start()
        await system.start("workflow", "investigator", user="bob", session="bobs-chat")
        await system.finish("writer", "investigator")
        return system.updates_stored(), system.updates_stored("bobs-chat")

    alice, bob = scenario(steps)
    system.close()
    assert [row["user_id"] for row in alice] == ["alice"] and [row["user_id"] for row in bob] == ["bob"]
    assert 'agent "Writer"' in sent(alice[0]) and 'workflow "Investigator"' in sent(bob[0])


def test_under_user_isolation_a_conversation_with_no_person_is_not_told(tmp_path):
    system = System(tmp_path, user_isolation=True)
    session = {"team_id": "superagent", "user_id": None}
    assert system.updates._authority(system.os, None, session["user_id"]) == (None, False)
    assert system.updates._authority(system.os, None, "alice") == (None, True)
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

            monkeypatch.setattr(WorkUpdates, "_start", refuse)
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
        assert len(added) == 1 and isinstance(added[0], WorkUpdates)
    assert run_background._requester_listeners == before
    system.close()


# ----------------------------------------------------------------- while a work update is going


class HeldUpdates(Chat):
    """Super Agent's model, which holds a work update at GATES["update"] and lets every other run through."""

    async def ainvoke(self, messages, tools=None, **kwargs):
        fresh = [m for m in messages if not m.from_history and m.role == "user"]
        if any(str(m.content).startswith(WORK_UPDATE_LABEL) for m in fresh):
            if GATES.get("update") is not None:
                await GATES["update"].wait()
        elif GATES.get("chat") is not None:
            await GATES["chat"].wait()
        return self.invoke(messages, tools=tools, **kwargs)


@pytest.fixture(params=[False, True], ids=["in-memory", "durable-queue"])
def held(request, tmp_path):
    value = System(tmp_path, queue=request.param)
    value.chat = HeldUpdates()
    value.os.manager.model = value.chat
    yield value
    value.close()


def listed(system):
    session = system.db.get_session(CHAT, deserialize=False)
    entries = ((session.get("session_data") or {}).get("session_state") or {}).get(LINKED_WORK_KEY, [])
    return {entry.get("component_id"): entry.get("shown") for entry in entries}


def test_a_message_sent_while_a_work_update_is_going_keeps_the_work_it_starts(held, monkeypatch):
    monkeypatch.setattr(work_update, "_UPDATE_POLL_SECONDS", 0.02)

    async def steps():
        GATES["update"] = asyncio.Event()
        await held.start()
        await held.finish("writer")
        going = [row["status"] for row in held.updates_stored()]
        # The person cannot see that a work update is going, and asks for more work.
        second = await held.start("workflow", "investigator")
        after_the_turn = listed(held)
        # The work update ends after the person's turn did.
        GATES["update"].set()
        await held.settle()
        after_the_update = listed(held)
        await held.finish("investigator")
        await asyncio.sleep(0.2)
        await held.settle()
        check = await held.say("Did it finish?", ("check_background_run", {"run_id": second}))
        return going, after_the_turn, after_the_update, len(held.updates_stored()), json.loads(check.tools[0].result)

    going, after_the_turn, after_the_update, updates, checked = scenario(steps)
    assert going[0] in ("PENDING", "RUNNING")
    assert after_the_turn == {"writer": "COMPLETED", "investigator": "LIVE"}
    # The work update, which loaded the state before that turn, kept the run the person started.
    assert after_the_update == {"writer": "COMPLETED", "investigator": "LIVE"}
    assert updates == 2 and checked.get("status") == "COMPLETED", checked


def test_the_state_a_work_update_saves_is_the_stored_one_with_its_own_marks():
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
                    # Shown by this work update.
                    {"kind": "run", "id": "a", "shown": "COMPLETED", "changed_in": "update", "name": "old"},
                    # Loaded as running and not marked by it: a turn of the person has since reported it.
                    {"kind": "run", "id": "b", "shown": "LIVE", "changed_in": None},
                    {"kind": "run", "id": "gone", "shown": "COMPLETED", "changed_in": None},
                ],
            },
        }

    session = Session()
    loaded = session.session_data["session_state"]
    work_update._keep_stored_state(session, stored, "update")
    # The same dictionary, which the run also holds, now has the stored state with this run's marks.
    assert session.session_data["session_state"] is loaded and session.session_data["kept"] is True
    assert loaded == {
        "other": "kept",
        LINKED_WORK_KEY: [
            {"kind": "run", "id": "a", "shown": "COMPLETED", "changed_in": "update", "name": "stored name"},
            {"kind": "run", "id": "b", "shown": "COMPLETED", "changed_in": "the-persons-turn"},
            {"kind": "run", "id": "new", "shown": "LIVE", "changed_in": None},
        ],
    }
    # Nothing readable stored: the run's own state stands.
    before = dict(loaded)
    work_update._keep_stored_state(session, None, "update")
    work_update._keep_stored_state(session, {"session_data": {}}, "update")
    assert loaded == before


class FailingUpdates(HeldUpdates):
    """Holds a work update, then fails it where its reply would be."""

    async def ainvoke(self, messages, tools=None, **kwargs):
        fresh = [m for m in messages if not m.from_history and m.role == "user"]
        update = any(str(m.content).startswith(WORK_UPDATE_LABEL) for m in fresh)
        result = await super().ainvoke(messages, tools=tools, **kwargs)
        if update and SEEN.get("update_fails"):
            raise RuntimeError("the model broke")
        return result


@pytest.mark.parametrize("ending", ["fails", "is cancelled"])
def test_a_work_update_that_does_not_finish_keeps_the_work_a_turn_started(held, monkeypatch, ending):
    monkeypatch.setattr(work_update, "_UPDATE_POLL_SECONDS", 0.02)
    held.chat = FailingUpdates()
    held.os.manager.model = held.chat

    async def steps():
        GATES["update"] = asyncio.Event()
        SEEN["update_fails"] = ending == "fails"
        await held.start()
        await held.finish("writer")
        second = await held.start("workflow", "investigator")
        if ending == "is cancelled":
            update = held.updates_stored()[0]["run_id"]
            await held.os.manager.acancel_run(update)
        GATES["update"].set()
        await held.settle()
        SEEN["update_fails"] = False
        ended = [row["status"] for row in held.updates_stored()]
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
    monkeypatch.setattr(work_update, "_UPDATE_POLL_SECONDS", 0.02)

    async def steps():
        GATES["update"] = asyncio.Event()
        await held.start()
        await held.start("workflow", "investigator")
        await held.finish("writer")
        # The second run ends while the work update for the first is going, and the person asks.
        await held.finish("investigator")
        await held.say("Status?")
        told = held.chat.runs[-1]["sent"][0].count("Changed since your last turn.")
        GATES["update"].set()
        await held.settle()
        await asyncio.sleep(0.3)
        await held.settle()
        after = listed(held)
        await held.say("Thanks")
        return told, after, len(held.updates_stored()), held.chat.runs[-1]["sent"]

    told, after, updates, last = scenario(steps)
    assert told == 2
    # The work update loaded the second run as running. It did not put that back over the turn's mark.
    assert after == {"writer": "COMPLETED", "investigator": "COMPLETED"}
    assert updates == 1
    assert not any("Changed since your last turn." in message for message in last)


def test_work_that_ends_while_a_work_update_is_going_gets_one_of_its_own(held, monkeypatch):
    monkeypatch.setattr(work_update, "_UPDATE_POLL_SECONDS", 0.02)

    async def steps():
        GATES["update"] = asyncio.Event()
        await held.start()
        second = await held.start("workflow", "investigator")
        await held.finish("writer")
        # The second run ends while the first work update, which called it running, is still going.
        await held.finish("investigator")
        during = len(held.updates_stored())
        GATES["update"].set()
        await held.settle()
        await asyncio.sleep(0.3)
        await held.settle()
        shown = [run["sent"] for run in held.chat.runs if run["sent"][-1].startswith(WORK_UPDATE_LABEL)]
        return held.row(second)["status"], shown[0][0], during, held.updates_stored(), shown[-1]

    ended, first_block, during, updates, last = scenario(steps)
    assert ended == "COMPLETED" and during == 1
    assert 'agent "Writer"' in first_block and "finished" in first_block
    assert first_block.count("Changed since your last turn.") == 1
    # It called the second run queued or running. The order of the two lines is not fixed.
    investigator = next(line for line in first_block.split("\n") if 'workflow "Investigator"' in line)
    assert "Changed since your last turn." not in investigator and "finished" not in investigator
    assert len(updates) == 2
    assert 'workflow "Investigator"' in sent(updates[1])
    assert last[0].count("Changed since your last turn.") == 1 and 'workflow "Investigator"' in last[0]


def test_work_a_going_work_update_will_show_gets_no_second_one(held, monkeypatch):
    monkeypatch.setattr(work_update, "_UPDATE_POLL_SECONDS", 0.02)

    async def steps():
        GATES["update"] = asyncio.Event()
        for name in WRITERS[:3]:
            await held.start("agent", name)
        await held.finish("writer")
        # Two more end while the first work update is going. One work update reports both.
        await held.finish("writer-2", "writer-3")
        GATES["update"].set()
        await held.settle()
        await asyncio.sleep(0.3)
        await held.settle()
        return held.updates_stored(), held.chat.runs[-1]["sent"][0]

    updates, block = scenario(steps)
    assert len(updates) == 2
    assert block.count("Changed since your last turn.") == 2


def test_a_turn_of_the_person_while_a_notice_waits_means_no_work_update(held, monkeypatch):
    monkeypatch.setattr(work_update, "_UPDATE_POLL_SECONDS", 0.02)

    async def steps():
        GATES["update"] = asyncio.Event()
        await held.start()
        await held.start("workflow", "investigator")
        await held.finish("writer")
        await held.finish("investigator")
        # The person speaks while the second notice waits for the first work update.
        GATES["chat"] = asyncio.Event()
        turn = asyncio.ensure_future(held.say("What is 17 times 23?"))
        await asyncio.sleep(0.05)
        GATES["update"].set()
        await held.settle()
        count = len(held.updates_stored())
        GATES["chat"].set()
        await turn
        GATES["chat"] = None
        await held.settle()
        return count, len(held.updates_stored())

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
        return paused["status"], plain.row(run_id)["status"], [sent(u).split("\n")[1] for u in plain.updates_stored()]

    paused, ended, updates = scenario(steps)
    assert (paused, ended) == ("PAUSED", "COMPLETED")
    assert len(updates) == 2
    assert updates[0].endswith("paused for a person.") and updates[1].endswith("finished.")


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
        return plain.row(run_id)["status"], [sent(u).split("\n")[1] for u in plain.updates_stored()]

    status, updates = scenario(steps)
    assert status == "COMPLETED"
    assert updates == [next(iter(updates), "")] and updates[0].startswith('Background run of workflow "Answerer"')
    assert updates[0].endswith("finished.")


# ----------------------------------------------------------------- round two of the review


def notices(system):
    """How each stored work update worded what ended."""
    return [sent(update).split("\n")[1].split("): ")[-1] for update in system.updates_stored()]


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

    second, ended, updates = scenario(steps)
    assert second == ("PAUSED", ["paused for a person.", "paused for a person."])
    assert ended == "COMPLETED" and updates[-1] == "finished." and len(updates) == 3


def test_a_pause_told_twice_without_a_continue_is_reported_once(plain):
    async def steps():
        plain.writer.tools = confirmations()[:1]
        plain.writer.model.script = [("publish", {})]
        run_id = await plain.start()
        await plain.finish()
        asked = {"session_id": CHAT, "run_id": "r", "team_id": "superagent", "user_id": "alice"}
        await plain.updates(asked, {"kind": "run", "id": run_id, "status": "PAUSED"}, None)
        await plain.settle()
        return notices(plain)

    assert scenario(steps) == ["paused for a person."]


def test_an_approval_through_the_resumable_streaming_continue_is_reported(plain):
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
        return plain.row(run_id)["status"], notices(plain)

    assert scenario(steps) == ("COMPLETED", ["paused for a person.", "finished."])


def test_an_application_tool_named_like_a_read_is_not_offered_in_a_work_update(tmp_path):
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
        return system.chat.runs[-1]["offered"], content(system.updates_stored()[0])

    offered, reply = scenario(steps)
    system.close()
    # It ran on the person's turn. A work update is offered the framework's own reads only.
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
        return paused.status.value, [row["status"] for row in system.turns()][:1], len(system.updates_stored())

    paused, first, updates = scenario(steps)
    system.close()
    assert (paused, first) == ("PAUSED", ["PAUSED"])
    assert updates == 1
