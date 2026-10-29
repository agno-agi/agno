import asyncio
from dataclasses import dataclass

import pytest

from agno.agents._approval import current_bridge, db_call, submit_decisions
from agno.agents.base import BaseExternalAgent
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.run.agent import RunContentEvent
from agno.run.base import RunStatus


@dataclass
class Harness(BaseExternalAgent):
    @property
    def _uses_native_approvals(self):
        return self.db is not None

    calls: int = 0
    executions: int = 0

    def acontinue_run(self, run_response=None, **kwargs):
        from agno.agents._approval import continue_run

        return continue_run(self, run_response, **kwargs)

    async def _arun_adapter_stream(self, input, **kwargs):
        self.calls += 1
        allowed = await current_bridge().request("Bash", {"command": "write-marker"}, {"sdk": "fixture"})
        if allowed:
            self.executions += 1
        yield RunContentEvent(content="allowed" if allowed else "denied")


async def pending(agent, run_id="run"):
    for _ in range(200):
        run = await agent.aget_run_output(run_id, session_id="session")
        if run is not None and run.status == RunStatus.paused:
            return run
        await asyncio.sleep(0.01)
    raise AssertionError("No persisted pause")


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [True, False])
@pytest.mark.parametrize("database", [SqliteDb, AsyncSqliteDb])
async def test_native_decision_releases_same_process_once(tmp_path, approved, database):
    db = database(db_file=str(tmp_path / "approvals.db"))
    agent = Harness(id="test", db=db, approval_timeout=5)
    task = asyncio.create_task(agent.arun("work", session_id="session", run_id="run"))
    try:
        run = await pending(agent)
        assert agent.executions == 0
        assert agent.calls == 1
        assert run.requirements[0].needs_confirmation
        approval_id = run.requirements[0].tool_execution.approval_id
        with pytest.raises(ValueError, match="Resolve"):
            await submit_decisions(agent, "run", "session", None)
        await db_call(
            db, "update_approval", approval_id, expected_status="pending", status="approved" if approved else "rejected"
        )
        await asyncio.sleep(0.15)
        assert not task.done(), "Resolve alone must not release a native permission gate"
        await submit_decisions(agent, "run", "session", None)
        await submit_decisions(agent, "run", "session", None)
        result = await asyncio.wait_for(task, 3)
        assert result.status == RunStatus.completed
        assert result.content == ("allowed" if approved else "denied")
        assert agent.calls == 1
        assert agent.executions == int(approved)
        with pytest.raises(ValueError, match="no longer available"):
            await submit_decisions(agent, "run", "session", None)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_expiry_does_not_execute(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "approvals.db"))
    agent = Harness(id="test", db=db, approval_timeout=0.2)
    result = await agent.arun("work", session_id="session", run_id="run")
    assert result.status == RunStatus.error
    assert "expired" in result.content
    assert agent.executions == 0
    rows, _ = db.get_approvals(run_id="run")
    assert rows[0]["status"] == "expired"


def test_automatic_approvals_require_storage():
    assert not Harness()._uses_native_approvals


@pytest.mark.parametrize("sdk", ["claude", "codex"])
@pytest.mark.parametrize("nested", [True, False])
def test_runtime_keeps_native_approval_routing_and_parent_boundary(tmp_path, sdk, nested):
    from agno.sandbox.runtime import _agent

    agent = _agent(
        {"agent_id": "test", "sdk": sdk, "config": {"_native_approvals": True, "_nested_native_approvals": nested}},
        tmp_path,
    )
    assert agent._uses_native_approvals
    assert agent._nested_native_approvals is nested


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
def test_claude_native_policy_selects_automatic_forwarding(tmp_path, mode, forwarded):
    from agno.agents.claude import ClaudeAgent
    from agno.os import AgentOS

    agent = ClaudeAgent(id="claude", permission_mode=mode)
    assert not agent._uses_native_approvals
    AgentOS(agents=[agent], db=SqliteDb(db_file=str(tmp_path / "db")), telemetry=False).get_app()
    assert agent._uses_native_approvals is forwarded
    options = agent._build_options()
    assert options.permission_mode == mode
    assert (options.can_use_tool is not None) is forwarded


