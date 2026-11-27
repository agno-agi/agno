"""Claude and Codex agents on vendor subscriptions: no API key reaches the harness, the Codex login
survives a restart, and a Codex agent on a subscription runs one piece of work at a time.

No model calls. The Claude and Codex SDKs are stand-ins.
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from agno.agents.claude import ClaudeAgent
from agno.agents.claude import agent as claude_module
from agno.agents.claude.agent import ClaudeResultError
from agno.agents.codex import CodexAgent, _subscription
from agno.agents.codex import agent as codex_module
from agno.exceptions import AgentBusyError
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.sandbox import Sandbox, _harness
from agno.sandbox.base import ExecResult, SandboxHandle

API_KEY = "sk-ant-api-key-that-must-not-leak"
OPENAI_KEY = "sk-openai-key-that-must-not-leak"


def login(refresh_token: str = "refresh-seed", refreshed: Optional[datetime] = None) -> Dict[str, Any]:
    refreshed = refreshed or datetime(2026, 11, 1, tzinfo=timezone.utc)
    return {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {"access_token": "access-" + refresh_token, "refresh_token": refresh_token, "account_id": "acct"},
        "last_refresh": refreshed.strftime("%Y-%m-%dT%H:%M:%S.%f") + "123Z",
    }


class FakeSandbox(Sandbox):
    """A sandbox with one computer whose only file is the Codex login."""

    def __init__(self, env=None):
        self.env = env
        self.network = "isolated"
        self.auth_json: Optional[str] = None
        self.operations: List[str] = []

    async def acreate(self, session_id, *, agent_id=None, generation=1, env=None):
        raise NotImplementedError

    async def aget(self, provider_ref):
        return None

    async def aexec(self, handle, argv, *, timeout=60, max_output_bytes=1_048_576, stdin=b""):
        if stdin:
            self.operations.append("write")
            self.auth_json = stdin.decode()
            return ExecResult(0, "", "")
        self.operations.append("read")
        return ExecResult(0, self.auth_json or "", "")

    async def astop(self, handle):
        raise NotImplementedError

    async def adestroy(self, handle):
        self.operations.append("destroy")


HANDLE = SandboxHandle("ref", "name", "codex-1", "s1", 1, "running", "digest")


class FakeDb:
    """The auth token methods of a database, holding rows as the table would."""

    def __init__(self):
        self.rows: Dict[Any, Dict[str, Any]] = {}

    def get_auth_token(self, provider, user_id, service):
        return self.rows.get((provider, user_id, service))

    def upsert_auth_token(self, token):
        self.rows[(token["provider"], token["user_id"], token["service"])] = token
        return token


class FakeCoordinator:
    """Stands in for the sandbox coordinator; records each turn and how many ran at once."""

    def __init__(self, hold: float = 0.0):
        self.calls: List[Any] = []
        self.hold = hold
        self.running = 0
        self.most_at_once = 0
        self.order: List[str] = []
        self.logins: Dict[str, Any] = {}

    async def arun(self, session_id, **execution):
        self.calls.append((session_id, execution))
        self.running += 1
        self.most_at_once = max(self.most_at_once, self.running)
        self.order.append("start " + execution["run_id"])
        try:
            await asyncio.sleep(self.hold)
        finally:
            self.running -= 1
            self.order.append("end " + execution["run_id"])
        return RunOutput(
            run_id=execution["run_id"],
            session_id=session_id,
            agent_id=execution["agent_id"],
            status=RunStatus.completed,
            content="done",
        )


@pytest.fixture
def coordinator(monkeypatch):
    fake = FakeCoordinator()
    monkeypatch.setattr(_harness, "coordinator", lambda agent: fake)
    return fake


@pytest.fixture(autouse=True)
def api_keys_on_the_host(monkeypatch):
    """The platform has API keys for its other agents, as a real deployment does."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", API_KEY)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "gateway-token")
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI_KEY)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    _subscription._busy.clear()


# ---------------------------------------------------------------------------
# Claude on an OAuth token
# ---------------------------------------------------------------------------


