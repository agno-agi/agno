"""Native harness permission requests as human-in-the-loop confirmations; no model calls.

A Claude or Codex permission request pauses the run with a tool that requires confirmation, as an Agno
agent's confirmation tool does. Continuing the run with the tool confirmed or rejected delivers that
decision to the same native execution, which never replays.
"""

import asyncio
import time
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from agno.agents._hitl import KEY, current_bridge, db_call, submit_decisions, sync_events, tail_stored
from agno.agents.base import BaseExternalAgent
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.models.response import ToolExecution
from agno.run.agent import RunContentEvent, RunContinuedEvent, RunOutput
from agno.run.base import RunStatus
from agno.run.requirement import RunRequirement
from agno.session import AgentSession


@dataclass
class Harness(BaseExternalAgent):
    @property
    def _uses_native_hitl(self):
        return self.db is not None

    calls: int = 0
    executions: int = 0

    def acontinue_run(self, run_response=None, **kwargs):
        from agno.agents._hitl import continue_run

        return continue_run(self, run_response, **kwargs)

    async def _arun_adapter_stream(self, input, **kwargs):
        self.calls += 1
        allowed = await current_bridge().request("Bash", {"command": "write-marker"}, {"sdk": "fixture"})
        if allowed:
            self.executions += 1
        yield RunContentEvent(content="allowed" if allowed else "denied")


async def pending(agent, run_id="run", session_id="session"):
    for _ in range(300):
        run = await agent.aget_run_output(run_id, session_id=session_id)
        if run is not None and run.status == RunStatus.paused:
            return run
        await asyncio.sleep(0.01)
    raise AssertionError("No persisted pause")


def answered(run, confirmed):
    """The paused run's tools as the chat sends them back after a confirm or reject."""
    tools = []
    for requirement in run.requirements:
        tool = ToolExecution.from_dict(requirement.tool_execution.to_dict())
        tool.confirmed = confirmed
        tools.append(tool)
    return tools


# ---------------------------------------------------------------------------
# The pause and the decision
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmed", [True, False])
@pytest.mark.parametrize("database", [SqliteDb, AsyncSqliteDb])
async def test_chat_decision_releases_the_same_native_execution_once(tmp_path, confirmed, database):
    db = database(db_file=str(tmp_path / "confirm.db"))
    agent = Harness(id="test", db=db, hitl_timeout=5)
    task = asyncio.create_task(agent.arun("work", session_id="session", run_id="run"))
    try:
        run = await pending(agent)
        assert agent.executions == 0 and agent.calls == 1
        # The pause is an ordinary confirmation tool: no admin approval is involved.
        tool = run.requirements[0].tool_execution
        assert run.requirements[0].needs_confirmation
        assert tool.requires_confirmation and tool.approval_type is None and tool.approval_id is None
        with pytest.raises(ValueError, match="Confirm or reject"):
            await submit_decisions(agent, "run", "session", None)
        await submit_decisions(agent, "run", "session", None, answered(run, confirmed))
        with pytest.raises(ValueError, match="not waiting"):
            await submit_decisions(agent, "run", "session", None, answered(run, confirmed))
        result = await asyncio.wait_for(task, 3)
        assert result.status == RunStatus.completed
        assert result.content == ("allowed" if confirmed else "denied")
        assert agent.calls == 1 and agent.executions == int(confirmed)
        assert result.metadata[KEY]["pending"] == []
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_no_approval_rows_are_created(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "confirm.db"))
    agent = Harness(id="test", db=db, hitl_timeout=5)
    task = asyncio.create_task(agent.arun("work", session_id="session", run_id="run"))
    try:
        run = await pending(agent)
        assert db.get_approvals() == ([], 0)
        await submit_decisions(agent, "run", "session", None, answered(run, True))
        await asyncio.wait_for(task, 3)
        assert db.get_approvals() == ([], 0)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_expiry_does_not_execute(tmp_path):
    agent = Harness(id="test", db=SqliteDb(db_file=str(tmp_path / "confirm.db")), hitl_timeout=0.2)
    result = await agent.arun("work", session_id="session", run_id="run")
    assert result.status == RunStatus.error
    assert "expired" in result.content
    assert agent.executions == 0


def test_native_hitl_requires_storage():
    assert not Harness()._uses_native_hitl


@pytest.mark.asyncio
async def test_changed_arguments_and_wrong_session_are_refused(tmp_path):
    agent = Harness(id="test", db=SqliteDb(db_file=str(tmp_path / "confirm.db")), hitl_timeout=5)
    task = asyncio.create_task(agent.arun("work", session_id="session", run_id="run"))
    try:
        run = await pending(agent)
        [changed] = answered(run, True)
        changed.tool_args = {"command": "different-action"}
        with pytest.raises(ValueError, match="does not match"):
            await submit_decisions(agent, "run", "session", None, [changed])
        with pytest.raises(ValueError, match="not found"):
            await submit_decisions(agent, "run", "other-session", None, answered(run, True))
        assert agent.executions == 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancel_while_waiting_never_executes(tmp_path):
    agent = Harness(id="test", db=SqliteDb(db_file=str(tmp_path / "confirm.db")), hitl_timeout=5)
    task = asyncio.create_task(agent.arun("work", session_id="session", run_id="run"))
    await pending(agent)
    await agent.acancel_run("run")
    result = await asyncio.wait_for(task, 2)
    assert result.status == RunStatus.cancelled
    assert agent.executions == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_status", [RunStatus.paused, RunStatus.running])
