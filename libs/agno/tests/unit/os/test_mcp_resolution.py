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
    os = AgentOS(agents=[agent], enable_mcp_server=True)

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
        enable_mcp_server=True,
    )

    resolved = await mcp_mod._resolve_run_component(os, "agents", "db-only", user_id=None, session_id=None)
    assert resolved.id == "db-only"


async def test_resolve_run_component_reports_missing_id():
    os = AgentOS(agents=[Agent(id="a1", name="A1")], enable_mcp_server=True)
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
        enable_mcp_server=True,
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
        enable_mcp_server=True,
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
        enable_mcp_server=True,
    )
    _patch_request(monkeypatch, authenticated=True)

    os.get_app()  # populate os.dbs (databases discovery), as at serve time
    async with Client(build_mcp_server(os)) as client:
        result = await client.call_tool("get_agentos_config", {})

    ids = {a["id"] for a in _config_payload(result)["agents"]}
    assert ids == {"a", "b"}
