"""Signing a Codex agent in to a ChatGPT subscription with a device code, from AgentOS.

No call to OpenAI. The Codex SDK is a stand-in that hands out a code and writes auth.json when told to.
"""

import asyncio
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from cryptography.fernet import Fernet
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from agno.agents.codex import CodexAgent, _sign_in, _subscription
from agno.agents.codex import agent as codex_module
from agno.os.manager.sign_in import SignInTools
from agno.os.routers.agents.sign_in import add_sign_in_routes
from agno.os.scopes import get_default_scope_mappings, get_required_scopes_for_route
from agno.sandbox import Sandbox, _harness

OPENAI_KEY = "sk-openai-key-that-must-not-leak"
REFRESH_TOKEN = "refresh-token-from-the-device-code-sign-in"


def signed_in_file() -> Dict[str, Any]:
    return {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {"access_token": "access-token-value", "refresh_token": REFRESH_TOKEN, "account_id": "acct"},
        "last_refresh": datetime(2026, 11, 27, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }


class FakeDb:
    def __init__(self):
        self.rows: Dict[Any, Dict[str, Any]] = {}

    def get_auth_token(self, provider, user_id, service):
        return self.rows.get((provider, user_id, service))

    def upsert_auth_token(self, token):
        self.rows[(token["provider"], token["user_id"], token["service"])] = token
        return token


class FakeSandbox(Sandbox):
    env = None
    network = "isolated"

    async def acreate(self, session_id, *, agent_id=None, generation=1, env=None):
        raise NotImplementedError

    async def aget(self, provider_ref):
        return None

    async def aexec(self, handle, argv, **kwargs):
        raise NotImplementedError

    async def astop(self, handle):
        raise NotImplementedError

    async def adestroy(self, handle):
        raise NotImplementedError


@dataclass
class CodexConfig:
    codex_bin: Optional[str] = None
    env: Optional[dict] = None
    config_overrides: tuple = ()


class FakeCodex:
    """Stands in for Codex: one device-code sign-in that ends when the test says the person entered the code."""

    entered: threading.Event
    succeeds: bool = True
    homes: List[Path] = []
    envs: List[dict] = []
    cancelled: List[str] = []

    def __init__(self, config: Any = None) -> None:
        self.config = config

    async def __aenter__(self) -> "FakeCodex":
        FakeCodex.envs.append(dict(self.config.env))
        FakeCodex.homes.append(Path(self.config.env["CODEX_HOME"]))
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def login_chatgpt_device_code(self) -> Any:
        home = Path(self.config.env["CODEX_HOME"])

        async def wait() -> Any:
            while not FakeCodex.entered.is_set():
                await asyncio.sleep(0.01)
            if FakeCodex.succeeds:
                (home / "auth.json").write_text(json.dumps(signed_in_file()))
            return SimpleNamespace(success=FakeCodex.succeeds, error=None if FakeCodex.succeeds else "access_denied")

        async def cancel() -> None:
            FakeCodex.cancelled.append("login-1")

        return SimpleNamespace(
            login_id="login-1",
            user_code="12AB-CDEFG",
            verification_url="https://auth.openai.com/codex/device",
            wait=wait,
            cancel=cancel,
        )


@pytest.fixture(autouse=True)
def codex(monkeypatch):
    FakeCodex.entered = threading.Event()
    FakeCodex.succeeds = True
    FakeCodex.homes, FakeCodex.envs, FakeCodex.cancelled = [], [], []
    module = ModuleType("openai_codex")
    module.CodexConfig = CodexConfig  # type: ignore[attr-defined]
    module.AsyncCodex = FakeCodex  # type: ignore[attr-defined]
    monkeypatch.setattr(codex_module, "_sdk", lambda: module)
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI_KEY)
    monkeypatch.setenv("AGNO_ENCRYPTION_KEY", Fernet.generate_key().decode())
    _sign_in._attempts.clear()
    _subscription._busy.clear()
    yield FakeCodex
    FakeCodex.entered.set()