async def test_claude_oauth_token_is_the_only_credential_in_the_sandbox(coordinator):
    sandbox = FakeSandbox(env={"ANTHROPIC_API_KEY": "scoped-key", "CLAUDE_CODE_USE_BEDROCK": "1", "GH_TOKEN": "gh"})
    agent = ClaudeAgent(id="claude-1", oauth_token=" oauth-token-1 \n", sandbox=sandbox)
    await agent.arun("hello", session_id="s1")
    _, execution = coordinator.calls[0]
    assert execution["env"] == {"CLAUDE_CODE_OAUTH_TOKEN": "oauth-token-1", "GH_TOKEN": "gh"}
    # The token is the sandbox's environment, never part of the request the sandbox stores.
    assert "oauth-token-1" not in json.dumps(execution["config"])
    assert "oauth-token-1" not in repr(agent)


async def test_each_claude_agent_holds_its_own_subscription(coordinator):
    sandbox = FakeSandbox()
    for name, token in (("claude-1", "token-one"), ("claude-2", "token-two")):
        await ClaudeAgent(id=name, oauth_token=token, sandbox=sandbox).arun("hello", session_id=name)
    assert [execution["env"] for _, execution in coordinator.calls] == [
        {"CLAUDE_CODE_OAUTH_TOKEN": "token-one"},
        {"CLAUDE_CODE_OAUTH_TOKEN": "token-two"},
    ]


async def test_claude_with_an_empty_oauth_token_fails_instead_of_using_the_api_key(coordinator):
    # Constructing the agent never fails: the platform must start, and the run says what is wrong.
    agent = ClaudeAgent(id="claude-1", oauth_token="  ", sandbox=FakeSandbox())
    with pytest.raises(
        ValueError, match="claude-1 is set to run on a Claude subscription, but its OAuth token is empty"
    ):
        await agent.arun("hello", session_id="s1")
    assert coordinator.calls == []
    assert API_KEY not in json.dumps(_harness.env(agent))


@dataclass
class ClaudeOptions:
    model: Optional[str] = None
    env: dict = field(default_factory=dict)
    extra_args: dict = field(default_factory=dict)
    resume: Optional[str] = None
    include_partial_messages: bool = False
    can_use_tool: Any = None


def test_claude_on_the_host_is_started_without_the_api_key(monkeypatch):
    monkeypatch.setattr(claude_module, "_sdk", lambda: SimpleNamespace(ClaudeAgentOptions=ClaudeOptions))
    monkeypatch.setenv("CLAUDE_CODE_USE_VERTEX", "1")
    native = ClaudeOptions(env={"ANTHROPIC_API_KEY": "option-key", "KEEP": "1"})
    options = ClaudeAgent(id="claude-1", oauth_token="oauth-token-1", options=native)._build_options()
    # Claude Code inherits the host's environment, so each of these is overridden with nothing.
    assert options.env == {
        "KEEP": "1",
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_AUTH_TOKEN": "",
        "CLAUDE_CODE_USE_BEDROCK": "",
        "CLAUDE_CODE_USE_VERTEX": "",
        "CLAUDE_CODE_USE_FOUNDRY": "",
        "CLAUDE_CODE_OAUTH_TOKEN": "oauth-token-1",
    }
    with pytest.raises(ValueError, match="OAuth token is empty"):
        ClaudeAgent(id="claude-1", oauth_token="")._build_options()


def test_a_refused_claude_oauth_token_says_so():
    class ResultMessage:
        is_error, subtype, errors, result, stop_reason, api_error_status = True, "success", None, "401", None, 401

    sdk = SimpleNamespace(ResultMessage=ResultMessage)
    with pytest.raises(
        ClaudeResultError,
        match="Claude Code OAuth token was refused or has expired.*`claude setup-token`.*No API key was used",
    ):
        ClaudeAgent._check_result_message(sdk, ResultMessage(), "authentication_failed", oauth_token=True)
    with pytest.raises(ClaudeResultError) as error:
        ClaudeAgent._check_result_message(sdk, ResultMessage(), "authentication_failed")
    assert "OAuth token" not in str(error.value)