async def test_snapshot_failure_never_releases_the_native_action(tmp_path, monkeypatch, failed_status):
    agent = Harness(id="test", db=SqliteDb(db_file=str(tmp_path / "confirm.db")), hitl_timeout=5)
    persist = agent._apersist_run_in_session
    decided = False

    async def fail_snapshot(session, run, **kwargs):
        # The owner's own snapshots fail; the continuation's decision write succeeds.
        if (
            run.status == failed_status
            and (run.metadata or {}).get(KEY)
            and (failed_status != RunStatus.running or decided)
        ):
            raise RuntimeError("snapshot unavailable")
        return await persist(session, run, **kwargs)

    monkeypatch.setattr(agent, "_apersist_run_in_session", fail_snapshot)
    task = asyncio.create_task(agent.arun("work", session_id="session", run_id="run"))
    try:
        if failed_status == RunStatus.running:
            run = await pending(agent)
            monkeypatch.setattr(agent, "_apersist_run_in_session", persist)
            await submit_decisions(agent, "run", "session", None, answered(run, True))
            decided = True
            monkeypatch.setattr(agent, "_apersist_run_in_session", fail_snapshot)
        result = await asyncio.wait_for(task, 3)
        assert result.status == RunStatus.error
        assert "snapshot unavailable" in result.content
        assert agent.executions == 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_simultaneous_requests_pause_one_at_a_time(tmp_path):
    @dataclass
    class ParallelHarness(Harness):
        async def _arun_adapter_stream(self, input, **kwargs):
            results = await asyncio.gather(
                current_bridge().request("Bash", {"command": "one"}, {"tool_call_id": "one"}),
                current_bridge().request("Bash", {"command": "two"}, {"tool_call_id": "two"}),
            )
            self.executions = sum(results)
            yield RunContentEvent(content="done")

    agent = ParallelHarness(id="parallel", db=SqliteDb(db_file=str(tmp_path / "parallel.db")), hitl_timeout=5)
    task = asyncio.create_task(agent.arun("work", run_id="run", session_id="session"))
    try:
        first = await pending(agent)
        assert [r.tool_execution.tool_call_id for r in first.requirements] == ["one"]
        second = await asyncio.wait_for(
            agent.acontinue_run(run_id="run", session_id="session", updated_tools=answered(first, True)), 3
        )
        assert second.status == RunStatus.paused
        assert [r.tool_execution.tool_call_id for r in second.requirements] == ["two"]
        result = await asyncio.wait_for(
            agent.acontinue_run(run_id="run", session_id="session", updated_tools=answered(second, False)), 3
        )
        assert result.status == RunStatus.completed
        assert (await asyncio.wait_for(task, 3)).status == RunStatus.completed
        assert agent.executions == 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_successive_requests_with_lifecycle_events_excluded(tmp_path, monkeypatch):
    from agno.run.agent import RunEvent

    agent = Harness(
        id="agent",
        db=SqliteDb(db_file=str(tmp_path / "events.db")),
        hitl_timeout=5,
        events_to_skip=[RunEvent.run_paused, RunEvent.run_continued],
    )

    async def source(input, **kwargs):
        await current_bridge().request("Bash", {"command": "first"}, {})
        await current_bridge().request("Bash", {"command": "second"}, {})
        yield RunContentEvent(content="done")

    monkeypatch.setattr(agent, "_arun_adapter_stream", source)
    task = asyncio.create_task(agent.arun("work", session_id="session", run_id="run"))
    try:
        first = await pending(agent)
        second = await asyncio.wait_for(
            agent.acontinue_run(run_id="run", session_id="session", updated_tools=answered(first, True)), 3
        )
        assert second.status == RunStatus.paused
        assert second.requirements[0].tool_execution.tool_args == {"command": "second"}
        assert not any(event.event in ("RunPaused", "RunContinued") for event in second.events or [])
        completed = await asyncio.wait_for(
            agent.acontinue_run(run_id="run", session_id="session", updated_tools=answered(second, False)), 3
        )
        assert completed.status == RunStatus.completed
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_a_recorded_decision_survives_a_later_failure(tmp_path, monkeypatch):
    agent = Harness(id="agent", db=SqliteDb(db_file=str(tmp_path / "audit.db")), hitl_timeout=5)

    async def source(input, **kwargs):
        assert await current_bridge().request("Bash", {"command": "echo test"}, {})
        raise RuntimeError("failure after delivery")
        yield  # pragma: no cover

    monkeypatch.setattr(agent, "_arun_adapter_stream", source)
    task = asyncio.create_task(agent.arun("work", session_id="session", run_id="run"))
    try:
        run = await pending(agent)
        tool_call_id = run.requirements[0].tool_execution.tool_call_id
        await submit_decisions(agent, "run", "session", None, answered(run, True))
        result = await asyncio.wait_for(task, 3)
        assert result.status == RunStatus.error
        assert result.metadata[KEY]["decisions"][tool_call_id]["confirmed"] is True
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


# ---------------------------------------------------------------------------
# Teams, workflows and continuation APIs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("parent", ["_team_id", "_workflow_id"])
@pytest.mark.parametrize("stream", [True, False])
async def test_nested_permission_request_fails_without_executing(tmp_path, parent, stream):
    agent = Harness(db=SqliteDb(db_file=str(tmp_path / "db")))
    result = agent.arun("work", stream=stream, yield_run_output=True, **{parent: "parent"})
    if stream:
        outputs = [item async for item in result if isinstance(item, RunOutput)]
        result = outputs[-1]
    else:
        result = await result
    assert result.status == RunStatus.error
    assert "standalone" in result.content
    assert agent.calls == 1 and agent.executions == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("parent", ["_team_id", "_workflow_id"])
async def test_nested_run_without_permission_request_keeps_working(tmp_path, parent, monkeypatch):
    agent = Harness(db=SqliteDb(db_file=str(tmp_path / "db")))

    async def source(input, **kwargs):
        yield RunContentEvent(content="done")

    monkeypatch.setattr(agent, "_arun_adapter_stream", source)
    result = await agent.arun("work", **{parent: "parent"})
    assert result.status == RunStatus.completed and result.content == "done"


