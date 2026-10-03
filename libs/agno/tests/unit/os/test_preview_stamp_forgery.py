"""The draft-preview version stamp must never be caller-forgeable.

A2 regression (from 6395f7aa6): the version stamp ``agno_component_version``
lives in ordinary run metadata, which is a caller-writable form field. A
non-owner refused ``version=N`` at run-start (404) could instead start an
UNPINNED run while smuggling ``{"agno_component_version": N}`` into the
request's ``metadata`` field. The forged key persisted onto the run, and
``/continue`` re-resolved and executed the very draft the caller was
forbidden to preview.

Two independent guards, both pinned here:

1. At run-start ``stamp_component_version`` POPS any inbound stamp out of the
   caller metadata BEFORE forwarding, and (re)writes it only when the route's
   own ``version`` parameter pinned one. A forged key never survives.

2. Every stamped-continue block RE-RUNS the run-start preview gate
   (``allow_draft_preview``) before trusting the stamp, raising the SAME 404
   as the run-start route on denial. A stamp naming a version the caller may
   not preview does not resolve, even if it somehow reached the run.

Plus: the scheduler executor scrubs ``agno_component_version`` from a crafted
schedule payload so a schedule cannot become a draft-preview smuggling channel.
"""

import json
from types import SimpleNamespace
from typing import Any, AsyncIterator, Iterator, Optional
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from agno.agent.agent import Agent
from agno.db.schemas.scheduler import DISPATCH_CHAIN_METADATA_KEY, DISPATCH_DEPTH_METADATA_KEY
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS
from agno.os.utils import COMPONENT_VERSION_METADATA_KEY
from agno.registry import Registry
from agno.team.team import Team
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow


class ScriptedModel(Model):
    """Offline model whose canned reply names the version that executed."""

    def __init__(self, model_id: str, reply: str):
        super().__init__(id=model_id, name=model_id, provider="test")
        self._reply = reply

    def _resp(self) -> ModelResponse:
        return ModelResponse(content=self._reply, role="assistant", response_usage=MessageMetrics())

    def invoke(self, *a, **k) -> ModelResponse:
        return self._resp()

    async def ainvoke(self, *a, **k) -> ModelResponse:
        return self._resp()

    def invoke_stream(self, *a, **k) -> Iterator[ModelResponse]:
        yield self._resp()

    async def ainvoke_stream(self, *a, **k) -> AsyncIterator[ModelResponse]:
        yield self._resp()

    def parse_args(self, *a, **k):
        return {}

    def _parse_provider_response(self, response: Any, **k) -> ModelResponse:
        return self._resp()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._resp()


@pytest.fixture
def db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "forgery.db"))


@pytest.fixture
def model_v1():
    return ScriptedModel("model-v1", "answer from v1")


@pytest.fixture
def model_v2():
    return ScriptedModel("model-v2", "answer from v2")


@pytest.fixture
def registry(db, model_v1, model_v2):
    return Registry(name="forgery-registry", dbs=[db], models=[model_v1, model_v2])