def test_subscription_credentials_are_not_stored_as_component_configs(monkeypatch):
    monkeypatch.setattr(claude_module, "_sdk", lambda: SimpleNamespace(ClaudeAgentOptions=ClaudeOptions))
    with pytest.raises(ValueError, match="oauth_token cannot be stored"):
        ClaudeAgent(id="claude-1", oauth_token="oauth-token-1").to_dict()
    with pytest.raises(ValueError, match="auth_json cannot be stored"):
        CodexAgent(id="codex-1", auth_json=login()).to_dict()


# ---------------------------------------------------------------------------
# Codex on a ChatGPT sign-in (auth.json)
# ---------------------------------------------------------------------------


async def test_codex_auth_json_keeps_the_api_key_out_of_the_sandbox(coordinator):
    sandbox = FakeSandbox(env={"OPENAI_API_KEY": "scoped-key", "CODEX_API_KEY": "scoped", "GH_TOKEN": "gh"})
    agent = CodexAgent(id="codex-1", auth_json=json.dumps(login()), sandbox=sandbox)
    await agent.arun("hello", session_id="s1")
    _, execution = coordinator.calls[0]
    # With no key in its environment the sandbox runtime has nothing to log Codex in with but the login file.
    assert execution["env"] == {"GH_TOKEN": "gh"}
    assert "refresh-seed" not in json.dumps(execution["config"])
    assert "refresh-seed" not in repr(agent)


async def test_codex_login_is_written_before_the_turn_and_the_refreshed_copy_survives_a_restart():
    db, sandbox = FakeDb(), FakeSandbox()
    agent = CodexAgent(id="codex-1", auth_json=json.dumps(login()), db=db)
    hook = agent._sandbox_login()

    await hook.ainstall(sandbox, HANDLE)
    assert json.loads(sandbox.auth_json) == login()

    # Codex refreshes the login during the turn; the old refresh token no longer works.
    refreshed = login("refresh-rotated", datetime(2026, 11, 9, tzinfo=timezone.utc))
    sandbox.auth_json = json.dumps(refreshed)
    await hook.acollect(sandbox, HANDLE)
    stored = json.dumps(list(db.rows.values()))
    assert ("codex", None, "codex-1") in db.rows
    assert "refresh-rotated" not in stored and "access-" not in stored

    # After a restart the agent is built again from the same environment value.
    restarted = CodexAgent(id="codex-1", auth_json=json.dumps(login()), db=db)
    fresh = FakeSandbox()
    await restarted._sandbox_login().ainstall(fresh, HANDLE)
    assert json.loads(fresh.auth_json)["tokens"]["refresh_token"] == "refresh-rotated"


async def test_a_new_codex_login_replaces_the_stored_one_and_an_older_copy_never_replaces_a_newer():
    db, sandbox = FakeDb(), FakeSandbox()
    agent = CodexAgent(id="codex-1", auth_json=login(), db=db)
    newer = login("refresh-rotated", datetime(2026, 11, 9, tzinfo=timezone.utc))
    sandbox.auth_json = json.dumps(newer)
    await agent._sandbox_login().acollect(sandbox, HANDLE)

    # A sandbox whose Codex has already refreshed past the stored copy keeps its own.
    newest = login("refresh-newest", datetime(2026, 11, 20, tzinfo=timezone.utc))
    sandbox.auth_json = json.dumps(newest)
    await agent._sandbox_login().ainstall(sandbox, HANDLE)
    assert json.loads(sandbox.auth_json) == newest

    # An older file read back from a sandbox does not replace the stored copy.
    sandbox.auth_json = json.dumps(login())
    await agent._sandbox_login().acollect(sandbox, HANDLE)
    assert (await _subscription.aload(agent))["tokens"]["refresh_token"] == "refresh-rotated"

    # The stored copy can only be read with the login it came from: a new one takes its place.
    reseeded = CodexAgent(
        id="codex-1", auth_json=login("refresh-new-sign-in", datetime(2026, 11, 2, tzinfo=timezone.utc)), db=db
    )
    assert (await _subscription.aload(reseeded))["tokens"]["refresh_token"] == "refresh-new-sign-in"