@pytest.mark.parametrize("sdk", ["claude", "codex"])
@pytest.mark.parametrize("stream", [True, False])
def test_public_sync_continuation_releases_the_original_run(tmp_path, monkeypatch, caplog, sdk, stream):
    from concurrent.futures import ThreadPoolExecutor

    from agno.agents.claude import ClaudeAgent
    from agno.agents.codex import CodexAgent

    db = SqliteDb(db_file=str(tmp_path / "db"))
    cls = ClaudeAgent if sdk == "claude" else CodexAgent
    agent = cls(id="test", db=db, hitl_timeout=5)
    executed = []

    async def source(input, **kwargs):
        if await current_bridge().request("Bash", {"command": "marker"}, {"sdk": sdk}):
            executed.append("marker")
        yield RunContentEvent(content="done")

    monkeypatch.setattr(agent, "_arun_adapter_stream", source)

    async def nonstream(input, **kwargs):
        return "".join([event.content async for event in source(input, **kwargs)])

    monkeypatch.setattr(agent, "_arun_adapter", nonstream)
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(agent.run, "work", session_id="session", run_id="run")
        for _ in range(300):
            run = agent.get_run_output("run", "session")
            if run is not None and run.status == RunStatus.paused:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("No persisted pause")
        for requirement in run.requirements:
            requirement.confirm()
        result = agent.continue_run(run_id="run", session_id="session", requirements=run.requirements, stream=stream)
        if stream:
            result = next(event for event in result if isinstance(event, RunOutput))
        assert result.status == RunStatus.completed
        assert running.result(timeout=2).status == RunStatus.completed
    assert executed == ["marker"]
    assert "Task was destroyed" not in caplog.text


@pytest.mark.asyncio
async def test_agentos_chat_confirmation_reaches_the_live_harness(tmp_path):
    import httpx

    from agno.os import AgentOS
    from agno.run.background import await_background_runs

    db = SqliteDb(db_file=str(tmp_path / "api.db"))
    agent = Harness(id="test", db=db, hitl_timeout=5)
    app = AgentOS(id="confirm-test", db=db, agents=[agent]).get_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # The chat's stream ends at the pause, as for an Agno agent's confirmation tool.
        response = await client.post(
            "/agents/test/runs", data={"message": "work", "session_id": "session", "stream": "true"}
        )
        assert response.status_code == 200, response.text
        assert "RunPaused" in response.text and "RunCompleted" not in response.text
        import re

        run_id = re.search(r'"run_id":\s*"([^"]+)"', response.text).group(1)
        run = await pending(agent, run_id)
        assert run.requirements[0].tool_execution.requires_confirmation
        # Nothing is listed for an admin to approve.
        listed = await client.get("/approvals")
        assert listed.status_code == 200 and listed.json()["meta"]["total_count"] == 0
        # Continuing without answering the request is refused.
        response = await client.post(
            f"/agents/test/runs/{run_id}/continue", data={"session_id": "session", "stream": "false"}
        )
        assert response.status_code == 409, response.text
        tools = [tool.to_dict() for tool in answered(run, True)]
        import json

        response = await client.post(
            f"/agents/test/runs/{run_id}/continue",
            data={"session_id": "session", "stream": "true", "tools": json.dumps(tools)},
        )
        assert response.status_code == 200, response.text
        assert "RunContinued" in response.text and "RunCompleted" in response.text
        await await_background_runs(timeout=2)
        result = await agent.aget_run_output(run_id, session_id="session")
        assert result.status == RunStatus.completed and result.content == "allowed"
        # The decision is delivered once; a repeated continuation finds the run no longer paused.
        response = await client.post(
            f"/agents/test/runs/{run_id}/continue",
            data={"session_id": "session", "stream": "false", "tools": json.dumps(tools)},
        )
        assert response.status_code == 409, response.text


# ---------------------------------------------------------------------------
# Native questions pause as user feedback
# ---------------------------------------------------------------------------

QUESTIONS = [
    {
        "question": "Which color?",
        "header": "Color",
        "options": [{"label": "Red", "description": None}, {"label": "Blue", "description": "Calm"}],
        "multi_select": False,
    },
    {
        "question": "Which sizes?",
        "header": "Size",
        "options": [{"label": "S", "description": None}, {"label": "M", "description": None}],
        "multi_select": True,
    },
]


@dataclass
class Asking(Harness):
    async def _arun_adapter_stream(self, input, **kwargs):
        import json

        self.calls += 1
        answers = await current_bridge().ask("AskUserQuestion", {"questions": QUESTIONS}, {"sdk": "fixture"}, QUESTIONS)
        yield RunContentEvent(content=json.dumps(answers))


def feedback(run, selections):
    """The paused run's tools as the chat sends them back after answering the questions."""
    tools = []
    for requirement in run.requirements:
        tool = ToolExecution.from_dict(requirement.tool_execution.to_dict())
        for question, selected in zip(tool.user_feedback_schema, selections):
            question.selected_options = selected
        tool.answered = True
        tools.append(tool)
    return tools


@pytest.mark.asyncio
async def test_agentos_chat_answers_reach_the_live_harness(tmp_path):
    import json
    import re

    import httpx

    from agno.os import AgentOS
    from agno.run.background import await_background_runs

    db = SqliteDb(db_file=str(tmp_path / "api.db"))
    agent = Asking(id="test", db=db, hitl_timeout=5)
    app = AgentOS(id="feedback-test", db=db, agents=[agent]).get_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/agents/test/runs", data={"message": "work", "session_id": "session", "stream": "true"}
        )
        assert response.status_code == 200, response.text
        assert "RunPaused" in response.text and "RunCompleted" not in response.text
        run_id = re.search(r'"run_id":\s*"([^"]+)"', response.text).group(1)
        run = await pending(agent, run_id)
        # The same pause as Agno's ask_user tool: user feedback, not a confirmation.
        requirement = run.requirements[0]
        assert requirement.pause_type == "user_feedback" and requirement.needs_user_feedback
        tool = requirement.tool_execution
        assert tool.requires_user_input and not tool.requires_confirmation
        assert [q.question for q in tool.user_feedback_schema] == ["Which color?", "Which sizes?"]
        assert tool.user_feedback_schema[1].multi_select and tool.user_feedback_schema[0].options[1].label == "Blue"
        # A confirm without selections does not answer the questions.
        confirmed = ToolExecution.from_dict(tool.to_dict())
        confirmed.confirmed = True
        response = await client.post(
            f"/agents/test/runs/{run_id}/continue",
            data={"session_id": "session", "stream": "false", "tools": json.dumps([confirmed.to_dict()])},
        )
        assert response.status_code == 409, response.text
        tools = [t.to_dict() for t in feedback(run, [["Blue"], ["S", "a custom size"]])]
        response = await client.post(
            f"/agents/test/runs/{run_id}/continue",
            data={"session_id": "session", "stream": "true", "tools": json.dumps(tools)},
        )
        assert response.status_code == 200, response.text
        assert "RunContinued" in response.text and "RunCompleted" in response.text
        await await_background_runs(timeout=2)
        result = await agent.aget_run_output(run_id, session_id="session")
        assert result.status == RunStatus.completed
        assert json.loads(result.content) == [["Blue"], ["S", "a custom size"]]
        assert agent.calls == 1
        # The answered questions stay on the run's tool, as the chat history shows them.
        stored = next(t for t in result.tools if t.tool_name == "AskUserQuestion")
        assert stored.answered and not stored.requires_confirmation
        assert [q.selected_options for q in stored.user_feedback_schema] == [["Blue"], ["S", "a custom size"]]
        assert stored.user_feedback_schema[0].options[1].selected is True
        assert not result.requirements
        response = await client.post(
            f"/agents/test/runs/{run_id}/continue",
            data={"session_id": "session", "stream": "false", "tools": json.dumps(tools)},
        )
        assert response.status_code == 409, response.text