def test_claude_explicit_permission_callback_remains_authoritative(tmp_path):
    from claude_agent_sdk import ClaudeAgentOptions

    from agno.agents.claude import ClaudeAgent

    async def decide(*args):
        raise AssertionError("Option inspection must not invoke the callback")

    agent = ClaudeAgent(db=SqliteDb(db_file=str(tmp_path / "db")), options=ClaudeAgentOptions(can_use_tool=decide))
    assert not agent._uses_native_approvals
    assert agent._build_options().can_use_tool is decide


@pytest.mark.parametrize("named,legacy,forwarded", [("default", "dontAsk", False), ("dontAsk", "default", True)])
def test_claude_legacy_policy_precedence_is_preserved(tmp_path, named, legacy, forwarded):
    from agno.agents.claude import ClaudeAgent

    with pytest.warns(DeprecationWarning):
        agent = ClaudeAgent(
            db=SqliteDb(db_file=str(tmp_path / "db")), permission_mode=named, options_kwargs={"permission_mode": legacy}
        )
    assert agent._uses_native_approvals is forwarded
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
def test_codex_native_policy_selects_automatic_forwarding(tmp_path, settings, forwarded):
    from agno.agents.codex import CodexAgent
    from agno.os import AgentOS
    from agno.sandbox._harness import _config

    agent = CodexAgent(id="codex", **settings)
    assert not agent._uses_native_approvals
    AgentOS(agents=[agent], db=SqliteDb(db_file=str(tmp_path / "db")), telemetry=False).get_app()
    assert agent._uses_native_approvals is forwarded
    config = _config(agent, None)
    assert config.get("_native_approvals", False) is forwarded
    assert config.get("approval_mode") != "human"


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", [None, "on-request", "untrusted", "never"])
async def test_codex_transport_preserves_native_policy(monkeypatch, policy):
    pytest.importorskip("openai_codex")
    from openai_codex.client import CodexClient

    from agno.agents.codex._approval import human_client

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
@pytest.mark.parametrize("parent", ["_team_id", "_workflow_id"])
@pytest.mark.parametrize("stream", [True, False])
async def test_nested_permission_request_fails_without_executing(tmp_path, parent, stream):
    agent = Harness(db=SqliteDb(db_file=str(tmp_path / "db")))
    result = agent.arun("work", stream=stream, yield_run_output=True, **{parent: "parent"})
    if stream:
        from agno.run.agent import RunOutput

        outputs = [item async for item in result if isinstance(item, RunOutput)]
        result = outputs[-1]
    else:
        result = await result
    assert result.status == RunStatus.error
    assert "standalone" in result.content
    assert agent.calls == 1
    assert agent.executions == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("parent", ["_team_id", "_workflow_id"])
async def test_nested_run_without_permission_request_keeps_working(tmp_path, parent, monkeypatch):
    agent = Harness(db=SqliteDb(db_file=str(tmp_path / "db")))

    async def source(input, **kwargs):
        yield RunContentEvent(content="done")

    monkeypatch.setattr(agent, "_arun_adapter_stream", source)
    result = await agent.arun("work", **{parent: "parent"})
    assert result.status == RunStatus.completed
    assert result.content == "done"


@pytest.mark.parametrize("sdk", ["claude", "codex"])
@pytest.mark.parametrize("stream", [True, False])
def test_public_sync_continuation_releases_original_run(tmp_path, monkeypatch, caplog, sdk, stream):
    import time
    from concurrent.futures import ThreadPoolExecutor

    from agno.agents.claude import ClaudeAgent
    from agno.agents.codex import CodexAgent
    from agno.run.agent import RunOutput

    db = SqliteDb(db_file=str(tmp_path / "db"))
    cls = ClaudeAgent if sdk == "claude" else CodexAgent
    agent = cls(id="test", db=db, approval_timeout=5)
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
        for _ in range(200):
            rows, _ = db.get_approvals(run_id="run")
            run = agent.get_run_output("run", "session")
            if rows and run is not None and run.status == RunStatus.paused:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("No persisted approval")
        db.update_approval(rows[0]["id"], status="approved")
        result = agent.continue_run(run_id="run", session_id="session", stream=stream)
        if stream:
            result = next(event for event in result if isinstance(event, RunOutput))
        assert result.status == RunStatus.completed
        assert running.result(timeout=2).status == RunStatus.completed
    assert executed == ["marker"]
    assert "Task was destroyed" not in caplog.text