async def test_the_login_is_saved_when_a_sandboxed_turn_fails():
    """The coordinator stops a failed turn's computer; the login is read back before it is removed."""
    from agno.db.postgres import PostgresDb
    from agno.sandbox.coordinator import SandboxCoordinator
    from agno.sandbox.postgres import SandboxLease, SandboxState

    db, sandbox = FakeDb(), FakeSandbox()
    agent = CodexAgent(id="codex-1", auth_json=login(), db=db)
    runner = SandboxCoordinator(PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:1/ai"), sandbox, object())
    runner.logins["codex-1"] = agent._sandbox_login()
    lease = SandboxLease("codex-1", "s1", None, "r1", 1, "owner")
    record = {"computer": HANDLE.__dict__}

    async def begin_stop(lease, **kwargs):
        return SandboxState(lease, datetime.now(timezone.utc) + timedelta(minutes=1), record)

    async def passthrough(*args, **kwargs):
        return {"status": "ERROR"}

    runner.store.abegin_stop = begin_stop
    runner.store.aconfirm_stopped = passthrough
    runner.store.afinish_stop = passthrough
    sandbox.auth_json = json.dumps(login("refresh-rotated", datetime(2026, 11, 9, tzinfo=timezone.utc)))
    await runner._stop(lease, status="ERROR", reason="the turn failed")

    assert sandbox.operations == ["read", "destroy"]
    assert (await _subscription.aload(agent))["tokens"]["refresh_token"] == "refresh-rotated"


@pytest.mark.parametrize(
    "value", ["", "not json", "[]", json.dumps({"OPENAI_API_KEY": "sk-secret-key", "tokens": None})]
)
async def test_an_unusable_codex_login_fails_the_run_without_repeating_it(coordinator, value):
    agent = CodexAgent(id="codex-1", auth_json=value, sandbox=FakeSandbox())
    with pytest.raises(ValueError, match="codex-1 is set to run on a ChatGPT subscription") as error:
        await agent.arun("hello", session_id="s1")
    assert "OPENAI_API_KEY was not used" in str(error.value)
    assert "sk-secret-key" not in str(error.value)
    assert coordinator.calls == []


class FakeAsyncCodex:
    calls: List[Dict[str, Any]] = []

    def __init__(self, config: Any = None) -> None:
        self.config = config

    async def __aenter__(self) -> "FakeAsyncCodex":
        self.calls.append(
            {"op": "client", "env": dict(self.config.env or {}), "overrides": self.config.config_overrides}
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.calls.append({"op": "client_exit"})

    async def account(self) -> Any:
        self.calls.append({"op": "account"})
        return SimpleNamespace(account=None)

    async def login_api_key(self, api_key: str) -> None:
        self.calls.append({"op": "login", "api_key": api_key})


@dataclass
class CodexConfig:
    codex_bin: Optional[str] = None
    env: Optional[dict] = None
    config_overrides: tuple = ()


@pytest.fixture
def codex_sdk(monkeypatch):
    FakeAsyncCodex.calls = []
    module = ModuleType("openai_codex")
    module.CodexConfig = CodexConfig  # type: ignore[attr-defined]
    module.AsyncCodex = FakeAsyncCodex  # type: ignore[attr-defined]
    monkeypatch.setattr(codex_module, "_sdk", lambda: module)
    from agno.agents.codex import _hitl

    monkeypatch.setattr(_hitl, "human_client", lambda config, bridge, **kwargs: FakeAsyncCodex(config))
    return FakeAsyncCodex.calls


async def test_codex_on_the_host_signs_in_with_the_auth_json_and_never_the_api_key(codex_sdk, tmp_path):
    db = FakeDb()
    agent = CodexAgent(id="codex-1", auth_json=login(), db=db, env={"CODEX_HOME": str(tmp_path), "KEEP": "1"})
    auth_json = tmp_path / "auth.json"
    async with agent._new_client():
        assert json.loads(auth_json.read_text()) == login()
        assert auth_json.stat().st_mode & 0o777 == 0o600
        auth_json.write_text(json.dumps(login("refresh-rotated", datetime(2026, 11, 9, tzinfo=timezone.utc))))
    assert [call["op"] for call in codex_sdk] == ["client", "client_exit"]
    assert codex_sdk[0]["env"] == {"CODEX_HOME": str(tmp_path), "KEEP": "1", "OPENAI_API_KEY": "", "CODEX_API_KEY": ""}
    assert codex_sdk[0]["overrides"] == ('cli_auth_credentials_store="file"',)
    assert (await _subscription.aload(agent))["tokens"]["refresh_token"] == "refresh-rotated"


async def test_codex_on_the_host_gets_a_home_of_its_own_by_default(codex_sdk, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "the-developers-own-codex-home"))
    async with CodexAgent(id="codex-1", auth_json=login())._new_client():
        pass
    assert codex_sdk[0]["env"]["CODEX_HOME"] == str(tmp_path / ".agno" / "codex" / "codex-1")
    assert not (tmp_path / "the-developers-own-codex-home").exists()


# ---------------------------------------------------------------------------
# One piece of work at a time
# ---------------------------------------------------------------------------


async def test_a_second_request_to_a_codex_agent_on_a_subscription_is_told_it_is_busy(coordinator):
    coordinator.hold = 0.05
    agent = CodexAgent(id="codex-1", auth_json=login(), sandbox=FakeSandbox())
    first = asyncio.create_task(agent.arun("one", session_id="s1", run_id="r1"))
    await asyncio.sleep(0.01)
    with pytest.raises(AgentBusyError, match="^codex-1 is busy") as error:
        await agent.arun("two", session_id="s2", run_id="r2")
    assert error.value.status_code == 409
    await first
    assert [execution["run_id"] for _, execution in coordinator.calls] == ["r1"]
    # The slot is free again once the first run ends, also for a run that fails.
    await agent.arun("three", session_id="s3", run_id="r3")


async def test_a_busy_codex_agent_refuses_a_queued_run_too_so_the_queue_keeps_it(coordinator):
    from agno.run.concurrency import mark_worker_managed, unmark_worker_managed

    coordinator.hold = 0.05
    agent = CodexAgent(id="codex-1", auth_json=login(), sandbox=FakeSandbox())
    # A second instance of the same agent, as a stored or rebuilt agent would be.
    twin = CodexAgent(id="codex-1", auth_json=login(), sandbox=FakeSandbox())
    mark_worker_managed("r2", "worker", 1)
    try:
        first = asyncio.create_task(agent.arun("one", session_id="s1", run_id="r1"))
        await asyncio.sleep(0.01)
        # The worker hands the ticket back on this error; nothing waits inside the claimed run.
        with pytest.raises(AgentBusyError):
            await twin.arun("two", session_id="s2", run_id="r2")
        await first
    finally:
        unmark_worker_managed("r2")
    assert [execution["run_id"] for _, execution in coordinator.calls] == ["r1"]


async def test_queued_runs_for_one_codex_agent_on_a_subscription_run_one_after_another(coordinator, monkeypatch):
    from agno.db.schemas.jobs import QueuedJob
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.job_queue import QueueWorker

    monkeypatch.setattr("agno.os.job_queue._BUSY_RETRY_SECONDS", 0)
    coordinator.hold = 0.05
    agent = CodexAgent(id="codex-1", auth_json=login(), sandbox=FakeSandbox())
    store = InMemoryQueueStore()
    worker = QueueWorker(
        store=store,
        resolve_component=lambda kind, component_id: agent,
        config=QueueConfig(durable=True, poll_interval=0.02, timeout_seconds=None),
        worker_id="worker",
    )
    for run_id in ("r1", "r2", "r3"):
        job = QueuedJob(
            id=run_id,
            component_type="agent",
            component_id="codex-1",
            session_id="s-" + run_id,
            payload={"input": "work", "kwargs": {}},
        )
        await store.enqueue_job(job.to_dict())

    async def all_completed() -> None:
        while {(await store.get_job(run_id))["status"] for run_id in ("r1", "r2", "r3")} != {"completed"}:
            await asyncio.sleep(0.01)

    await worker.start()
    try:
        await asyncio.wait_for(all_completed(), timeout=5)
    finally:
        await worker.stop()
    assert coordinator.most_at_once == 1 and len(coordinator.calls) == 3
    # Waiting for the agent spent none of the one execution each ticket allows.
    assert [(await store.get_job(run_id))["attempt"] for run_id in ("r1", "r2", "r3")] == [1, 1, 1]


@pytest.mark.parametrize("stream", [False, True], ids=["arun", "stream"])
async def test_a_second_request_to_a_codex_agent_on_the_host_is_told_it_is_busy(codex_sdk, tmp_path, stream):
    from agno.db.in_memory import InMemoryDb

    agent = CodexAgent(id="codex-1", auth_json=login(), db=InMemoryDb(), env={"CODEX_HOME": str(tmp_path)}, retries=2)
    async with agent._asubscription_slot():
        with pytest.raises(AgentBusyError, match="^codex-1 is busy") as error:
            if stream:
                [event async for event in agent.arun("two", session_id="s2", run_id="r2", stream=True)]
            else:
                await agent.arun("two", session_id="s2", run_id="r2")
    assert error.value.status_code == 409
    # Refused before it started: no Codex process, and no failed run left in the session.
    assert codex_sdk == []
    session = await agent.aget_session("s2")
    assert session is None or not session.runs


@pytest.mark.parametrize("approval_policy", [None, "never"], ids=["asks for approval", "never asks"])
def test_agentos_refuses_a_run_for_a_busy_codex_agent_on_the_host(codex_sdk, tmp_path, approval_policy):
    """Over HTTP, as a busy session is refused: 409, or a typed RunError event on a stream, and no run stored.

    An agent that asks for approval is always run in the background by AgentOS, so the default
    configuration takes the background path for both requests.
    """
    from fastapi.testclient import TestClient

    from agno.db.sqlite import SqliteDb
    from agno.os import AgentOS

    db = SqliteDb(db_file=str(tmp_path / "runs.db"))
    agent = CodexAgent(
        id="codex-1",
        auth_json=login(),
        db=db,
        env={"CODEX_HOME": str(tmp_path)},
        **({"approval_policy": approval_policy} if approval_policy else {}),
    )
    assert agent._uses_native_hitl is (approval_policy is None)
    client = TestClient(AgentOS(agents=[agent], db=db).get_app(), raise_server_exceptions=False)
    _subscription._busy.add("codex-1")  # another run of this agent is in flight

    resp = client.post("/agents/codex-1/runs", data={"message": "go", "session_id": "s", "stream": "false"})
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"].startswith("codex-1 is busy")

    resp = client.post("/agents/codex-1/runs", data={"message": "go", "session_id": "s", "stream": "true"})
    assert resp.status_code == 200
    events = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]
    assert [event["event"] for event in events] == ["RunError"]
    assert events[0]["error_type"] == "agent_busy" and events[0]["content"].startswith("codex-1 is busy")

    assert codex_sdk == []
    session = db.get_session(session_id="s", session_type="agent")
    assert session is None or not session.runs