@pytest.mark.asyncio
async def test_native_question_answers_must_match_the_asked_questions(tmp_path):
    agent = Asking(id="test", db=SqliteDb(db_file=str(tmp_path / "ask.db")), hitl_timeout=5)
    task = asyncio.create_task(agent.arun("work", session_id="session", run_id="run"))
    try:
        run = await pending(agent)
        unanswered = feedback(run, [["Blue"], None])
        with pytest.raises(ValueError, match="Answer every question"):
            await submit_decisions(agent, "run", "session", None, unanswered)
        renamed = feedback(run, [["Blue"], ["S"]])
        renamed[0].user_feedback_schema[0].question = "Which shape?"
        with pytest.raises(ValueError, match="Answer every question"):
            await submit_decisions(agent, "run", "session", None, renamed)
        changed = feedback(run, [["Blue"], ["S"]])
        changed[0].tool_args = {"questions": []}
        with pytest.raises(ValueError, match="does not match"):
            await submit_decisions(agent, "run", "session", None, changed)
        assert (await agent.aget_run_output("run", "session")).status == RunStatus.paused
        # A skipped question is an empty selection.
        await submit_decisions(agent, "run", "session", None, feedback(run, [[], ["M"]]))
        result = await asyncio.wait_for(task, 5)
        assert result.content == '[[], ["M"]]'
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_claude_ask_user_question_answers_by_question_text(monkeypatch):
    from agno.agents import _hitl
    from agno.agents.claude.agent import _ask_user_question

    asked = []
    selections = [["Blue"], ["S", "M"]]

    async def ask(name, arguments, native, questions):
        asked.append((name, questions))
        return selections

    monkeypatch.setattr(_hitl, "current_bridge", lambda: SimpleNamespace(ask=ask))
    sdk = SimpleNamespace(
        PermissionResultAllow=lambda **kw: ("allow", kw), PermissionResultDeny=lambda **kw: ("deny", kw)
    )
    arguments = {
        "questions": [
            {"question": "Which color?", "header": "Color", "options": [{"label": "Red"}, {"label": "Blue"}]},
            {"question": "Which sizes?", "header": "Size", "options": [{"label": "S"}], "multiSelect": True},
        ]
    }
    behavior, result = await _ask_user_question(sdk, arguments, {"sdk": "claude"})
    assert behavior == "allow"
    assert result["updated_input"] == {**arguments, "answers": {"Which color?": "Blue", "Which sizes?": "S, M"}}
    assert asked[0][0] == "AskUserQuestion" and asked[0][1][1]["multi_select"] is True
    selections = [[], []]
    behavior, result = await _ask_user_question(sdk, arguments, {"sdk": "claude"})
    assert behavior == "deny" and "declined" in result["message"]
    with pytest.raises(ValueError, match="no questions"):
        await _ask_user_question(sdk, {"questions": []}, {"sdk": "claude"})


@pytest.mark.asyncio
async def test_codex_request_user_input_answers_by_question_id(monkeypatch):
    pytest.importorskip("openai_codex")
    from openai_codex.client import CodexClient

    from agno.agents.codex._hitl import human_client

    asked = []
    sent = []

    async def ask(name, arguments, native, questions):
        asked.append((name, arguments, native, questions))
        return [["Blue"], []]

    client = human_client(None, SimpleNamespace(ask=ask))._client._sync
    monkeypatch.setattr(CodexClient, "_write_message", lambda self, message: sent.append(message))
    questions = [
        {
            "id": "color",
            "header": "Color",
            "question": "Which color?",
            "isOther": True,
            "isSecret": False,
            "options": [{"label": "Red", "description": "Warm"}, {"label": "Blue", "description": "Calm"}],
        },
        {
            "id": "note",
            "header": "Note",
            "question": "Anything else?",
            "isOther": True,
            "isSecret": False,
            "options": None,
        },
    ]
    params = {"threadId": "thread", "turnId": "turn", "itemId": "item", "questions": questions}
    await client.decide({"id": 9, "method": "item/tool/requestUserInput", "params": params})
    assert sent == [{"id": 9, "result": {"answers": {"color": {"answers": ["Blue"]}, "note": {"answers": []}}}}]
    name, arguments, native, asked_questions = asked[0]
    assert name == "requestUserInput" and native["tool_call_id"] == "item"
    assert asked_questions[0]["options"][1] == {"label": "Blue", "description": "Calm"}
    assert asked_questions[1]["options"] == []
    asked.clear()
    secret = {**params, "questions": [{**questions[0], "isSecret": True}]}
    await client.decide({"id": 10, "method": "item/tool/requestUserInput", "params": secret})
    assert not asked and "error" in sent[-1]