@pytest.mark.asyncio
async def test_changed_arguments_and_wrong_session_refused(tmp_path):
    from agno.models.response import ToolExecution

    db = SqliteDb(db_file=str(tmp_path / "approvals.db"))
    agent = Harness(id="test", db=db, approval_timeout=5)
    task = asyncio.create_task(agent.arun("work", session_id="session", run_id="run"))
    try:
        run = await pending(agent)
        tool = run.requirements[0].tool_execution
        db.update_approval(tool.approval_id, status="approved")
        changed = ToolExecution.from_dict(tool.to_dict())
        changed.tool_args = {"command": "different-action"}
        changed.confirmed = True
        with pytest.raises(ValueError, match="does not match"):
            await submit_decisions(agent, "run", "session", None, [changed])
        with pytest.raises(ValueError, match="not found"):
            await submit_decisions(agent, "run", "other-session", None)
        assert agent.executions == 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancel_waiting_request_never_executes(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "approvals.db"))
    agent = Harness(id="test", db=db, approval_timeout=5)
    task = asyncio.create_task(agent.arun("work", session_id="session", run_id="run"))
    run = await pending(agent)
    await agent.acancel_run("run")
    result = await asyncio.wait_for(task, 2)
    assert result.status == RunStatus.cancelled
    assert agent.executions == 0
    assert db.get_approval(run.requirements[0].tool_execution.approval_id)["status"] == "cancelled"


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_status", [RunStatus.paused, RunStatus.running])
async def test_snapshot_failure_never_releases_native_action(tmp_path, monkeypatch, failed_status):
    db = SqliteDb(db_file=str(tmp_path / "approvals.db"))
    agent = Harness(id="test", db=db, approval_timeout=5)
    persist = agent._apersist_run_in_session

    async def fail_snapshot(session, run, **kwargs):
        if run.status == failed_status and (run.metadata or {}).get("native_approval"):
            raise RuntimeError("snapshot unavailable")
        return await persist(session, run, **kwargs)

    monkeypatch.setattr(agent, "_apersist_run_in_session", fail_snapshot)
    task = asyncio.create_task(agent.arun("work", session_id="session", run_id="run"))
    try:
        if failed_status == RunStatus.running:
            run = await pending(agent)
            approval_id = run.requirements[0].tool_execution.approval_id
            db.update_approval(approval_id, status="approved")
            await submit_decisions(agent, "run", "session", None)
        result = await asyncio.wait_for(task, 3)
        assert result.status == RunStatus.error
        assert "snapshot unavailable" in result.content
        assert agent.executions == 0
        rows, _ = db.get_approvals(run_id="run")
        assert rows[0]["status"] == "cancelled"
        assert rows[0]["run_status"] == "ERROR"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_codex_reader_does_not_wait_for_permission(monkeypatch, tmp_path):
    pytest.importorskip("openai_codex")
    import queue
    import threading
    from types import SimpleNamespace

    from openai_codex.client import CodexClient

    from agno.agents._approval import ApprovalBridge
    from agno.agents.codex._approval import human_client

    db = SqliteDb(db_file=str(tmp_path / "approvals.db"))
    agent = Harness(id="test", db=db, approval_timeout=5)
    bridge = ApprovalBridge(agent, "run", "session", None)
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
    assert notifications, "An unresolved approval blocked the SDK reader"
    assert not sent
    record = event.approval
    db.update_approval(
        record["id"], status="approved", resolution_data={"native_approval": record["context"]["native_approval"]}
    )
    continued, acknowledged = await asyncio.wait_for(bridge.queue.get(), 2)
    assert continued.event == "RunContinued"
    assert not sent, "Native execution must wait for durable continuation acknowledgement"
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
async def test_agentos_approval_api_to_live_harness(tmp_path):
    import httpx

    from agno.os import AgentOS
    from agno.run.background import await_background_runs

    db = SqliteDb(db_file=str(tmp_path / "api.db"))
    agent = Harness(id="test", db=db, approval_timeout=5)
    app = AgentOS(id="approval-test", db=db, agents=[agent]).get_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/agents/test/runs", data={"message": "work", "session_id": "session", "stream": "false"}
        )
        assert response.status_code == 202, response.text
        run_id = response.json()["run_id"]
        run = await pending(agent, run_id)
        approval_id = run.requirements[0].tool_execution.approval_id
        response = await client.post(
            f"/agents/test/runs/{run_id}/continue", data={"session_id": "session", "stream": "false"}
        )
        assert response.status_code == 409, response.text
        response = await client.post(
            f"/approvals/{approval_id}/resolve",
            json={"status": "approved", "resolution_data": {"native_approval": {"owner": "forged"}}},
        )
        assert response.status_code == 400, response.text
        response = await client.post(f"/approvals/{approval_id}/resolve", json={"status": "approved"})
        assert response.status_code == 200, response.text
        response = await client.post(
            f"/agents/test/runs/{run_id}/continue", data={"session_id": "session", "stream": "true"}
        )
        assert response.status_code == 200, response.text
        assert "RunContinued" in response.text
        assert "RunCompleted" in response.text
        await await_background_runs(timeout=2)
        result = await agent.aget_run_output(run_id, session_id="session")
        assert result.status == RunStatus.completed
        assert result.content == "allowed"