@pytest.mark.parametrize(
    "build",
    [
        lambda sandbox: ClaudeAgent(id="claude-1", oauth_token="oauth-token-1", sandbox=sandbox),
        lambda sandbox: ClaudeAgent(id="claude-key", sandbox=sandbox),
        lambda sandbox: CodexAgent(id="codex-key", sandbox=sandbox),
        lambda sandbox: CodexAgent(id="codex-1", access_token="enterprise-token", sandbox=sandbox),
    ],
    ids=["claude on a subscription", "claude on an API key", "codex on an API key", "codex on an access token"],
)
async def test_other_agents_are_not_limited_to_one_at_a_time(coordinator, build):
    coordinator.hold = 0.03
    agent = build(FakeSandbox())
    await asyncio.gather(*(agent.arun("work", session_id=f"s{n}", run_id=f"r{n}") for n in range(3)))
    assert coordinator.most_at_once == 3


# ---------------------------------------------------------------------------
# API keys only: as before
# ---------------------------------------------------------------------------


async def test_agents_with_only_api_keys_are_given_them_as_before(coordinator, monkeypatch, codex_sdk):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "host-token")
    await ClaudeAgent(id="claude-key", sandbox=FakeSandbox()).arun("hello", session_id="s1")
    await CodexAgent(id="codex-key", sandbox=FakeSandbox()).arun("hello", session_id="s2")
    assert coordinator.calls[0][1]["env"] == {"ANTHROPIC_API_KEY": API_KEY, "CLAUDE_CODE_OAUTH_TOKEN": "host-token"}
    assert coordinator.calls[1][1]["env"] == {"OPENAI_API_KEY": OPENAI_KEY}
    # On the host a Codex agent with no auth_json still logs in with the key.
    async with CodexAgent(id="codex-key")._new_client():
        pass
    assert [call for call in codex_sdk if call["op"] == "login"] == [{"op": "login", "api_key": OPENAI_KEY}]
    assert "CODEX_HOME" not in codex_sdk[0]["env"]