@pytest.mark.asyncio
async def test_sandbox_client_delivers_answers_or_a_confirmation():
    from agno.sandbox.client import RuntimeExecution, SandboxRuntimeClient

    calls = []

    async def rpc(computer, operation, payload):
        calls.append(payload)
        return {"accepted": True}

    client = SimpleNamespace(_rpc=rpc)
    execution = RuntimeExecution(computer=SimpleNamespace(agent_id="a", session_id="s"), execution_id="e", run_id="r")
    base = {"tool_call_id": "t", "digest": "d", "owner": "o"}
    await SandboxRuntimeClient.aresolve(client, execution, {**base, "answers": [["Blue"]]})
    await SandboxRuntimeClient.aresolve(client, execution, {**base, "confirmed": True})
    assert calls[0]["answers"] == [["Blue"]] and "confirmed" not in calls[0]
    assert calls[1]["confirmed"] is True and "answers" not in calls[1]


# ---------------------------------------------------------------------------
# Native policy selection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sdk", ["claude", "codex"])
@pytest.mark.parametrize("nested", [True, False])
def test_runtime_keeps_native_hitl_routing_and_parent_boundary(tmp_path, sdk, nested):
    from agno.sandbox.runtime import _agent

    agent = _agent(
        {
            "agent_id": "test",
            "sdk": sdk,
            "config": {"_native_hitl": True, "_nested_native_hitl": nested},
        },
        tmp_path,
    )
    assert agent._uses_native_hitl
    assert agent._nested_native_hitl is nested


@pytest.mark.parametrize(
    "mode,forwarded",
    [
        (None, True),
        ("default", True),
        ("acceptEdits", True),
        ("plan", True),
        ("bypassPermissions", False),
        ("dontAsk", False),
    ],
)
def test_claude_native_policy_selects_chat_confirmation(tmp_path, mode, forwarded):
    from agno.agents.claude import ClaudeAgent
    from agno.os import AgentOS

    agent = ClaudeAgent(id="claude", permission_mode=mode)
    assert not agent._uses_native_hitl
    AgentOS(agents=[agent], db=SqliteDb(db_file=str(tmp_path / "db")), telemetry=False).get_app()
    assert agent._uses_native_hitl is forwarded
    options = agent._build_options()
    assert options.permission_mode == mode
    assert (options.can_use_tool is not None) is forwarded


def test_claude_explicit_permission_callback_remains_authoritative(tmp_path):
    from claude_agent_sdk import ClaudeAgentOptions

    from agno.agents.claude import ClaudeAgent

    async def decide(*args):
        raise AssertionError("Option inspection must not invoke the callback")

    agent = ClaudeAgent(db=SqliteDb(db_file=str(tmp_path / "db")), options=ClaudeAgentOptions(can_use_tool=decide))
    assert not agent._uses_native_hitl
    assert agent._build_options().can_use_tool is decide


@pytest.mark.parametrize("named,legacy,forwarded", [("default", "dontAsk", False), ("dontAsk", "default", True)])
def test_claude_legacy_policy_precedence_is_preserved(tmp_path, named, legacy, forwarded):
    from agno.agents.claude import ClaudeAgent

    with pytest.warns(DeprecationWarning):
        agent = ClaudeAgent(
            db=SqliteDb(db_file=str(tmp_path / "db")), permission_mode=named, options_kwargs={"permission_mode": legacy}
        )
    assert agent._uses_native_hitl is forwarded
    assert agent._build_options().permission_mode == legacy


@pytest.mark.parametrize(
    "settings,forwarded",
    [
        ({}, True),
        ({"approval_policy": "on-request"}, True),
        ({"approval_policy": "untrusted"}, True),
        ({"approval_policy": "never"}, False),
        ({"approval_mode": "auto_review"}, False),
        ({"approval_mode": "deny_all"}, False),
        ({"config": {"approval_policy": "never"}}, False),
        ({"config": {"approvals_reviewer": "auto_review"}}, False),
        ({"turn_options": {"approval_mode": "deny_all"}}, False),
    ],
)
def test_codex_native_policy_selects_chat_confirmation(tmp_path, settings, forwarded):
    from agno.agents.codex import CodexAgent
    from agno.os import AgentOS
    from agno.sandbox._harness import _config

    agent = CodexAgent(id="codex", **settings)
    assert not agent._uses_native_hitl
    AgentOS(agents=[agent], db=SqliteDb(db_file=str(tmp_path / "db")), telemetry=False).get_app()
    assert agent._uses_native_hitl is forwarded
    config = _config(agent, None)
    assert config.get("_native_hitl", False) is forwarded


# ---------------------------------------------------------------------------
# Codex transport
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", [None, "on-request", "untrusted", "never"])
async def test_codex_transport_preserves_native_policy(monkeypatch, policy):
    pytest.importorskip("openai_codex")
    from openai_codex.client import CodexClient

    from agno.agents.codex._hitl import human_client

    messages = []
    monkeypatch.setattr(CodexClient, "_write_message", lambda self, value: messages.append(value))
    client = human_client(None, None, approval_policy=policy)._client._sync
    for method in ("thread/start", "thread/resume", "turn/start"):
        client._write_message(
            {
                "id": 1,
                "method": method,
                "params": {
                    "approvalPolicy": "on-request",
                    "approvalsReviewer": "auto_review",
                    "sandbox": "danger-full-access",
                },
            }
        )
        params = messages[-1]["params"]
        assert params.get("approvalPolicy") == policy
        assert params["approvalsReviewer"] == "user"
        assert params["sandbox"] == "danger-full-access"


