"""Resolution semantics of the v2.7 MCP surface.

These cover what the other MCP test files deliberately stub out (they patch
``_resolve_run_component`` to return the in-memory instance): that the real resolver
isolates each run with ``create_fresh``, resolves components from the DB registry, and
that ``get_agentos_config`` both enumerates DB-registry components and filters the roster
to the caller's per-resource scopes.
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("fastmcp")

from fastmcp import Client  # noqa: E402

import agno.os.mcp as mcp_mod  # noqa: E402
from agno.agent import Agent  # noqa: E402
from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.mcp import build_mcp_server  # noqa: E402


def _config_payload(result):
    structured = result.structured_content or {}
    return structured.get("result", structured)


def _patch_request(monkeypatch, **state):
    import fastmcp.server.dependencies as fastmcp_deps

    request = SimpleNamespace(state=SimpleNamespace(**state), scope={})
    monkeypatch.setattr(fastmcp_deps, "get_http_request", lambda: request)


async def test_resolve_run_component_returns_a_fresh_copy_each_call():
    """create_fresh: every run resolves a distinct deep_copy, never the shared singleton,
    so concurrent MCP runs cannot contaminate each other's state."""
    agent = Agent(id="a1", name="A1")
    os = AgentOS(agents=[agent], mcp_server=True)

    first = await mcp_mod._resolve_run_component(os, "agents", "a1", user_id=None, session_id=None)
    second = await mcp_mod._resolve_run_component(os, "agents", "a1", user_id=None, session_id=None)

    assert first.id == "a1"
    assert first is not agent  # not the shared instance registered on the OS
    assert second is not agent
    assert first is not second  # and distinct per call


async def test_resolve_run_component_reads_the_db_registry(monkeypatch, tmp_path):
    """A component that lives in the DB registry (not the in-memory list) still resolves --
    the resolver forwards db + registry, matching the REST run routes."""
    import agno.agent.agent as agent_mod

    db_agent = Agent(id="db-only", name="DB Only")
    monkeypatch.setattr(agent_mod, "get_agent_by_id", lambda **kwargs: db_agent)

    os = AgentOS(
        agents=[Agent(id="in-memory", name="In Memory")],
        db=SqliteDb(db_file=str(tmp_path / "res.db")),
        mcp_server=True,
    )

    resolved = await mcp_mod._resolve_run_component(os, "agents", "db-only", user_id=None, session_id=None)
    assert resolved.id == "db-only"


async def test_resolve_run_component_reports_missing_id():
    os = AgentOS(agents=[Agent(id="a1", name="A1")], mcp_server=True)
    with pytest.raises(Exception, match="Agent ghost not found"):
        await mcp_mod._resolve_run_component(os, "agents", "ghost", user_id=None, session_id=None)


async def test_config_lists_db_registry_components(monkeypatch, tmp_path):
    """get_agentos_config surfaces DB-registry components alongside in-memory ones, so
    anything created in the DB is discoverable (and therefore runnable) over MCP."""
    import agno.agent.agent as agent_mod
    import agno.team.team as team_mod
    import agno.workflow.workflow as workflow_mod

    monkeypatch.setattr(agent_mod, "get_agents", lambda **kwargs: [Agent(id="db-agent", name="DB Agent")])
    monkeypatch.setattr(team_mod, "get_teams", lambda **kwargs: [])
    monkeypatch.setattr(workflow_mod, "get_workflows", lambda **kwargs: [])

    os = AgentOS(
        agents=[Agent(id="mem-agent", name="Mem Agent")],
        db=SqliteDb(db_file=str(tmp_path / "cfg.db")),
        mcp_server=True,
    )

    os.get_app()  # populate os.dbs (databases discovery), as at serve time
    async with Client(build_mcp_server(os)) as client:
        result = await client.call_tool("get_agentos_config", {})

    ids = {a["id"] for a in _config_payload(result)["agents"]}
    assert ids == {"mem-agent", "db-agent"}


async def test_config_filters_roster_to_accessible_resources(monkeypatch):
    """A caller scoped to one agent must not enumerate the whole deployment via the config
    tool -- the roster is filtered exactly as the REST list routes filter it."""
    os = AgentOS(
        agents=[Agent(id="mine", name="Mine"), Agent(id="theirs", name="Theirs")],
        mcp_server=True,
    )
    _patch_request(
        monkeypatch,
        authenticated=True,
        user_id="sa:bot",
        scopes=["config:read", "agents:mine:read"],
        authorization_enabled=True,
        service_account_name="bot",
    )

    os.get_app()  # populate os.dbs (databases discovery), as at serve time
    async with Client(build_mcp_server(os)) as client:
        result = await client.call_tool("get_agentos_config", {})

    ids = {a["id"] for a in _config_payload(result)["agents"]}
    assert ids == {"mine"}