@pytest.mark.asyncio
async def test_parallel_requests_are_all_persisted_before_release(tmp_path):
    @dataclass
    class ParallelHarness(Harness):
        async def _arun_adapter_stream(self, input, **kwargs):
            results = await asyncio.gather(
                current_bridge().request("Bash", {"command": "one"}, {"tool_call_id": "one"}),
                current_bridge().request("Bash", {"command": "two"}, {"tool_call_id": "two"}),
            )
            self.executions = sum(results)
            yield RunContentEvent(content="done")

    db = SqliteDb(db_file=str(tmp_path / "parallel.db"))
    agent = ParallelHarness(id="parallel", db=db, approval_timeout=5)
    task = asyncio.create_task(agent.arun("work", run_id="run", session_id="session"))
    try:
        for _ in range(100):
            run = await pending(agent)
            if len(run.requirements or []) == 2:
                break
            await asyncio.sleep(0.01)
        assert len(run.requirements) == 2
        for requirement, status in zip(run.requirements, ("approved", "rejected")):
            db.update_approval(requirement.tool_execution.approval_id, status=status)
        await submit_decisions(agent, "run", "session", None)
        result = await asyncio.wait_for(task, 3)
        assert result.status == RunStatus.completed
        assert agent.executions == 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_human_wait_has_a_separate_bounded_budget():
    from agno.agents._approval import wait_for_execution

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
async def test_reclaimed_direct_native_run_never_replays(tmp_path):
    from agno.db.schemas.jobs import QueuedJob
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.job_queue import QueueWorker
    from agno.run.agent import RunOutput
    from agno.session import AgentSession

    db = SqliteDb(db_file=str(tmp_path / "lost-owner.db"))
    agent = Harness(id="test", db=db)
    run = RunOutput(
        run_id="run",
        session_id="session",
        agent_id="test",
        status=RunStatus.paused,
        queue_attempt=1,
        metadata={"native_approval": {"owner": "lost", "approval_ids": []}},
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
@pytest.mark.parametrize("allowed", [True, False])
@pytest.mark.parametrize("kind", ["fileChange", "permissions"])
async def test_codex_native_decision_shapes(monkeypatch, allowed, kind):
    pytest.importorskip("openai_codex")
    from types import SimpleNamespace

    from openai_codex.client import CodexClient

    from agno.agents.codex._approval import human_client

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