@pytest.mark.asyncio
async def test_codex_reader_does_not_wait_for_a_permission_decision(monkeypatch, tmp_path):
    pytest.importorskip("openai_codex")
    import queue
    import threading

    from openai_codex.client import CodexClient

    from agno.agents import _hitl
    from agno.agents.codex._hitl import human_client

    agent = Harness(id="test", db=SqliteDb(db_file=str(tmp_path / "confirm.db")), hitl_timeout=5)
    bridge = _hitl.HITLBridge(agent, "run", "session", None)
    client = human_client(None, bridge)._client._sync
    incoming = queue.Queue()
    sent = []
    notifications = []
    monkeypatch.setattr(CodexClient, "_write_message", lambda self, message: sent.append(message))
    monkeypatch.setattr(client, "_read_message", incoming.get)
    client._router = SimpleNamespace(
        route_notification=notifications.append, route_response=lambda value: None, fail_all=lambda error: None
    )
    reader = threading.Thread(target=client._reader_loop, daemon=True)
    reader.start()
    incoming.put(
        {
            "id": 1,
            "method": "item/commandExecution/requestApproval",
            "params": {"threadId": "thread", "turnId": "turn", "itemId": "item", "command": "write-marker"},
        }
    )
    incoming.put({"method": "thread/status/changed", "params": {}})
    event, ready = await asyncio.wait_for(bridge.queue.get(), 2)
    ready.set()
    for _ in range(100):
        if notifications:
            break
        await asyncio.sleep(0.01)
    assert notifications, "A pending permission request blocked the SDK reader"
    assert not sent
    request = event.native_request
    decided = RunOutput(
        run_id="run",
        session_id="session",
        agent_id="test",
        status=RunStatus.running,
        metadata={
            KEY: {
                "decisions": {
                    request["tool_call_id"]: {"confirmed": True, "digest": request["digest"], "owner": bridge.owner}
                }
            }
        },
    )

    async def read(*args, **kwargs):
        return decided

    monkeypatch.setattr(_hitl, "read_run", read)
    continued, acknowledged = await asyncio.wait_for(bridge.queue.get(), 3)
    assert continued.event == "RunContinued"
    assert not sent, "The native execution must wait for the continuation to be recorded"
    acknowledged.set()
    for _ in range(100):
        if sent:
            break
        await asyncio.sleep(0.01)
    assert sent == [{"id": 1, "result": {"decision": "accept"}}]
    client._write_message({"id": 2, "method": "thread/start", "params": {"approvalsReviewer": "auto_review"}})
    assert sent[-1]["params"]["approvalsReviewer"] == "user"
    incoming.put(None)
    await asyncio.to_thread(reader.join, 2)
    assert not reader.is_alive()


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [True, False])
@pytest.mark.parametrize("kind", ["fileChange", "permissions"])
async def test_codex_native_decision_shapes(monkeypatch, allowed, kind):
    pytest.importorskip("openai_codex")
    from openai_codex.client import CodexClient

    from agno.agents.codex._hitl import human_client

    requests = []
    sent = []

    async def request(name, arguments, native):
        requests.append((name, arguments, native))
        return allowed

    client = human_client(None, SimpleNamespace(request=request))._client._sync
    monkeypatch.setattr(CodexClient, "_write_message", lambda self, message: sent.append(message))
    changes = [{"path": "/workspace/file.txt", "kind": {"type": "add"}, "diff": "+approved"}]
    client.items["item"] = {"changes": changes}
    permissions = {"network": {"enabled": True}}
    await client.decide(
        {
            "id": 7,
            "method": f"item/{kind}/requestApproval",
            "params": {"threadId": "thread", "turnId": "turn", "itemId": "item", "permissions": permissions},
        }
    )
    if kind == "fileChange":
        assert requests[0][1]["changes"] == changes
        assert sent == [{"id": 7, "result": {"decision": "accept" if allowed else "decline"}}]
    else:
        assert sent == [{"id": 7, "result": {"permissions": permissions if allowed else {}, "scope": "turn"}}]
    requests.clear()
    await client.decide({"id": 8, "method": "item/unknown/requestApproval", "params": {}})
    assert not requests
    assert "error" in sent[-1]


@pytest.mark.asyncio
async def test_codex_closed_transport_does_not_leak_a_callback_exception(monkeypatch):
    pytest.importorskip("openai_codex")
    from agno.agents.codex._hitl import human_client

    async def request(*args):
        return True

    client = human_client(None, SimpleNamespace(request=request))._client._sync
    errors = []

    def closed(payload):
        raise BrokenPipeError("closed")

    monkeypatch.setattr(client, "_write_message", closed)
    monkeypatch.setattr(client._router, "fail_all", errors.append)
    await client.decide(
        {"id": 1, "method": "item/commandExecution/requestApproval", "params": {"command": "echo test", "itemId": "t"}}
    )
    assert len(errors) == 1 and isinstance(errors[0], BrokenPipeError)


# ---------------------------------------------------------------------------
# Persistence boundaries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("database", [SqliteDb, AsyncSqliteDb])
async def test_orphaned_native_pause_can_be_cancelled(tmp_path, database):
    db = database(db_file=str(tmp_path / "orphan.db"))
    agent = Harness(id="agent", db=db)
    run = RunOutput(
        run_id="orphan",
        session_id="session",
        agent_id="agent",
        status=RunStatus.paused,
        requirements=[RunRequirement(tool_execution=ToolExecution(tool_call_id="tool", requires_confirmation=True))],
        metadata={KEY: {"owner": "dead", "pending": ["tool"]}},
    )
    await db_call(db, "upsert_session", AgentSession(session_id="session", agent_id="agent", runs=[run]))
    await db_call(db, "upsert_run", run, session_id="session", run_index=0)
    await agent.acancel_run("orphan")
    await agent.acancel_run("orphan")
    stored = await agent.aget_run_output("orphan", "session")
    assert stored.status == RunStatus.cancelled
    assert not stored.requirements
    assert stored.metadata[KEY]["pending"] == []
    session = await agent.aget_session("session")
    agent._claim_session(session, "session", "next")
    agent._release_session("session", "next")


async def seed_paused(db, pending):
    run = RunOutput(
        run_id="run",
        session_id="session",
        agent_id="agent",
        user_id="user",
        status=RunStatus.paused,
        metadata={KEY: {"owner": "owner", "pending": pending}},
    )
    await db_call(
        db, "upsert_session", AgentSession(session_id="session", agent_id="agent", user_id="user", runs=[run])
    )
    await db_call(db, "upsert_run", run, session_id="session", user_id="user", run_index=0)