async def test_config_unfiltered_without_authorization(monkeypatch):
    """With authorization off (open/dev), the config tool returns the full roster -- filtering
    only kicks in when scopes are actually enforced."""
    os = AgentOS(
        agents=[Agent(id="a", name="A"), Agent(id="b", name="B")],
        mcp_server=True,
    )
    _patch_request(monkeypatch, authenticated=True)

    os.get_app()  # populate os.dbs (databases discovery), as at serve time
    async with Client(build_mcp_server(os)) as client:
        result = await client.call_tool("get_agentos_config", {})

    ids = {a["id"] for a in _config_payload(result)["agents"]}
    assert ids == {"a", "b"}


# ==================== Lifecycle resolution: draft-only + stamped versions (B11) ====================


def _draft_only_db(tmp_path, owner=None):
    from agno.db.base import ComponentType

    db = SqliteDb(db_file=str(tmp_path / "draft-mcp.db"))
    db.create_component_with_config(
        component_id="draft-bot",
        component_type=ComponentType.AGENT,
        name="draft-bot",
        config={"name": "draft-bot", "instructions": "hi"},
        stage="draft",
        user_id=owner,
    )
    return db


async def test_resolver_reaches_draft_only_components_with_published_only_false(tmp_path):
    """continue/cancel resolve with published_only=False, like the REST lifecycle
    routes: a run on a draft-only preview component must stay continuable and
    cancellable even though the component has no published version."""
    db = _draft_only_db(tmp_path)
    os = AgentOS(agents=[], db=db, mcp_server=True)

    # Run-start default stays published-only: a draft-only component is not dispatchable.
    with pytest.raises(Exception, match="Agent draft-bot not found"):
        await mcp_mod._resolve_run_component(os, "agents", "draft-bot", user_id=None, session_id=None)

    resolved = await mcp_mod._resolve_run_component(
        os, "agents", "draft-bot", user_id=None, session_id=None, published_only=False
    )
    assert resolved is not None and resolved.id == "draft-bot"


async def test_resolver_pins_an_explicit_version(tmp_path):
    """version= threads through to the shared resolvers, so a stamped run can be
    re-resolved at the exact version recorded at run-start."""
    db = _draft_only_db(tmp_path)
    db.upsert_config("draft-bot", config={"name": "draft-bot", "instructions": "v2 draft"})
    os = AgentOS(agents=[], db=db, mcp_server=True)

    v1 = await mcp_mod._resolve_run_component(
        os, "agents", "draft-bot", user_id=None, session_id=None, version=1, published_only=False
    )
    v2 = await mcp_mod._resolve_run_component(
        os, "agents", "draft-bot", user_id=None, session_id=None, version=2, published_only=False
    )
    assert v1.instructions == "hi"
    assert v2.instructions == "v2 draft"


async def test_pinned_draft_resolution_applies_the_preview_gate(monkeypatch, tmp_path):
    """The draft-preview gate rides the resolver, identically to REST: a
    non-owner identity is denied a pinned draft (same not-found as absence),
    the owner passes. This is the gate the continue tool relies on when it
    re-resolves a stamped version."""
    db = _draft_only_db(tmp_path, owner="owner")
    os = AgentOS(agents=[], db=db, mcp_server=True)

    _patch_request(monkeypatch, user_id="mallory", scopes=["agents:run"])
    with pytest.raises(Exception, match="Agent draft-bot not found"):
        await mcp_mod._resolve_run_component(
            os, "agents", "draft-bot", user_id=None, session_id=None, version=1, published_only=False
        )

    _patch_request(monkeypatch, user_id="owner", scopes=["agents:run"])
    resolved = await mcp_mod._resolve_run_component(
        os, "agents", "draft-bot", user_id=None, session_id=None, version=1, published_only=False
    )
    assert resolved.id == "draft-bot"