async def until(agent: CodexAgent, status: str) -> Dict[str, Any]:
    for _ in range(300):
        seen = await agent.asign_in_status()
        if seen["status"] == status:
            return seen
        await asyncio.sleep(0.01)
    raise AssertionError(f"sign-in never became {status}: {seen}")


async def test_a_sign_in_gives_a_link_and_a_code_and_stores_what_codex_wrote(codex):
    db = FakeDb()
    agent = CodexAgent(id="codex-1", db=db)
    assert (await agent.asign_in_status()) == {"agent_id": "codex-1", "status": "not_signed_in"}

    started = await agent.asign_in()
    assert started["status"] == "waiting"
    assert (started["user_code"], started["verification_url"]) == ("12AB-CDEFG", "https://auth.openai.com/codex/device")
    # Codex is started in an empty folder of its own, with no API key and no other credential.
    assert codex.envs[0]["OPENAI_API_KEY"] == "" and codex.envs[0]["CODEX_ACCESS_TOKEN"] == ""
    assert (await agent.asign_in_status())["user_code"] == "12AB-CDEFG"
    assert db.rows == {}

    codex.entered.set()
    done = await until(agent, "signed_in")
    # Nothing a caller is given holds the sign-in, and the stored row is ciphertext.
    assert REFRESH_TOKEN not in json.dumps([started, done]) and "access-token-value" not in json.dumps([started, done])
    stored = json.dumps(list(db.rows.values()))
    assert ("codex", None, "codex-1") in db.rows
    assert REFRESH_TOKEN not in stored and "access-token-value" not in stored
    # The folder Codex wrote auth.json in is gone.
    assert not codex.homes[0].exists()


async def test_a_signed_in_agent_runs_on_the_sign_in_and_is_never_given_the_api_key(codex):
    db = FakeDb()
    await CodexAgent(id="codex-1", db=db).asign_in()
    codex.entered.set()
    await until(CodexAgent(id="codex-1", db=db), "signed_in")

    # A new instance, as after a restart, with nothing in code but its id and database.
    # (A sandboxed agent is built with a PostgreSQL database; the stand-in is attached after.)
    agent = CodexAgent(id="codex-1", sandbox=FakeSandbox())
    agent.db = db
    assert _harness.env(agent) == {"OPENAI_API_KEY": OPENAI_KEY}
    await agent._aresolve_subscription()
    assert _harness.env(agent) == {}
    assert agent._sandbox_login() is not None
    assert (await _subscription.aload(agent))["tokens"]["refresh_token"] == REFRESH_TOKEN
    # A Codex agent nobody signed in, on the same database, is on its API key as before.
    other = CodexAgent(id="codex-2", sandbox=FakeSandbox())
    other.db = db
    await other._aresolve_subscription()
    assert _harness.env(other) == {"OPENAI_API_KEY": OPENAI_KEY}
    assert other._sandbox_login() is None


async def test_a_refreshed_copy_of_a_signed_in_agent_is_saved_and_a_new_sign_in_replaces_it(codex):
    db = FakeDb()
    agent = CodexAgent(id="codex-1", db=db)
    await agent.asign_in()
    codex.entered.set()
    await until(agent, "signed_in")
    refreshed = {**signed_in_file(), "tokens": {"refresh_token": "rotated", "access_token": "a"}}
    refreshed["last_refresh"] = "2026-12-05T00:00:00Z"
    await _subscription.asave(agent, refreshed)
    assert (await _subscription.aload(agent))["tokens"]["refresh_token"] == "rotated"

    # Signing in again takes the place of the stored copy, although that copy is newer.
    codex.entered = threading.Event()
    await agent.asign_in()
    codex.entered.set()
    for _ in range(300):
        if (await _subscription.aload(agent))["tokens"]["refresh_token"] == REFRESH_TOKEN:
            break
        await asyncio.sleep(0.01)
    assert (await _subscription.aload(agent))["tokens"]["refresh_token"] == REFRESH_TOKEN