def hand_over(pending, marker):
    expected = {"status": "PAUSED", f"metadata.{KEY}.pending": pending}
    fields = {"status": "RUNNING", "metadata": {KEY: {"pending": [], "marker": marker}}}
    return expected, fields


@pytest.mark.asyncio
@pytest.mark.parametrize("database", [SqliteDb, AsyncSqliteDb])
async def test_sqlite_handover_is_conditional_on_the_pending_request(tmp_path, database):
    """A repeated continuation, or a stale one after the run paused again for a new request, writes nothing."""
    db = database(db_file=str(tmp_path / "handover.db"))
    await seed_paused(db, ["second"])
    assert not await db_call(
        db, "update_run_if_matches", "run", "session", *hand_over(["first"], "stale"), user_id="user"
    )
    assert not await db_call(db, "update_run_if_matches", "run", "other", *hand_over(["second"], "x"), user_id="user")
    assert not await db_call(
        db, "update_run_if_matches", "run", "session", *hand_over(["second"], "x"), user_id="other"
    )
    stored = await db_call(db, "get_run", "run")
    assert stored.status == RunStatus.paused and stored.metadata[KEY]["pending"] == ["second"]
    assert await db_call(
        db, "update_run_if_matches", "run", "session", *hand_over(["second"], "second"), user_id="user"
    )
    assert not await db_call(
        db, "update_run_if_matches", "run", "session", *hand_over(["second"], "again"), user_id="user"
    )
    stored = await db_call(db, "get_run", "run")
    assert stored.status == RunStatus.running
    assert stored.metadata[KEY]["marker"] == "second"


@pytest.mark.asyncio
async def test_sqlite_handover_has_one_winner_across_connections(tmp_path):
    """Separate engines on one file, as separate processes would be: exactly one continuation wins."""
    import threading

    path = str(tmp_path / "race.db")
    await seed_paused(SqliteDb(db_file=path), ["tool"])
    databases = [SqliteDb(db_file=path) for _ in range(8)]
    barrier = threading.Barrier(len(databases))

    def attempt(db, index):
        barrier.wait()
        return db.update_run_if_matches("run", "session", *hand_over(["tool"], str(index)), user_id="user")

    results = await asyncio.gather(*(asyncio.to_thread(attempt, db, i) for i, db in enumerate(databases)))
    assert results.count(True) == 1
    stored = SqliteDb(db_file=path).get_run("run")
    assert stored.metadata[KEY]["marker"] == str(results.index(True))


@pytest.mark.asyncio
async def test_stored_tail_detects_a_new_request_without_stored_events():
    run = RunOutput(run_id="run", session_id="session", status=RunStatus.paused, metadata={KEY: {"pending": ["first"]}})
    reads = 0

    async def read(*args, **kwargs):
        nonlocal reads
        reads += 1
        if reads > 1:
            run.metadata[KEY]["pending"] = ["second"]
        return run

    agent = SimpleNamespace(hitl_timeout=0.25, aget_run_output=read)
    items = [item async for item in tail_stored(agent, "run", "session", None, 0)]
    assert items[-1].metadata[KEY]["pending"] == ["second"]
    assert any(getattr(item, "event", None) == "RunPaused" for item in items)


@pytest.mark.asyncio
async def test_stored_tail_sees_a_new_pause_that_lands_before_its_first_read():
    """The native execution can reach its next request before the continuation first reads the run."""
    run = RunOutput(
        run_id="run", session_id="session", status=RunStatus.paused, metadata={KEY: {"pending": ["second"]}}
    )

    async def read(*args, **kwargs):
        return run

    agent = SimpleNamespace(hitl_timeout=0.25, aget_run_output=read)
    items = [item async for item in tail_stored(agent, "run", "session", None, 0, answered={"first"})]
    assert items[-1] is run


@pytest.mark.asyncio
async def test_an_acknowledged_request_is_not_a_new_pause():
    paused = RunOutput(
        run_id="run",
        session_id="session",
        status=RunStatus.paused,
        events=[RunContinuedEvent(native_request_id="first")],
        metadata={KEY: {"pending": ["second"]}},
    )
    completed = RunOutput(run_id="run", session_id="session", status=RunStatus.completed, content="done")
    states = iter([paused, completed])

    async def read(*args, **kwargs):
        return next(states)

    agent = SimpleNamespace(hitl_timeout=0.25, aget_run_output=read)
    items = [item async for item in tail_stored(agent, "run", "session", None, 0, {"first", "second"})]
    assert items[-1].status == RunStatus.completed


@pytest.mark.asyncio
async def test_run_read_is_scoped_without_loading_session_history(tmp_path, monkeypatch):
    from agno.agents._hitl import read_run

    db = SqliteDb(db_file=str(tmp_path / "scope.db"))
    agent = Harness(id="agent", db=db)
    run = RunOutput(run_id="run", session_id="session", agent_id="agent", user_id="user")
    db.upsert_session(AgentSession(session_id="session", agent_id="agent", user_id="user", runs=[run]))
    db.upsert_run(run, session_id="session")

    def reject_full_session(*args, **kwargs):
        pytest.fail("Confirmation polling must not load session history")

    monkeypatch.setattr(db, "get_session", reject_full_session)
    assert (await read_run(agent, "run", "session", "user")).run_id == "run"
    assert await read_run(agent, "run", "session", "other") is None
    assert await read_run(agent, "run", "other", "user") is None
    agent.id = "other"
    assert await read_run(agent, "run", "session", "user") is None


@pytest.mark.asyncio
async def test_sync_postgres_calls_leave_the_event_loop_free():
    import threading

    owner = threading.get_ident()
    db = SimpleNamespace(
        db_engine=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")), get_run=lambda _: threading.get_ident()
    )
    assert await db_call(db, "get_run", "run") != owner


@pytest.mark.asyncio
async def test_sync_continuation_iterator_inside_a_running_loop():
    async def source():
        yield RunContinuedEvent(run_id="run")

    assert [item.event for item in sync_events(source())] == ["RunContinued"]