async def test_continue_run_resolves_the_stamped_version(monkeypatch):
    """continue_run reads the run's agno_component_version stamp and continues
    on THAT version (published_only=False), like the REST /continue routes -- so
    a draft-only preview run started over REST is continuable over MCP."""
    from fastmcp import Client as MCPClient

    from agno.run.agent import RunOutput

    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: None)

    base_agent = Agent(id="preview-agent", name="Preview Agent")
    stamped_run = RunOutput(run_id="run-1", session_id="s-1", metadata={"agno_component_version": 7})

    async def fake_aget_run_output(run_id=None, session_id=None, user_id=None):
        return stamped_run

    base_agent.aget_run_output = fake_aget_run_output  # type: ignore[method-assign]

    continued_on = []
    stamped_agent = Agent(id="preview-agent", name="Preview Agent v7")

    async def stamped_acontinue_run(*, run_id, session_id, user_id, requirements, stream=False):
        continued_on.append("stamped")
        return RunOutput(run_id=run_id, session_id=session_id, content="resumed@7")

    async def base_acontinue_run(*, run_id, session_id, user_id, requirements, stream=False):
        continued_on.append("base")
        return RunOutput(run_id=run_id, session_id=session_id, content="resumed@base")

    stamped_agent.acontinue_run = stamped_acontinue_run  # type: ignore[method-assign]
    base_agent.acontinue_run = base_acontinue_run  # type: ignore[method-assign]

    os = AgentOS(agents=[base_agent], mcp_server=True)

    calls = []

    async def spy_resolve(os_, kind, cid, **kwargs):
        # Hands back the shared instances (the production deep_copy would drop
        # the method stubs); what is under test is the tool's WIRING - which
        # arguments each resolution gets and which instance the continuation
        # then runs on.
        calls.append(dict(kwargs))
        if kwargs.get("version") is not None:
            # The pinned re-resolution: hand back the version-7 instance.
            return stamped_agent
        return base_agent

    monkeypatch.setattr(mcp_mod, "_resolve_run_component", spy_resolve)

    async with MCPClient(build_mcp_server(os)) as client:
        result = await client.call_tool(
            "continue_run", {"run_id": "run-1", "session_id": "s-1", "agent_id": "preview-agent"}
        )

    # Base resolution matches the REST continue route (published_only=False),
    # then the stamp re-resolves at version 7, and the continuation runs THERE.
    assert calls[0].get("published_only") is False and calls[0].get("version") is None
    assert calls[1].get("version") == 7 and calls[1].get("published_only") is False
    assert continued_on == ["stamped"]
    structured = result.structured_content or {}
    payload = structured.get("result", structured)
    assert payload.get("run_id") == "run-1" and payload.get("session_id") == "s-1"


async def test_continue_run_without_a_stamp_keeps_base_resolution(monkeypatch):
    """No stamp (legacy/unpinned runs) keeps today's resolution -- exactly one
    resolve, no version pin."""
    from fastmcp import Client as MCPClient

    from agno.run.agent import RunOutput

    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: None)

    agent = Agent(id="plain-agent", name="Plain Agent")

    async def fake_aget_run_output(run_id=None, session_id=None, user_id=None):
        return RunOutput(run_id="run-1", session_id="s-1")  # no metadata stamp

    async def fake_acontinue_run(*, run_id, session_id, user_id, requirements, stream=False):
        return RunOutput(run_id=run_id, session_id=session_id, content="resumed")

    agent.aget_run_output = fake_aget_run_output  # type: ignore[method-assign]
    agent.acontinue_run = fake_acontinue_run  # type: ignore[method-assign]
    os = AgentOS(agents=[agent], mcp_server=True)

    calls = []

    async def spy_resolve(os_, kind, cid, **kwargs):
        calls.append(dict(kwargs))
        return agent  # shared instance: the deep_copy would drop the stubs

    monkeypatch.setattr(mcp_mod, "_resolve_run_component", spy_resolve)

    async with MCPClient(build_mcp_server(os)) as client:
        await client.call_tool("continue_run", {"run_id": "run-1", "session_id": "s-1", "agent_id": "plain-agent"})

    assert len(calls) == 1
    assert calls[0].get("published_only") is False


async def test_cancel_run_reaches_draft_only_components(tmp_path, monkeypatch):
    """cancel_run resolves with strict=False AND published_only=False (the REST
    cancel route's parameters): a draft-only preview run must stay cancellable."""
    from fastmcp import Client as MCPClient

    db = _draft_only_db(tmp_path)
    os = AgentOS(agents=[], db=db, mcp_server=True)

    cancelled = []

    async def fake_cancel(component, run_id):
        cancelled.append((component.id, run_id))

    monkeypatch.setattr(mcp_mod.run_service, "cancel_component_run", fake_cancel)

    async with MCPClient(build_mcp_server(os)) as client:
        result = await client.call_tool("cancel_run", {"run_id": "run-9", "agent_id": "draft-bot"})

    assert cancelled == [("draft-bot", "run-9")]
    assert "cancellation requested" in str(result.content)