async def test_a_sign_in_can_be_given_up_and_a_refused_one_says_so(codex):
    agent = CodexAgent(id="codex-1", db=FakeDb())
    await agent.asign_in()
    assert (await agent.acancel_sign_in()) == {"agent_id": "codex-1", "status": "not_signed_in"}
    for _ in range(300):
        if codex.cancelled:
            break
        await asyncio.sleep(0.01)
    assert codex.cancelled == ["login-1"] and not codex.homes[0].exists()

    codex.succeeds = False
    await agent.asign_in()
    codex.entered.set()
    failed = await until(agent, "failed")
    assert failed["error"] == "access_denied" and agent.db.rows == {}


def test_the_sync_methods_do_the_same(codex):
    db = FakeDb()
    agent = CodexAgent(id="codex-1", db=db)
    assert agent.sign_in()["user_code"] == "12AB-CDEFG"
    assert agent.sign_in_status()["status"] == "waiting"
    codex.entered.set()
    for _ in range(300):
        if agent.sign_in_status()["status"] == "signed_in":
            break
        threading.Event().wait(0.01)
    assert agent.sign_in_status()["status"] == "signed_in" and ("codex", None, "codex-1") in db.rows
    assert agent.cancel_sign_in()["status"] == "signed_in"


@pytest.mark.parametrize(
    "build, expected",
    [
        (lambda: CodexAgent(id="codex-1", db=FakeDb(), auth_json=signed_in_file()), "set in code \\(auth_json\\)"),
        (lambda: CodexAgent(id="codex-1", db=FakeDb(), access_token="token"), "set in code \\(access_token\\)"),
        (lambda: CodexAgent(id="codex-1"), "needs a database"),
    ],
    ids=["auth_json in code", "access_token in code", "no database"],
)
async def test_an_agent_that_cannot_be_signed_in_from_agentos_is_refused(build, expected):
    with pytest.raises(ValueError, match=expected):
        await build().asign_in()


async def test_a_sign_in_needs_the_encryption_key(monkeypatch, codex):
    monkeypatch.delenv("AGNO_ENCRYPTION_KEY")
    with pytest.raises(ValueError, match="AGNO_ENCRYPTION_KEY, which is not set"):
        await CodexAgent(id="codex-1", db=FakeDb()).asign_in()
    assert codex.envs == []


# ---------------------------------------------------------------------------
# REST routes
# ---------------------------------------------------------------------------


def test_the_sign_in_routes_are_admin_only():
    mappings = get_default_scope_mappings()
    for method in ("POST", "GET", "DELETE"):
        assert get_required_scopes_for_route(mappings, method, "/agents/codex-1/sign-in") == ["agent_os:admin"]
    # The broader agent patterns still decide the agent's own routes.
    assert get_required_scopes_for_route(mappings, "GET", "/agents/codex-1") == ["agents:read"]


def test_the_routes_start_read_and_give_up_a_sign_in(codex):
    from agno.agent import Agent

    db = FakeDb()
    served = SimpleNamespace(agents=[CodexAgent(id="codex-1", db=db), Agent(id="writer")], db=None, registry=None)
    router = APIRouter()
    add_sign_in_routes(router, served)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        started = client.post("/agents/codex-1/sign-in")
        assert started.status_code == 200
        assert started.json()["user_code"] == "12AB-CDEFG"
        assert client.get("/agents/codex-1/sign-in").json()["status"] == "waiting"
        assert client.delete("/agents/codex-1/sign-in").json()["status"] == "not_signed_in"

        client.post("/agents/codex-1/sign-in")
        codex.entered.set()
        for _ in range(300):
            body = client.get("/agents/codex-1/sign-in").json()
            if body["status"] == "signed_in":
                break
            threading.Event().wait(0.01)
        assert body["status"] == "signed_in" and REFRESH_TOKEN not in json.dumps(body)

        assert client.post("/agents/nobody/sign-in").status_code == 404
        assert client.post("/agents/writer/sign-in").status_code == 400
    served.agents[0].auth_json = signed_in_file()
    with TestClient(app) as client:
        refused = client.post("/agents/codex-1/sign-in")
        assert refused.status_code == 409 and "set in code" in refused.json()["detail"]