# ---------------------------------------------------------------------------
# Queue worker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_human_wait_has_a_separate_bounded_budget():
    from agno.agents._hitl import wait_for_execution

    task = asyncio.create_task(asyncio.sleep(0.15))
    assert await wait_for_execution(task, 0.05, 0.5, lambda: True)
    task = asyncio.create_task(asyncio.sleep(0.15))
    assert not await wait_for_execution(task, 0.05, 0.5, lambda: False)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    task = asyncio.create_task(asyncio.sleep(0.15))
    assert not await wait_for_execution(task, 0.5, 0.05, lambda: True)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_budget_read_failure_does_not_cancel_the_native_execution():
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.job_queue import QueueWorker

    async def read(*args, **kwargs):
        raise RuntimeError("transient database outage")

    agent = SimpleNamespace(_uses_native_hitl=True, hitl_timeout=1, aget_run_output=read)
    worker = QueueWorker(
        store=InMemoryQueueStore(),
        resolve_component=lambda *_: agent,
        config=QueueConfig(timeout_seconds=1),
        worker_id="t",
    )
    result = await worker._await_with_timeout(
        asyncio.sleep(0.05, result="done"), None, agent, {"id": "run", "session_id": "session"}
    )
    assert result == "done"


@pytest.mark.asyncio
async def test_budget_poll_retains_the_human_wait_during_a_database_outage(monkeypatch):
    from agno.agents import _hitl
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.job_queue import QueueWorker

    reads = 0

    async def read(*args, **kwargs):
        nonlocal reads
        reads += 1
        if reads == 1:
            return RunOutput(metadata={KEY: {"pending": ["waiting"]}})
        raise RuntimeError("transient database outage")

    monkeypatch.setattr(_hitl, "read_run", read)
    agent = SimpleNamespace(_uses_native_hitl=True, hitl_timeout=3)
    worker = QueueWorker(
        store=InMemoryQueueStore(),
        resolve_component=lambda *_: agent,
        config=QueueConfig(timeout_seconds=0.5),
        worker_id="test",
    )
    assert (
        await worker._await_with_timeout(
            asyncio.sleep(1.3, result="done"), None, agent, {"id": "run", "session_id": "session"}
        )
        == "done"
    )
    assert reads == 2


@pytest.mark.asyncio
async def test_reclaimed_direct_native_run_never_replays(tmp_path):
    from agno.db.schemas.jobs import QueuedJob
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.job_queue import QueueWorker

    db = SqliteDb(db_file=str(tmp_path / "lost-owner.db"))
    agent = Harness(id="test", db=db)
    run = RunOutput(
        run_id="run",
        session_id="session",
        agent_id="test",
        status=RunStatus.paused,
        queue_attempt=1,
        metadata={KEY: {"owner": "lost", "pending": []}},
    )
    db.upsert_session(AgentSession(session_id="session", agent_id="test", runs=[run]))
    db.upsert_run(run, session_id="session", run_index=0)
    store = InMemoryQueueStore()
    await store.enqueue_job(
        QueuedJob(
            id="run",
            component_type="agent",
            component_id="test",
            session_id="session",
            payload={"input": "work", "stream": True},
            max_attempts=2,
        ).to_dict()
    )
    await store.claim_job("lost-worker")
    store._jobs["run"]["locked_at"] = 0
    worker = QueueWorker(
        store=store, resolve_component=lambda *_: agent, config=QueueConfig(durable=True), worker_id="successor"
    )
    job = await store.claim_job("successor")
    assert job["attempt"] == 2
    await asyncio.wait_for(worker._execute_claimed(job), 3)
    assert agent.calls == 0
    assert (await store.get_job("run"))["status"] == "failed"
    assert (await agent.aget_run_output("run", "session")).status == RunStatus.error


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [RunStatus.pending, RunStatus.completed, RunStatus.cancelled])
async def test_never_started_or_terminal_native_job_is_not_failed_on_reclaim(tmp_path, status):
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.job_queue import QueueWorker

    agent = Harness(id="agent", db=SqliteDb(db_file=str(tmp_path / "pending.db")))
    run = RunOutput(
        run_id="run",
        session_id="session",
        agent_id="agent",
        status=status,
        queue_attempt=1,
        metadata={KEY: {"owner": "old", "pending": []}} if status != RunStatus.pending else None,
    )
    agent.db.upsert_session(AgentSession(session_id="session", agent_id="agent", runs=[run]))
    agent.db.upsert_run(run, session_id="session")
    worker = QueueWorker(
        store=InMemoryQueueStore(), resolve_component=lambda *_: agent, config=QueueConfig(durable=True), worker_id="s"
    )
    assert not await worker._ahonor_non_retryable_row(
        agent, {"id": "run", "session_id": "session", "attempt": 2, "component_type": "agent", "component_id": "agent"}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [RunStatus.completed, RunStatus.cancelled])
async def test_reclaimed_terminal_native_run_settles_ticket_without_execution(tmp_path, status):
    from agno.db.schemas.jobs import QueuedJob
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.job_queue import QueueWorker

    agent = Harness(id="agent", db=SqliteDb(db_file=str(tmp_path / "terminal.db")))
    run = RunOutput(
        run_id="run",
        session_id="session",
        agent_id="agent",
        status=status,
        queue_attempt=1,
        metadata={KEY: {"owner": "old", "pending": []}},
    )
    agent.db.upsert_session(AgentSession(session_id="session", agent_id="agent", runs=[run]))
    agent.db.upsert_run(run, session_id="session")
    store = InMemoryQueueStore()
    await store.enqueue_job(
        QueuedJob(
            id="run",
            component_type="agent",
            component_id="agent",
            session_id="session",
            payload={"input": "work", "kwargs": {}},
            max_attempts=3,
        ).to_dict()
    )
    await store.claim_job("old")
    job = await store.claim_job("successor", lock_grace_seconds=0)
    assert job["attempt"] == 2
    worker = QueueWorker(
        store=store, resolve_component=lambda *_: agent, config=QueueConfig(durable=True), worker_id="successor"
    )
    await worker._execute_claimed_inner(job)
    assert (await store.get_job("run"))["status"] == status.value.lower()
    assert agent.calls == 0
    assert (await agent.aget_run_output("run", "session")).status == status