def _scoped_middleware(*, user_id: Optional[str], scopes, isolation: bool = False):
    """Mirror what AgentOS's JWT middleware writes to request.state.

    ``authorization_enabled`` is left False so the route-level RBAC dependency
    is a no-op — these tests target the draft-preview gate, not RBAC.
    """

    class _M(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.user_id = user_id
            request.state.scopes = list(scopes)
            request.state.user_isolation_enabled = isolation
            request.state.authorization_enabled = False
            return await call_next(request)

    return _M


# A scoped, authenticated caller who is NOT the draft owner and not admin.
_BOB = dict(user_id="bob", scopes=["agents:run", "teams:run", "workflows:run"])
# An admin caller (privileged: may preview anyone's draft).
_ADMIN = dict(user_id="admin", scopes=["agent_os:admin"])


def _client(app, caller) -> TestClient:
    app.add_middleware(_scoped_middleware(**caller))
    return TestClient(app, raise_server_exceptions=False)


def _save_agent(db, model_v1, model_v2, component_id="pv-agent") -> str:
    """v1 published (current), v2 draft, unowned (shared)."""
    Agent(id=component_id, name="PV", model=model_v1, instructions="You are v1").save(db=db, stage="published")
    Agent(id=component_id, name="PV", model=model_v2, instructions="You are v2").save(db=db, stage="draft")
    return component_id


def _save_team(db, model_v1, model_v2, component_id="pv-team") -> str:
    member = Agent(id="fm-member", name="M", model=model_v1, instructions="member")
    member.save(db=db, stage="published")
    Team(id=component_id, name="PVTeam", model=model_v1, members=[member], instructions="You are v1").save(
        db=db, stage="published"
    )
    Team(id=component_id, name="PVTeam", model=model_v2, members=[member], instructions="You are v2").save(
        db=db, stage="draft"
    )
    return component_id


# ---------------------------------------------------------------------------
# Guard 1: a forged stamp is stripped at run-start (end-to-end exploit)
# ---------------------------------------------------------------------------


class TestForgedStampStrippedAtRunStart:
    """The executed exploit: a non-owner refused version=2 starts an UNPINNED
    run smuggling the stamp in caller metadata. The stamp must NOT survive, so
    /continue keeps today's published resolution instead of the draft."""

    def test_agent_forged_metadata_stamp_does_not_survive(self, db, registry, model_v1, model_v2):
        agent_id = _save_agent(db, model_v1, model_v2)
        client = _client(AgentOS(db=db, registry=registry, telemetry=False).get_app(), _BOB)

        # Refused the draft preview outright.
        refused = client.post(f"/agents/{agent_id}/runs", data={"message": "hi", "stream": "false", "version": "2"})
        assert refused.status_code == 404, refused.text

        # Unpinned run smuggling the forged stamp: runs v1, stamp stripped.
        start = client.post(
            f"/agents/{agent_id}/runs",
            data={"message": "hi", "stream": "false", "metadata": '{"agno_component_version": 2}'},
        )
        assert start.status_code == 200, start.text
        body = start.json()
        assert body["content"] == "answer from v1"
        assert COMPONENT_VERSION_METADATA_KEY not in (body.get("metadata") or {})

        stored = client.get(f"/agents/{agent_id}/runs/{body['run_id']}", params={"session_id": body["session_id"]})
        assert COMPONENT_VERSION_METADATA_KEY not in (stored.json().get("metadata") or {})

        # Continue resolves the CURRENT published v1, never the forbidden draft.
        cont = client.post(
            f"/agents/{agent_id}/runs/{body['run_id']}/continue",
            data={"input": "again", "session_id": body["session_id"], "stream": "false"},
        )
        assert cont.status_code == 200, cont.text
        assert cont.json()["content"] == "answer from v1"

    def test_agent_forged_stamp_preserves_other_caller_metadata(self, db, registry, model_v1, model_v2):
        """Only the stamp is scrubbed; the caller's own metadata keys survive."""
        agent_id = _save_agent(db, model_v1, model_v2)
        client = _client(AgentOS(db=db, registry=registry, telemetry=False).get_app(), _BOB)

        start = client.post(
            f"/agents/{agent_id}/runs",
            data={"message": "hi", "stream": "false", "metadata": '{"agno_component_version": 2, "trace": "keep"}'},
        )
        assert start.status_code == 200, start.text
        meta = start.json().get("metadata") or {}
        assert meta.get("trace") == "keep"
        assert COMPONENT_VERSION_METADATA_KEY not in meta

    def test_a_forged_dispatch_chain_is_stripped_at_run_start(self, db, registry, model_v1, model_v2):
        # Defence in depth: a caller forging the dispatch lineage can only
        # shorten their own reach (the guard fails closed on garbage and a
        # pre-seeded chain only restricts), but the runtime-owned keys still
        # never enter through a caller-writable form field.
        agent_id = _save_agent(db, model_v1, model_v2)
        client = _client(AgentOS(db=db, registry=registry, telemetry=False).get_app(), _BOB)

        start = client.post(
            f"/agents/{agent_id}/runs",
            data={
                "message": "hi",
                "stream": "false",
                "metadata": '{"agno_dispatch_chain": ["team:x"], "agno_dispatch_depth": 0, "trace": "keep"}',
            },
        )
        assert start.status_code == 200, start.text
        body = start.json()
        meta = body.get("metadata") or {}
        assert meta.get("trace") == "keep"
        assert DISPATCH_CHAIN_METADATA_KEY not in meta
        assert DISPATCH_DEPTH_METADATA_KEY not in meta

        stored = client.get(f"/agents/{agent_id}/runs/{body['run_id']}", params={"session_id": body["session_id"]})
        stored_meta = stored.json().get("metadata") or {}
        assert DISPATCH_CHAIN_METADATA_KEY not in stored_meta
        assert DISPATCH_DEPTH_METADATA_KEY not in stored_meta

    def test_team_forged_metadata_stamp_does_not_survive(self, db, registry, model_v1, model_v2):
        team_id = _save_team(db, model_v1, model_v2)
        client = _client(AgentOS(db=db, registry=registry, telemetry=False).get_app(), _BOB)

        refused = client.post(f"/teams/{team_id}/runs", data={"message": "hi", "stream": "false", "version": "2"})
        assert refused.status_code == 404, refused.text

        start = client.post(
            f"/teams/{team_id}/runs",
            data={"message": "hi", "stream": "false", "metadata": '{"agno_component_version": 2}'},
        )
        assert start.status_code == 200, start.text
        body = start.json()
        assert body["content"] == "answer from v1"
        assert COMPONENT_VERSION_METADATA_KEY not in (body.get("metadata") or {})

        cont = client.post(
            f"/teams/{team_id}/runs/{body['run_id']}/continue",
            data={"input": "again", "session_id": body["session_id"], "stream": "false"},
        )
        assert cont.status_code == 200, cont.text
        assert cont.json()["content"] == "answer from v1"

    def test_workflow_forged_metadata_stamp_does_not_survive(self, db, registry, model_v1, model_v2):
        member = Agent(id="wf-member", name="M", model=model_v1, instructions="member")
        member.save(db=db, stage="published")
        Workflow(id="pv-flow", name="PVFlow", steps=[Step(name="s1", agent=member)]).save(db=db, stage="published")
        Workflow(id="pv-flow", name="PVFlow", steps=[Step(name="s1", agent=member)]).save(db=db, stage="draft")
        client = _client(AgentOS(db=db, registry=registry, telemetry=False).get_app(), _BOB)

        start = client.post(
            "/workflows/pv-flow/runs",
            data={"message": "go", "stream": "false", "metadata": '{"agno_component_version": 2}'},
        )
        assert start.status_code == 200, start.text
        body = start.json()

        stored = client.get("/workflows/pv-flow/runs/" + body["run_id"], params={"session_id": body["session_id"]})
        assert stored.status_code == 200, stored.text
        assert COMPONENT_VERSION_METADATA_KEY not in (stored.json().get("metadata") or {})


# ---------------------------------------------------------------------------
# Guard 2: even a stamp that reaches the run is re-gated on continue
# ---------------------------------------------------------------------------


def _force_stamp(monkeypatch, module, version: int):
    """Simulate a run that already carries a stamp the caller may not preview
    (a pre-fix persisted stamp, or a leaked one), bypassing run-start scrubbing."""

    def _planted(kwargs, _version):
        meta = dict(kwargs.get("metadata") or {})
        meta[COMPONENT_VERSION_METADATA_KEY] = version
        kwargs["metadata"] = meta

    monkeypatch.setattr(module, "stamp_component_version", _planted)


class TestForgedStampRefusedOnContinue:
    """A stamp naming a draft the caller may not preview must be refused on
    continue with the SAME 404 body a plain not-found produces."""

    def test_agent_continue_refuses_forbidden_stamp(self, db, registry, model_v1, model_v2, monkeypatch):
        import agno.os.routers.agents.router as agents_router

        agent_id = _save_agent(db, model_v1, model_v2)
        client = _client(AgentOS(db=db, registry=registry, telemetry=False).get_app(), _BOB)

        # Plant a v2 stamp on bob's unpinned run, then restore normal behaviour.
        _force_stamp(monkeypatch, agents_router, 2)
        start = client.post(f"/agents/{agent_id}/runs", data={"message": "hi", "stream": "false"})
        assert start.status_code == 200, start.text
        body = start.json()
        assert (body.get("metadata") or {}).get(COMPONENT_VERSION_METADATA_KEY) == 2
        monkeypatch.undo()

        cont = client.post(
            f"/agents/{agent_id}/runs/{body['run_id']}/continue",
            data={"input": "again", "session_id": body["session_id"], "stream": "false"},
        )
        assert cont.status_code == 404, cont.text
        # Byte-identical to a genuine not-found for a missing agent.
        control = client.post(
            "/agents/does-not-exist/runs/x/continue",
            data={"input": "again", "session_id": body["session_id"], "stream": "false"},
        )
        assert cont.json() == control.json() == {"detail": "Agent not found"}

    def test_team_continue_refuses_forbidden_stamp(self, db, registry, model_v1, model_v2, monkeypatch):
        import agno.os.routers.teams.router as teams_router

        team_id = _save_team(db, model_v1, model_v2)
        client = _client(AgentOS(db=db, registry=registry, telemetry=False).get_app(), _BOB)

        _force_stamp(monkeypatch, teams_router, 2)
        start = client.post(f"/teams/{team_id}/runs", data={"message": "hi", "stream": "false"})
        assert start.status_code == 200, start.text
        body = start.json()
        assert (body.get("metadata") or {}).get(COMPONENT_VERSION_METADATA_KEY) == 2
        monkeypatch.undo()

        cont = client.post(
            f"/teams/{team_id}/runs/{body['run_id']}/continue",
            data={"input": "again", "session_id": body["session_id"], "stream": "false"},
        )
        assert cont.status_code == 404, cont.text
        control = client.post(
            "/teams/does-not-exist/runs/x/continue",
            data={"input": "again", "session_id": body["session_id"], "stream": "false"},
        )
        assert cont.json() == control.json() == {"detail": "Team not found"}

    def test_workflow_continue_refuses_forbidden_stamp(self, db, registry, model_v1, monkeypatch):
        """Workflow continue requires a PAUSED run, so resolve_workflow is
        stubbed to hand back a paused run carrying the forbidden stamp; the
        re-gate must still refuse it before any draft resolution."""
        import agno.os.routers.workflows.router as wf_router

        member = Agent(id="wf-member", name="M", model=model_v1, instructions="member")
        member.save(db=db, stage="published")
        Workflow(id="pv-flow", name="PVFlow", steps=[Step(name="s1", agent=member)]).save(db=db, stage="published")
        Workflow(id="pv-flow", name="PVFlow", steps=[Step(name="s1", agent=member)]).save(db=db, stage="draft")

        class _PausedStub:
            id = "pv-flow"

            async def aget_run_output(self, **kwargs):
                return SimpleNamespace(is_paused=True, status=None, metadata={COMPONENT_VERSION_METADATA_KEY: 2})

        async def _fake_resolve(*a, **k):
            return _PausedStub()

        monkeypatch.setattr(wf_router, "resolve_workflow", _fake_resolve)

        client = _client(AgentOS(db=db, registry=registry, telemetry=False).get_app(), _BOB)
        cont = client.post(
            "/workflows/pv-flow/runs/r-1/continue",
            data={"session_id": "s-1", "stream": "false"},
        )
        assert cont.status_code == 404, cont.text
        assert cont.json() == {"detail": "Workflow not found"}


@pytest.mark.asyncio
class TestWsContinueRefusesForbiddenStamp:
    """The WebSocket continue path re-gates the stamp exactly like REST."""

    async def _run(self, db, registry, model_v1, *, is_admin: bool):
        from agno.os.routers.workflows.router import (
            WebSocketAuthContext,
            handle_workflow_continue_via_websocket,
        )

        # Build the published-vs-draft component in the real db; the re-gate
        # reads it via os.db to decide whether the stamped draft is previewable.
        member = Agent(id="wf-member", name="M", model=model_v1, instructions="member")
        member.save(db=db, stage="published")
        Workflow(id="pv-flow", name="PVFlow", steps=[Step(name="s1", agent=member)]).save(db=db, stage="published")
        Workflow(id="pv-flow", name="PVFlow", steps=[Step(name="s1", agent=member)]).save(db=db, stage="draft")

        class _PausedStub:
            id = "pv-flow"

            async def aget_run_output(self, **kwargs):
                return SimpleNamespace(is_paused=True, status=None, metadata={COMPONENT_VERSION_METADATA_KEY: 2})

        calls = {"n": 0}

        def _fake_get_workflow_by_id(**kwargs):
            calls["n"] += 1
            # First call: the working handle. A version-pinned call means the
            # re-gate PASSED and we are now resolving the stamped draft.
            if kwargs.get("version") is not None:
                return None
            return _PausedStub()

        class FakeWebSocket:
            def __init__(self):
                self.sent = []

            async def send_text(self, text):
                self.sent.append(json.loads(text))

        import agno.os.routers.workflows.router as wf_router

        os_stub = SimpleNamespace(workflows=[], db=db, registry=registry)
        ws = FakeWebSocket()
        with patch.object(wf_router, "get_workflow_by_id", _fake_get_workflow_by_id):
            await handle_workflow_continue_via_websocket(
                ws,
                {"workflow_id": "pv-flow", "run_id": "r-1", "session_id": "s-1", "user_id": "bob"},
                os_stub,
                ws_auth=WebSocketAuthContext(jwt_enabled=True, is_admin=is_admin, user_isolation_enabled=False),
            )
        return ws.sent, calls["n"]

    async def test_non_owner_is_refused_with_not_found(self, db, registry, model_v1):
        sent, resolve_calls = await self._run(db, registry, model_v1, is_admin=False)
        assert sent == [{"event": "error", "error": "Workflow pv-flow not found"}]
        # The re-gate fired before any stamped-draft resolution.
        assert resolve_calls == 1

    async def test_admin_passes_the_regate(self, db, registry, model_v1):
        # A privileged caller clears the re-gate and reaches the stamped-draft
        # resolution (which our stub reports as gone) — a DIFFERENT refusal.
        sent, resolve_calls = await self._run(db, registry, model_v1, is_admin=True)
        assert sent and sent[0]["error"] != "Workflow pv-flow not found"
        assert "no longer available" in sent[0]["error"]
        assert resolve_calls == 2


# ---------------------------------------------------------------------------
# Happy path: a legitimately allowed preview still stamps and continues
# ---------------------------------------------------------------------------


class TestLegitimatePreviewStillWorks:
    def test_owner_scoped_preview_stamps_and_continues_on_the_draft(self, db, registry, model_v1, model_v2):
        """A scoped caller who OWNS the draft may preview it: the stamp lands
        and continue resolves the draft, unbroken by the re-gate."""
        from agno.db.base import ComponentType

        cfg_v1 = Agent(id="owned-agent", name="Owned", model=model_v1, instructions="You are v1").to_dict()
        cfg_v2 = Agent(id="owned-agent", name="Owned", model=model_v2, instructions="You are v2").to_dict()
        db.create_component_with_config(
            component_id="owned-agent",
            component_type=ComponentType.AGENT,
            name="Owned",
            config=cfg_v1,
            stage="published",
            user_id="alice",
        )
        db.upsert_config("owned-agent", config=cfg_v2, stage="draft")

        client = _client(
            AgentOS(db=db, registry=registry, telemetry=False).get_app(),
            dict(user_id="alice", scopes=["agents:run"]),
        )
        start = client.post("/agents/owned-agent/runs", data={"message": "hi", "stream": "false", "version": "2"})
        assert start.status_code == 200, start.text
        body = start.json()
        assert body["content"] == "answer from v2"
        assert (body.get("metadata") or {}).get(COMPONENT_VERSION_METADATA_KEY) == 2

        cont = client.post(
            f"/agents/owned-agent/runs/{body['run_id']}/continue",
            data={"input": "again", "session_id": body["session_id"], "stream": "false"},
        )
        assert cont.status_code == 200, cont.text
        assert cont.json()["content"] == "answer from v2"

    def test_admin_preview_stamps_and_continues_on_the_draft(self, db, registry, model_v1, model_v2):
        agent_id = _save_agent(db, model_v1, model_v2)
        client = _client(AgentOS(db=db, registry=registry, telemetry=False).get_app(), _ADMIN)

        start = client.post(f"/agents/{agent_id}/runs", data={"message": "hi", "stream": "false", "version": "2"})
        assert start.status_code == 200, start.text
        body = start.json()
        assert body["content"] == "answer from v2"
        assert (body.get("metadata") or {}).get(COMPONENT_VERSION_METADATA_KEY) == 2

        cont = client.post(
            f"/agents/{agent_id}/runs/{body['run_id']}/continue",
            data={"input": "again", "session_id": body["session_id"], "stream": "false"},
        )
        assert cont.status_code == 200, cont.text
        assert cont.json()["content"] == "answer from v2"


# ---------------------------------------------------------------------------
# Scheduler executor: a crafted schedule payload cannot smuggle the stamp
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSchedulerExecutorScrubsStamp:
    @staticmethod
    def _schedule(**overrides):
        from agno.db.schemas.scheduler import Schedule

        defaults = {
            "id": "sched-1",
            "name": "nightly",
            "cron_expr": "0 0 * * *",
            "endpoint": "/agents/my-agent/runs",
            "method": "POST",
        }
        defaults.update(overrides)
        return Schedule(**defaults)

    async def test_payload_metadata_stamp_is_not_forwarded(self):
        from agno.scheduler.executor import ScheduleExecutor

        executor = ScheduleExecutor(base_url="http://localhost:8000", internal_service_token="tok")
        schedule = self._schedule(
            user_id="alice",
            payload={
                "message": "hi",
                "metadata": {
                    "agno_component_version": 2,
                    "agno_dispatch_chain": ["team:x"],
                    "agno_dispatch_depth": 0,
                    "trace": "keep",
                },
            },
        )
        with patch.object(executor, "_background_run", new=AsyncMock(return_value={})) as bg:
            await executor._call_endpoint(schedule)

        form_payload = bg.await_args.args[3]
        forwarded_metadata = json.loads(form_payload["metadata"])
        assert COMPONENT_VERSION_METADATA_KEY not in forwarded_metadata
        assert DISPATCH_CHAIN_METADATA_KEY not in forwarded_metadata
        assert DISPATCH_DEPTH_METADATA_KEY not in forwarded_metadata
        assert forwarded_metadata["trace"] == "keep"

    async def test_top_level_payload_stamp_is_not_forwarded(self):
        from agno.scheduler.executor import ScheduleExecutor

        executor = ScheduleExecutor(base_url="http://localhost:8000", internal_service_token="tok")
        schedule = self._schedule(
            user_id="alice",
            payload={"message": "hi", "agno_component_version": 2, "agno_dispatch_chain": ["team:x"]},
        )
        with patch.object(executor, "_background_run", new=AsyncMock(return_value={})) as bg:
            await executor._call_endpoint(schedule)

        form_payload = bg.await_args.args[3]
        assert COMPONENT_VERSION_METADATA_KEY not in form_payload
        assert DISPATCH_CHAIN_METADATA_KEY not in form_payload


# ---------------------------------------------------------------------------
# Session metadata is a caller-writable channel that merges into every run of
# the session and WINS conflicting keys, so the reserved keys are scrubbed at
# the session routes exactly like the run-start routes and the executor.
# ---------------------------------------------------------------------------


class TestForgedSessionMetadataScrubbed:
    def test_create_session_scrubs_reserved_keys(self, db, registry, model_v1, model_v2):
        agent_id = _save_agent(db, model_v1, model_v2)
        client = _client(AgentOS(db=db, registry=registry, telemetry=False).get_app(), _BOB)

        created = client.post(
            "/sessions",
            params={"type": "agent"},
            json={
                "agent_id": agent_id,
                "metadata": {
                    "agno_component_version": 2,
                    "agno_dispatch_chain": [],
                    "agno_dispatch_depth": 0,
                    "trace": "keep",
                },
            },
        )
        assert created.status_code == 201, created.text
        meta = created.json().get("metadata") or {}
        assert meta.get("trace") == "keep"
        assert COMPONENT_VERSION_METADATA_KEY not in meta
        assert DISPATCH_CHAIN_METADATA_KEY not in meta
        assert DISPATCH_DEPTH_METADATA_KEY not in meta

        session_id = created.json()["session_id"]
        stored = client.get(f"/sessions/{session_id}", params={"type": "agent"})
        stored_meta = stored.json().get("metadata") or {}
        assert stored_meta.get("trace") == "keep"
        assert DISPATCH_CHAIN_METADATA_KEY not in stored_meta

    def test_update_session_scrubs_reserved_keys(self, db, registry, model_v1, model_v2):
        agent_id = _save_agent(db, model_v1, model_v2)
        client = _client(AgentOS(db=db, registry=registry, telemetry=False).get_app(), _BOB)

        created = client.post("/sessions", params={"type": "agent"}, json={"agent_id": agent_id})
        assert created.status_code == 201, created.text
        session_id = created.json()["session_id"]

        updated = client.patch(
            f"/sessions/{session_id}",
            params={"type": "agent"},
            json={
                "metadata": {
                    "agno_component_version": 2,
                    "agno_dispatch_chain": [],
                    "agno_dispatch_depth": 0,
                    "trace": "keep",
                }
            },
        )
        assert updated.status_code == 200, updated.text
        meta = updated.json().get("metadata") or {}
        assert meta.get("trace") == "keep"
        assert COMPONENT_VERSION_METADATA_KEY not in meta
        assert DISPATCH_CHAIN_METADATA_KEY not in meta
        assert DISPATCH_DEPTH_METADATA_KEY not in meta