# ---------------------------------------------------------------------------
# Codex on a ChatGPT Enterprise access token
# ---------------------------------------------------------------------------


async def test_codex_access_token_is_the_only_credential_in_the_sandbox(coordinator):
    sandbox = FakeSandbox(env={"OPENAI_API_KEY": "scoped-key", "CODEX_API_KEY": "scoped", "GH_TOKEN": "gh"})
    agent = CodexAgent(id="codex-1", access_token=" enterprise-token \n", sandbox=sandbox)
    await agent.arun("hello", session_id="s1")
    _, execution = coordinator.calls[0]
    assert execution["env"] == {"CODEX_ACCESS_TOKEN": "enterprise-token", "GH_TOKEN": "gh"}
    assert "enterprise-token" not in json.dumps(execution["config"])
    assert "enterprise-token" not in repr(agent)
    # The token is not replaced as Codex works, so there is nothing to write into the sandbox or save after.
    assert agent._sandbox_login() is None
    with pytest.raises(ValueError, match="access_token cannot be stored"):
        CodexAgent(id="codex-1", access_token="enterprise-token").to_dict()


async def test_codex_on_the_host_signs_in_with_the_access_token_and_never_the_api_key(codex_sdk, tmp_path):
    agent = CodexAgent(id="codex-1", access_token="enterprise-token", env={"CODEX_HOME": str(tmp_path), "KEEP": "1"})
    async with agent._new_client():
        pass
    assert [call["op"] for call in codex_sdk] == ["client", "client_exit"]
    assert codex_sdk[0]["env"] == {
        "CODEX_HOME": str(tmp_path),
        "KEEP": "1",
        "OPENAI_API_KEY": "",
        "CODEX_API_KEY": "",
        "CODEX_ACCESS_TOKEN": "enterprise-token",
    }
    assert not (tmp_path / "auth.json").exists()