# ---------------------------------------------------------------------------
# Super Agent tools
# ---------------------------------------------------------------------------


class Authority:
    """A person's authority in a chat: an administrator or not."""

    service_account = False
    scheduled = False

    def __init__(self, admin: bool):
        self.admin = admin
        self.context = SimpleNamespace(principal_id="sam")

    def require(self, resource: str, action: str, resource_id: Optional[str] = None) -> None:
        if (resource, action) != ("agent_os", "admin") or not self.admin:
            raise PermissionError(f"Permission required: {resource}:{action}")

    async def arequire(self, resource: str, action: str, resource_id: Optional[str] = None) -> None:
        self.require(resource, action, resource_id)


class Served:
    """The parts of an AgentOS the tools read."""

    db = None
    registry = None
    _manager_app = None

    def __init__(self, agents: List[Any], authorization: bool):
        self.agents, self.authorization = agents, authorization


def tools_for(db: FakeDb, authorization: bool = True) -> SignInTools:
    served = Served([CodexAgent(id="codex-1", db=db)], authorization)
    tools = SignInTools(served)
    tools._served = served  # the toolkit holds its AgentOS weakly
    return tools


async def test_super_agent_gives_an_administrator_the_link_and_the_code(codex):
    db = FakeDb()
    tools = tools_for(db)
    context = SimpleNamespace(authorization=Authority(admin=True), user_id="sam", metadata=None)
    started = json.loads(await tools.astart_agent_sign_in("codex-1", _agno_run_context=context))
    assert (started["user_code"], started["verification_url"]) == ("12AB-CDEFG", "https://auth.openai.com/codex/device")
    assert json.loads(await tools.acheck_agent_sign_in("codex-1", _agno_run_context=context))["status"] == "waiting"
    codex.entered.set()
    for _ in range(300):
        checked = await tools.acheck_agent_sign_in("codex-1", _agno_run_context=context)
        if json.loads(checked)["status"] == "signed_in":
            break
        await asyncio.sleep(0.01)
    assert json.loads(checked)["status"] == "signed_in" and REFRESH_TOKEN not in checked
    assert "is not a Codex agent" in await tools.astart_agent_sign_in("writer", _agno_run_context=context)


@pytest.mark.parametrize("sync", [False, True], ids=["async", "sync"])
async def test_super_agent_refuses_anyone_who_is_not_an_administrator(codex, sync):
    tools = tools_for(FakeDb())
    member = SimpleNamespace(authorization=Authority(admin=False), user_id="sam", metadata=None)
    nobody = SimpleNamespace(authorization=None, user_id=None, metadata=None)
    for context, expected in ((member, "Permission required: agent_os:admin"), (nobody, "administrator is required")):
        if sync:
            answers = [
                await asyncio.to_thread(tools.start_agent_sign_in, "codex-1", context),
                await asyncio.to_thread(tools.check_agent_sign_in, "codex-1", context),
            ]
        else:
            answers = [
                await tools.astart_agent_sign_in("codex-1", _agno_run_context=context),
                await tools.acheck_agent_sign_in("codex-1", _agno_run_context=context),
            ]
        assert all(expected in answer for answer in answers), answers
    assert codex.envs == []


def test_both_tools_are_registered_in_both_kinds():
    tools = tools_for(FakeDb())
    assert set(tools.functions) == {"start_agent_sign_in", "check_agent_sign_in"}
    assert set(tools.async_functions) == {"start_agent_sign_in", "check_agent_sign_in"}
    assert os.environ["AGNO_ENCRYPTION_KEY"]