def test_codex_takes_a_sign_in_or_an_access_token_not_both():
    with pytest.raises(ValueError, match="takes auth_json .* or access_token .*, not both"):
        CodexAgent(id="codex-1", auth_json=login(), access_token="enterprise-token")


async def test_codex_with_an_empty_access_token_fails_instead_of_using_the_api_key(coordinator):
    agent = CodexAgent(id="codex-1", access_token=" ", sandbox=FakeSandbox())
    with pytest.raises(ValueError, match="codex-1 is set to run on a ChatGPT Enterprise workspace.*is empty"):
        await agent.arun("hello", session_id="s1")
    assert coordinator.calls == []
    assert OPENAI_KEY not in json.dumps(_harness.env(agent))


def test_a_refused_codex_access_token_says_so(monkeypatch):
    refused = "unexpected status 401 Unauthorized: token expired"
    message = CodexAgent(id="codex-1", access_token="enterprise-token")._turn_failure(refused)
    assert "The Codex access token (CODEX_ACCESS_TOKEN) was refused or has expired" in message
    assert "No API key was used" in message
    # Another failure of the same agent, and the same failure of an agent on an API key, are left as they are.
    assert CodexAgent(id="codex-1", access_token="enterprise-token")._turn_failure("out of disk") == (
        "Codex turn failed: out of disk"
    )
    assert CodexAgent(id="codex-key")._turn_failure(refused) == "Codex turn failed: " + refused
    # Inside a sandbox the agent has no access_token setting, only the variable and no API key.
    monkeypatch.setenv("CODEX_ACCESS_TOKEN", "enterprise-token")
    monkeypatch.delenv("OPENAI_API_KEY")
    assert "Codex access token" in CodexAgent(id="codex-1")._turn_failure(refused)
