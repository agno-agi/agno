"""Unit tests for StudioTools toolkit.

Uses a real SqliteDb backed by a pytest tmp_path so the full component +
config persistence path is exercised, not mocked.
"""

import json
from datetime import datetime
from typing import Any, Dict

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.tools.calculator import CalculatorTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.function import Function
from agno.tools.studio import StudioTool, StudioTools
from agno.tools.toolkit import Toolkit

# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="studio-test-db", db_file=str(tmp_path / "studio.db"))


@pytest.fixture
def registry(db):
    return Registry(
        name="Test Registry",
        tools=[DuckDuckGoTools(), CalculatorTools()],
        models=[OpenAIResponses(id="gpt-5.4"), OpenAIResponses(id="gpt-5.5")],
        dbs=[db],
    )


@pytest.fixture
def studio(registry, db):
    return StudioTools(registry=registry, db=db)


@pytest.fixture
def studio_versioned(registry, db):
    return StudioTools(registry=registry, db=db, versions=True)


def _loads(s: str) -> Dict[str, Any]:
    return json.loads(s)


# ----------------------------------------------------------------------
# Backward-compatible alias
# ----------------------------------------------------------------------


class TestStudioToolAlias:
    def test_singular_alias_resolves_to_canonical_class(self):
        assert StudioTool is StudioTools

    def test_alias_constructs_a_working_toolkit(self, registry, db):
        tool = StudioTool(registry=registry, db=db)
        assert isinstance(tool, StudioTools)
        assert "create_agent" in tool.functions


# ----------------------------------------------------------------------
# Initialization
# ----------------------------------------------------------------------


VERSIONING_TOOLS = {
    "list_versions",
    "get_version",
    "publish_component",
    "set_current_version",
    "delete_version",
}


class TestInitialization:
    def test_default_registers_agents_plus_discovery(self, studio):
        expected = {
            # Discovery (always)
            "list_models",
            "list_tools",
            "list_functions",
            "list_dbs",
            "list_agents",
            "list_teams",
            "list_workflows",
            # Agent ops (enabled by default)
            "get_agent",
            "create_agent",
            "edit_agent",
            "delete_agent",
            "run_agent",
        }
        assert expected == set(studio.functions.keys())

    def test_versioning_tools_not_registered_by_default(self, studio):
        assert studio.enable_versions is False
        assert not VERSIONING_TOOLS & set(studio.functions.keys())
        assert not VERSIONING_TOOLS & set(studio.async_functions.keys())

    def test_versions_flag_registers_versioning_tools(self, studio_versioned):
        assert studio_versioned.enable_versions is True
        assert VERSIONING_TOOLS.issubset(set(studio_versioned.functions.keys()))
        assert VERSIONING_TOOLS.issubset(set(studio_versioned.async_functions.keys()))

    def test_instructions_reflect_versioning_flag(self, studio, studio_versioned):
        assert "published immediately" in studio.instructions
        assert "publish_component" not in studio.instructions
        assert "publish_component" in studio_versioned.instructions
        assert "published immediately" not in studio_versioned.instructions

    def test_instructions_include_component_rules_only_when_enabled(self, registry, db):
        default = StudioTools(registry=registry, db=db)
        assert "Team rules" not in default.instructions
        assert "Workflow rules" not in default.instructions

        full = StudioTools(registry=registry, db=db, teams=True, workflows=True)
        assert "Team rules" in full.instructions
        assert "Workflow rules" in full.instructions

    def test_add_instructions_defaults_on_and_respects_override(self, registry, db):
        assert StudioTools(registry=registry, db=db).add_instructions is True
        assert StudioTools(registry=registry, db=db, add_instructions=False).add_instructions is False

    def test_default_does_not_register_team_or_workflow_tools(self, studio):
        names = set(studio.functions.keys())
        for absent in ("create_team", "create_workflow", "edit_team", "edit_workflow"):
            assert absent not in names

    def test_registers_async_run_agent_by_default(self, studio):
        assert "run_agent" in studio.async_functions
        assert set(studio.async_functions.keys()) == set(studio.functions.keys())
        assert "run_team" not in studio.async_functions
        assert "run_workflow" not in studio.async_functions

    def test_registers_all_async_run_tools_when_enabled(self, registry, db):
        tool = StudioTools(registry=registry, db=db, teams=True, workflows=True)
        assert {"run_agent", "run_team", "run_workflow"}.issubset(set(tool.async_functions.keys()))
        assert set(tool.async_functions.keys()) == set(tool.functions.keys())

    def test_db_defaults_to_first_registry_db(self, registry):
        tool = StudioTools(registry=registry)
        assert tool.db is registry.dbs[0]

    def test_explicit_db_overrides_registry(self, registry, db):
        other = SqliteDb(id="other", db_file=":memory:")
        tool = StudioTools(registry=registry, db=other)
        assert tool.db is other


# ----------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------


class TestDiscovery:
    def test_list_models(self, studio):
        result = _loads(studio.list_models())
        ids = {m["id"] for m in result["models"]}
        assert ids == {"gpt-5.4", "gpt-5.5"}

    def test_list_tools(self, studio):
        result = _loads(studio.list_tools())
        names = {t["name"] for t in result["tools"]}
        assert "calculator" in names
        assert "websearch" in names  # DuckDuckGoTools registers as 'websearch'
        for t in result["tools"]:
            if t["name"] == "calculator":
                assert "add" in t["functions"]

    def test_list_functions(self, registry, db):
        def transform_content(value: str) -> str:
            """Transform content for a workflow step."""
            return value.upper()

        registry.functions.append(transform_content)
        studio = StudioTools(registry=registry, db=db)

        result = _loads(studio.list_functions())
        assert result["count"] == 1
        assert result["functions"][0]["name"] == "transform_content"
        assert result["functions"][0]["description"] == "Transform content for a workflow step."
        assert result["functions"][0]["signature"] == "(value: str) -> str"

    def test_list_dbs(self, studio, db):
        result = _loads(studio.list_dbs())
        assert result["count"] == 1
        assert result["dbs"][0]["id"] == db.id

    def test_list_agents_includes_studio_created_db_components(self, registry, db):
        code_agent = Agent(id="code-only", name="Code Only", model=OpenAIResponses(id="gpt-5.4"))
        tool = StudioTools(registry=registry, db=db, agents_list=[code_agent])
        tool.create_agent(name="math-king", instructions="i", model_id="gpt-5.4")

        result = _loads(tool.list_agents())
        ids = {a["id"]: a.get("source") for a in result["agents"]}
        assert ids.get("code-only") == "code"
        assert ids.get("math-king") == "db"

    def test_list_agents_dedupes_when_code_shadows_db(self, registry, db):
        tool = StudioTools(registry=registry, db=db)
        tool.create_agent(name="shared", instructions="i", model_id="gpt-5.4")

        code_agent = Agent(id="shared", name="Shared Code", model=OpenAIResponses(id="gpt-5.4"))
        tool2 = StudioTools(registry=registry, db=db, agents_list=[code_agent])

        result = _loads(tool2.list_agents())
        shared_entries = [a for a in result["agents"] if a["id"] == "shared"]
        assert len(shared_entries) == 1
        assert shared_entries[0]["source"] == "code"

    def test_list_agents_dedupes_code_without_id_by_name(self, registry, db):
        tool = StudioTools(registry=registry, db=db)
        tool.create_agent(name="Shared Name", instructions="i", model_id="gpt-5.4")

        code_agent = Agent(name="Shared Name", model=OpenAIResponses(id="gpt-5.4"))
        tool2 = StudioTools(registry=registry, db=db, agents_list=[code_agent])

        result = _loads(tool2.list_agents())
        shared_entries = [a for a in result["agents"] if a["name"] == "Shared Name"]
        assert len(shared_entries) == 1
        assert shared_entries[0]["source"] == "code"

    def test_list_teams_includes_db_components(self, registry, db):
        tool = StudioTools(registry=registry, db=db, teams=True)
        tool.create_agent(name="a1", instructions="i", model_id="gpt-5.4")
        tool.create_team(name="squad", instructions="i", member_ids=["a1"], model_id="gpt-5.4")

        result = _loads(tool.list_teams())
        ids = {t["id"]: t.get("source") for t in result["teams"]}
        assert ids.get("squad") == "db"

    def test_list_workflows_includes_db_components(self, registry, db):
        tool = StudioTools(registry=registry, db=db, workflows=True)
        tool.create_agent(name="a1", instructions="i", model_id="gpt-5.4")
        tool.create_workflow(name="pipeline", description="d", step_specs=[{"name": "s1", "agent_id": "a1"}])

        result = _loads(tool.list_workflows())
        ids = {w["id"]: w.get("source") for w in result["workflows"]}
        assert ids.get("pipeline") == "db"


# ----------------------------------------------------------------------
# Creation
# ----------------------------------------------------------------------


class TestCreateAgent:
    def test_happy_path_persists_component(self, studio, db):
        out = _loads(
            studio.create_agent(
                name="news-scout",
                instructions="Summarize tech news.",
                model_id="gpt-5.4",
                tool_names=["calculator"],
            )
        )
        assert out["status"] == "created"
        assert out["id"] == "news-scout"
        assert out["tools"] == ["calculator"]
        assert out["db_version"] == 1

        component = db.get_component("news-scout")
        assert component is not None
        assert component["component_type"] == "agent"

    def test_unknown_model_returns_error(self, studio):
        out = _loads(studio.create_agent(name="x", instructions="i", model_id="does-not-exist", tool_names=[]))
        assert "error" in out
        assert "Model not found" in out["error"]

    def test_unknown_tool_returns_error(self, studio):
        out = _loads(studio.create_agent(name="x", instructions="i", model_id="gpt-5.4", tool_names=["nonexistent"]))
        assert "error" in out
        assert "Tools not found" in out["error"]

    def test_create_without_tools(self, studio):
        out = _loads(studio.create_agent(name="plain", instructions="i", model_id="gpt-5.4"))
        assert out["status"] == "created"
        assert out["tools"] == []

    def test_slug_collisions_get_unique_ids(self, studio, db):
        first = _loads(studio.create_agent(name="My Agent", instructions="i", model_id="gpt-5.4"))
        second = _loads(studio.create_agent(name="my-agent", instructions="i", model_id="gpt-5.4"))
        third = _loads(studio.create_agent(name="My--Agent", instructions="i", model_id="gpt-5.4"))

        assert first["id"] == "my-agent"
        assert second["id"] == "my-agent-2"
        assert third["id"] == "my-agent-3"
        assert db.get_component("my-agent")["name"] == "My Agent"
        assert db.get_component("my-agent-2")["name"] == "my-agent"
        assert db.get_component("my-agent-3")["name"] == "My--Agent"

    def test_component_ids_share_global_namespace(self, studio):
        studio.create_agent(name="member", instructions="i", model_id="gpt-5.4")
        team = _loads(studio.create_team(name="Reporter", instructions="i", member_ids=["member"], model_id="gpt-5.4"))
        agent = _loads(studio.create_agent(name="reporter", instructions="i", model_id="gpt-5.4"))

        assert team["id"] == "reporter"
        assert agent["id"] == "reporter-2"

    def test_persist_failure_returns_error(self, studio, db, monkeypatch):
        def fail_upsert_config(*args, **kwargs):
            raise RuntimeError("persist failed")

        monkeypatch.setattr(db, "upsert_config", fail_upsert_config)

        out = _loads(studio.create_agent(name="broken", instructions="i", model_id="gpt-5.4"))
        assert "error" in out
        assert "persist failed" in out["error"]

    @pytest.mark.asyncio
    async def test_async_create_agent_persists_component(self, studio, db):
        out = _loads(await studio.acreate_agent(name="async-agent", instructions="i", model_id="gpt-5.4"))
        assert out["status"] == "created"
        assert db.get_component("async-agent") is not None


class TestToolNameResolution:
    """Multiple MCP servers in one registry must stay independently addressable."""

    @pytest.fixture
    def mcp_registry(self, db):
        pytest.importorskip("mcp")
        from agno.tools.mcp import MCPTools

        docs = MCPTools(url="https://docs.example.com/mcp")
        search = MCPTools(url="https://search.example.com/mcp")
        registry = Registry(
            name="MCP Registry",
            tools=[docs, search],
            models=[OpenAIResponses(id="gpt-5.5")],
            dbs=[db],
        )
        return registry, docs, search

    def test_two_mcp_toolkits_are_independently_listable(self, mcp_registry, db):
        registry, docs, search = mcp_registry
        studio = StudioTool(registry=registry, db=db)

        result = _loads(studio.list_tools())
        names = [t["name"] for t in result["tools"]]
        assert len(names) == len(set(names))
        assert docs.name in names and search.name in names

    def test_two_mcp_toolkits_survive_add_tool_dedup(self, mcp_registry):
        registry, docs, search = mcp_registry
        fresh = Registry()
        fresh.add_tool(docs)
        fresh.add_tool(search)
        assert docs in fresh.tools and search in fresh.tools

    def test_create_agent_selects_the_right_mcp_toolkit_by_name(self, mcp_registry, db):
        registry, docs, search = mcp_registry
        studio = StudioTool(registry=registry, db=db)

        assert studio._find_tool(docs.name) is docs
        assert studio._find_tool(search.name) is search

        # Simulate a connected toolkit: create_agent refuses toolkits with no
        # functions, since they would persist as an empty tool set.
        search.functions["web_search"] = Function(
            name="web_search",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            skip_entrypoint_processing=True,
        )

        out = _loads(
            studio.create_agent(name="web-search-agent", instructions="Search the web.", tool_names=[search.name])
        )
        assert out["status"] == "created"
        assert out["tools"] == [search.name]

    def test_ambiguous_tool_name_errors_instead_of_first_matching(self, db):
        def alpha():
            pass

        def beta():
            pass

        registry = Registry(
            name="Ambiguous Registry",
            tools=[Toolkit(name="dup", tools=[alpha]), Toolkit(name="dup", tools=[beta])],
            models=[OpenAIResponses(id="gpt-5.5")],
            dbs=[db],
        )
        studio = StudioTool(registry=registry, db=db)

        with pytest.raises(ValueError, match="ambiguous"):
            studio._find_tool("dup")

        out = _loads(studio.create_agent(name="x", instructions="i", tool_names=["dup"]))
        assert "error" in out
        assert "ambiguous" in out["error"]


class TestMCPToolkitPersistence:
    """Registry MCP toolkits must persist their functions and survive rehydration.

    Uses stub toolkits with the connected-MCP shape: functions registered on
    the toolkit at connect time, with a fixed schema and
    skip_entrypoint_processing=True.
    """

    @staticmethod
    def _connect(toolkit: Toolkit) -> Function:
        """Simulate MCPTools.connect(): register a fixed-schema function."""

        async def call_proxy(**kwargs) -> str:
            return "docs result"

        func = Function(
            name="search_docs",
            description="Search the docs.",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            entrypoint=call_proxy,
            skip_entrypoint_processing=True,
        )
        toolkit.functions[func.name] = func
        return func

    def _registry(self, db, toolkit: Toolkit) -> Registry:
        return Registry(
            name="MCP Persistence Registry",
            tools=[toolkit],
            models=[OpenAIResponses(id="gpt-5.5")],
            dbs=[db],
        )

    def test_create_agent_refuses_unconnected_toolkit(self, db):
        toolkit = Toolkit(name="agno_docs")  # no functions: never connected
        studio = StudioTool(registry=self._registry(db, toolkit), db=db)

        out = _loads(studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs"]))

        assert "error" in out
        assert "agno_docs" in out["error"]
        assert db.get_component("docs-agent") is None

    def test_edit_agent_refuses_unconnected_toolkit(self, db):
        toolkit = Toolkit(name="agno_docs")
        studio = StudioTool(registry=self._registry(db, toolkit), db=db)
        studio.create_agent(name="docs-agent", instructions="i")

        out = _loads(studio.edit_agent(agent_id="docs-agent", tool_names=["agno_docs"]))

        assert "error" in out
        assert "agno_docs" in out["error"]

    def test_create_agent_persists_connected_toolkit_functions(self, db):
        toolkit = Toolkit(name="agno_docs")
        self._connect(toolkit)
        studio = StudioTool(registry=self._registry(db, toolkit), db=db)

        out = _loads(studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs"]))
        assert out["status"] == "created"

        config = db.get_config("docs-agent")["config"]
        persisted_tools = config.get("tools")
        assert persisted_tools, "connected toolkit functions must be persisted"
        assert [t["name"] for t in persisted_tools] == ["search_docs"]
        assert persisted_tools[0]["parameters"]["required"] == ["query"]

    def test_rehydrated_agent_resolves_mcp_tools_after_late_connect(self, db):
        """Simulate a restart: persist with a connected toolkit, then rehydrate
        against a fresh registry whose toolkit connects only after the
        entrypoint lookup cache was first built."""
        toolkit = Toolkit(name="agno_docs")
        self._connect(toolkit)
        studio = StudioTool(registry=self._registry(db, toolkit), db=db)
        studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs"])

        # Fresh process: new registry, toolkit not yet connected
        fresh_toolkit = Toolkit(name="agno_docs")
        fresh_registry = self._registry(db, fresh_toolkit)

        # Prime the lookup cache before "connect", as startup code paths may
        assert fresh_registry._entrypoint_lookup == {}

        # The AgentOS lifespan connects the toolkit
        func = self._connect(fresh_toolkit)

        config = db.get_config("docs-agent")["config"]
        agent = Agent.from_dict(config, registry=fresh_registry)

        assert agent.tools, "rehydrated agent must keep its MCP tools"
        rehydrated = {t.name: t for t in agent.tools if isinstance(t, Function)}
        assert "search_docs" in rehydrated
        assert rehydrated["search_docs"].entrypoint is func.entrypoint
        assert rehydrated["search_docs"].skip_entrypoint_processing is True


class TestCreateTeam:
    def _make_members(self, studio):
        studio.create_agent(name="a1", instructions="i", model_id="gpt-5.4")
        studio.create_agent(name="a2", instructions="i", model_id="gpt-5.4")

    def test_happy_path(self, studio, db):
        self._make_members(studio)
        out = _loads(
            studio.create_team(
                name="squad",
                instructions="coordinate",
                member_ids=["a1", "a2"],
                model_id="gpt-5.4",
            )
        )
        assert out["status"] == "created"
        assert out["member_ids"] == ["a1", "a2"]
        assert db.get_component("squad")["component_type"] == "team"

    def test_missing_member_returns_error(self, studio):
        self._make_members(studio)
        out = _loads(
            studio.create_team(
                name="squad",
                instructions="i",
                member_ids=["a1", "ghost"],
                model_id="gpt-5.4",
            )
        )
        assert "error" in out
        assert "Members not found" in out["error"]

    def test_empty_members_returns_error(self, studio):
        out = _loads(studio.create_team(name="squad", instructions="i", member_ids=[], model_id="gpt-5.4"))
        assert "error" in out


class TestCreateWorkflow:
    def _make_agents(self, studio):
        studio.create_agent(name="a1", instructions="i", model_id="gpt-5.4")
        studio.create_agent(name="a2", instructions="i", model_id="gpt-5.4")

    def test_happy_path(self, studio, db):
        self._make_agents(studio)
        out = _loads(
            studio.create_workflow(
                name="pipeline",
                description="two steps",
                step_specs=[
                    {"name": "s1", "agent_id": "a1"},
                    {"name": "s2", "agent_id": "a2"},
                ],
            )
        )
        assert out["status"] == "created"
        assert out["steps"] == ["s1", "s2"]
        assert db.get_component("pipeline")["component_type"] == "workflow"

    def test_empty_step_specs_returns_error(self, studio):
        out = _loads(studio.create_workflow(name="x", description="d", step_specs=[]))
        assert "error" in out

    def test_missing_agent_in_step_returns_error(self, studio):
        out = _loads(
            studio.create_workflow(name="x", description="d", step_specs=[{"name": "s1", "agent_id": "ghost"}])
        )
        assert "error" in out
        assert "Agent not found" in out["error"]

    def test_step_without_executor_returns_error(self, studio):
        out = _loads(studio.create_workflow(name="x", description="d", step_specs=[{"name": "s1"}]))
        assert "error" in out


# ----------------------------------------------------------------------
# Edit: draft lifecycle with versions=True, immediate publish without
# ----------------------------------------------------------------------


class TestEditAgent:
    def _create(self, studio):
        return _loads(
            studio.create_agent(name="tutor", instructions="orig", model_id="gpt-5.4", tool_names=["calculator"])
        )

    def test_edit_produces_draft_v2(self, studio_versioned):
        self._create(studio_versioned)
        out = _loads(studio_versioned.edit_agent(agent_id="tutor", instructions="updated"))
        assert out["status"] == "edited"
        assert out["stage"] == "draft"
        assert out["draft_version"] == 2

    def test_second_edit_updates_same_draft_in_place(self, studio_versioned):
        self._create(studio_versioned)
        studio_versioned.edit_agent(agent_id="tutor", instructions="updated once")
        out = _loads(studio_versioned.edit_agent(agent_id="tutor", instructions="updated twice"))
        assert out["draft_version"] == 2  # same draft, no new version

        versions = _loads(studio_versioned.list_versions("tutor"))
        stages = [v["stage"] for v in versions["versions"]]
        assert stages.count("draft") == 1
        assert stages.count("published") == 1

    def test_successive_partial_edits_accumulate_in_draft(self, studio_versioned):
        # A second edit must build on the pending draft, not reset to the
        # published config (which would silently discard the first edit).
        self._create(studio_versioned)
        studio_versioned.edit_agent(agent_id="tutor", instructions="new instructions")
        out = _loads(studio_versioned.edit_agent(agent_id="tutor", description="new description"))

        draft = _loads(studio_versioned.get_version("tutor", version=out["draft_version"]))
        assert draft["config"]["instructions"] == "new instructions"
        assert draft["config"]["description"] == "new description"

    def test_edit_unknown_agent_returns_error(self, studio):
        out = _loads(studio.edit_agent(agent_id="ghost", instructions="x"))
        assert "error" in out

    def test_edit_unknown_model_returns_error(self, studio):
        self._create(studio)
        out = _loads(studio.edit_agent(agent_id="tutor", model_id="does-not-exist"))
        assert "error" in out

    def test_edit_unknown_tool_returns_error(self, studio):
        self._create(studio)
        out = _loads(studio.edit_agent(agent_id="tutor", tool_names=["nonexistent"]))
        assert "error" in out


class TestEditWithoutVersioning:
    """With versions=False (default), edits publish immediately -- no drafts."""

    def test_edit_publishes_immediately(self, studio, db):
        studio.create_agent(name="tutor", instructions="orig", model_id="gpt-5.4")
        out = _loads(studio.edit_agent(agent_id="tutor", instructions="updated"))
        assert out["status"] == "edited"
        assert out["stage"] == "published"
        assert out["version"] == 2

        configs = db.list_configs("tutor")
        assert [c["stage"] for c in configs] == ["published", "published"]

        current = db.get_config("tutor")
        assert current["version"] == 2

    def test_second_edit_creates_new_published_version(self, studio, db):
        studio.create_agent(name="tutor", instructions="orig", model_id="gpt-5.4")
        studio.edit_agent(agent_id="tutor", instructions="edit1")
        out = _loads(studio.edit_agent(agent_id="tutor", instructions="edit2"))
        assert out["version"] == 3
        assert db.get_config("tutor")["version"] == 3


class TestEditTeam:
    def _setup(self, studio):
        studio.create_agent(name="a1", instructions="i", model_id="gpt-5.4")
        studio.create_agent(name="a2", instructions="i", model_id="gpt-5.4")
        studio.create_team(name="squad", instructions="orig", member_ids=["a1"], model_id="gpt-5.4")

    def test_edit_team_members(self, studio_versioned):
        self._setup(studio_versioned)
        out = _loads(studio_versioned.edit_team(team_id="squad", member_ids=["a1", "a2"]))
        assert out["status"] == "edited"
        assert out["stage"] == "draft"

    def test_edit_team_missing_member_returns_error(self, studio):
        self._setup(studio)
        out = _loads(studio.edit_team(team_id="squad", member_ids=["ghost"]))
        assert "error" in out


class TestEditWorkflow:
    def _setup(self, studio):
        studio.create_agent(name="a1", instructions="i", model_id="gpt-5.4")
        studio.create_workflow(name="pipeline", description="orig", step_specs=[{"name": "s1", "agent_id": "a1"}])

    def test_edit_workflow_description(self, studio):
        self._setup(studio)
        out = _loads(studio.edit_workflow(workflow_id="pipeline", description="updated"))
        assert out["status"] == "edited"
        assert out["stage"] == "published"

    def test_edit_workflow_produces_draft(self, studio_versioned):
        self._setup(studio_versioned)
        out = _loads(studio_versioned.edit_workflow(workflow_id="pipeline", description="updated"))
        assert out["status"] == "edited"
        assert out["stage"] == "draft"
        assert out["draft_version"] == 2

    def test_edit_workflow_bad_step(self, studio):
        self._setup(studio)
        out = _loads(studio.edit_workflow(workflow_id="pipeline", step_specs=[{"name": "s1", "agent_id": "ghost"}]))
        assert "error" in out


# ----------------------------------------------------------------------
# Versioning
# ----------------------------------------------------------------------


class TestVersioning:
    def _create_and_edit(self, studio):
        studio.create_agent(name="tutor", instructions="orig", model_id="gpt-5.4", tool_names=["calculator"])
        studio.edit_agent(agent_id="tutor", instructions="updated")

    def test_list_versions_returns_both(self, studio_versioned):
        self._create_and_edit(studio_versioned)
        result = _loads(studio_versioned.list_versions("tutor"))
        assert result["count"] == 2
        stages = sorted(v["stage"] for v in result["versions"])
        assert stages == ["draft", "published"]

    def test_get_version_returns_config(self, studio_versioned):
        self._create_and_edit(studio_versioned)
        result = _loads(studio_versioned.get_version("tutor", version=1))
        assert result.get("version") == 1
        assert result.get("stage") == "published"

    def test_get_current_version_omits_version(self, studio_versioned):
        self._create_and_edit(studio_versioned)
        # The published v1 is current; the pending draft v2 must not be returned.
        result = _loads(studio_versioned.get_version("tutor"))
        assert result.get("version") == 1
        assert result.get("stage") == "published"

    def test_list_versions_marks_current(self, studio_versioned):
        self._create_and_edit(studio_versioned)
        by_version = {v["version"]: v for v in _loads(studio_versioned.list_versions("tutor"))["versions"]}
        assert by_version[1]["is_current"] is True
        assert by_version[2]["is_current"] is False

        studio_versioned.publish_component("tutor")
        by_version = {v["version"]: v for v in _loads(studio_versioned.list_versions("tutor"))["versions"]}
        assert by_version[2]["is_current"] is True
        assert by_version[1]["is_current"] is False

    def test_draft_metadata_not_visible_until_publish(self, studio_versioned, db):
        studio_versioned.create_agent(name="tutor", instructions="i", model_id="gpt-5.4", description="original")
        studio_versioned.edit_agent(agent_id="tutor", description="draft-only")
        assert db.get_component("tutor")["description"] == "original"

        studio_versioned.publish_component("tutor")
        assert db.get_component("tutor")["description"] == "draft-only"

    def test_publish_promotes_draft_to_current(self, studio_versioned):
        self._create_and_edit(studio_versioned)
        out = _loads(studio_versioned.publish_component("tutor"))
        assert out["status"] == "published"
        assert out["version"] == 2

        versions = _loads(studio_versioned.list_versions("tutor"))
        stages = [v["stage"] for v in versions["versions"]]
        assert stages.count("published") == 2
        assert stages.count("draft") == 0

    def test_publish_already_published_version_is_noop(self, studio_versioned):
        self._create_and_edit(studio_versioned)
        studio_versioned.publish_component("tutor")  # draft v2 -> published

        # Re-publishing the same (now published) version must not raise the db's
        # "Cannot update published config" error; it is an idempotent no-op.
        out = _loads(studio_versioned.publish_component("tutor", version=2))
        assert out["status"] == "already_published"
        assert out["version"] == 2

    def test_publish_unknown_version_returns_error(self, studio_versioned):
        studio_versioned.create_agent(name="tutor", instructions="i", model_id="gpt-5.4")
        out = _loads(studio_versioned.publish_component("tutor", version=99))
        assert "error" in out

    def test_publish_without_draft_returns_error(self, studio_versioned):
        studio_versioned.create_agent(name="tutor", instructions="i", model_id="gpt-5.4")
        out = _loads(studio_versioned.publish_component("tutor"))
        assert "error" in out

    def test_set_current_version_rollback(self, studio_versioned):
        self._create_and_edit(studio_versioned)
        studio_versioned.publish_component("tutor")  # v2 published & current
        out = _loads(studio_versioned.set_current_version("tutor", 1))
        assert out["status"] == "set_current"
        assert out["version"] == 1

    def test_delete_draft_version(self, studio_versioned):
        self._create_and_edit(studio_versioned)
        out = _loads(studio_versioned.delete_version("tutor", 2))
        assert out["status"] == "deleted"

        versions = _loads(studio_versioned.list_versions("tutor"))
        assert versions["count"] == 1
        assert versions["versions"][0]["version"] == 1

    def test_delete_published_version_returns_error(self, studio_versioned):
        self._create_and_edit(studio_versioned)
        # v1 is published+current — DB should refuse to delete it
        out = _loads(studio_versioned.delete_version("tutor", 1))
        assert "error" in out


# ----------------------------------------------------------------------
# Delete
# ----------------------------------------------------------------------


class TestDelete:
    def test_delete_agent_removes_from_db(self, studio, db):
        studio.create_agent(name="temp", instructions="i", model_id="gpt-5.4")
        out = _loads(studio.delete_agent("temp"))
        assert out["status"] == "deleted"
        assert db.get_component("temp") is None

    def test_delete_unknown_agent_returns_error(self, studio):
        out = _loads(studio.delete_agent("ghost"))
        assert "error" in out

    def test_delete_agent_only_deletes_db_component_when_live_agent_shadows_id(self, registry, db):
        studio = StudioTools(registry=registry, db=db)
        studio.create_agent(name="temp", instructions="i", model_id="gpt-5.4")

        class ShadowAgent:
            id = "temp"
            name = "temp"

            def delete(self, **kwargs):
                raise AssertionError("delete_agent should not call delete() on live agents")

        tool = StudioTools(registry=registry, db=db, agents_list=[ShadowAgent()])

        out = _loads(tool.delete_agent("temp"))
        assert out["status"] == "deleted"
        assert db.get_component("temp") is None


# ----------------------------------------------------------------------
# Lookup priority
# ----------------------------------------------------------------------


class TestLookup:
    def test_find_agent_finds_just_created_via_db(self, studio):
        studio.create_agent(name="cached", instructions="i", model_id="gpt-5.4")
        agent = studio._find_agent("cached")
        assert agent is not None
        assert agent.id == "cached"

    def test_find_agent_falls_back_to_live_list(self, registry, db):
        live = Agent(id="live-one", name="Live", model=OpenAIResponses(id="gpt-5.4"), db=db)
        tool = StudioTools(registry=registry, db=db, agents_list=[live])
        found = tool._find_agent("live-one")
        assert found is live

    def test_find_agent_falls_back_to_db(self, studio, registry, db):
        studio.create_agent(name="persisted", instructions="i", model_id="gpt-5.4")
        fresh = StudioTools(registry=registry, db=db)
        found = fresh._find_agent("persisted")
        assert found is not None
        assert found.id == "persisted"

    def test_edit_code_defined_agent_is_rejected(self, studio, registry, db):
        # A code-defined (live) agent shadows any DB row at lookup time, so editing
        # it would write an unreachable draft. edit_* must reject it instead of
        # silently returning "edited" (review findings 9-12).
        studio.create_agent(name="shared", instructions="db", model_id="gpt-5.4")
        live = Agent(id="shared", name="Shared", model=OpenAIResponses(id="gpt-5.4"), instructions="live")
        tool = StudioTools(registry=registry, db=db, agents_list=[live], versions=True)

        out = _loads(tool.edit_agent(agent_id="shared", instructions="updated-live"))

        assert "error" in out
        assert "code-defined" in out["error"]
        assert live.instructions == "live"


# ----------------------------------------------------------------------
# Type guards (a component id of one type must not load as another)
# ----------------------------------------------------------------------


class TestTypeGuards:
    def _full(self, registry, db):
        return StudioTools(registry=registry, db=db, teams=True, workflows=True)

    def test_get_agent_rejects_team_id(self, registry, db):
        tool = self._full(registry, db)
        tool.create_agent(name="member", instructions="i", model_id="gpt-5.4")
        tool.create_team(name="squad", instructions="i", member_ids=["member"], model_id="gpt-5.4")

        # 'squad' is a team; loading it as an agent must fail, not return a team-as-agent.
        out = _loads(tool.get_agent("squad"))
        assert "error" in out

    def test_run_agent_rejects_team_id(self, registry, db):
        tool = self._full(registry, db)
        tool.create_agent(name="member", instructions="i", model_id="gpt-5.4")
        tool.create_team(name="squad", instructions="i", member_ids=["member"], model_id="gpt-5.4")

        out = _loads(tool.run_agent("squad", message="hi"))
        assert "error" in out

    def test_get_team_rejects_agent_id(self, registry, db):
        tool = self._full(registry, db)
        tool.create_agent(name="solo", instructions="i", model_id="gpt-5.4")

        out = _loads(tool.get_team("solo"))
        assert "error" in out

    def test_team_member_rejects_workflow_id(self, registry, db):
        tool = self._full(registry, db)
        tool.create_agent(name="a1", instructions="i", model_id="gpt-5.4")
        tool.create_workflow(name="flow", description="d", step_specs=[{"name": "s1", "agent_id": "a1"}])

        # A workflow id is neither an agent nor a team, so it cannot be a member.
        out = _loads(tool.create_team(name="squad", instructions="i", member_ids=["flow"], model_id="gpt-5.4"))
        assert "error" in out
        assert "flow" in out["error"]

    def test_workflow_step_agent_id_rejects_team_id(self, registry, db):
        tool = self._full(registry, db)
        tool.create_agent(name="member", instructions="i", model_id="gpt-5.4")
        tool.create_team(name="squad", instructions="i", member_ids=["member"], model_id="gpt-5.4")

        # 'squad' is a team, so an agent_id step pointing at it must error.
        out = _loads(
            tool.create_workflow(name="flow", description="d", step_specs=[{"name": "s1", "agent_id": "squad"}])
        )
        assert "error" in out

    def test_get_agent_tool_names_match_create(self, registry, db):
        tool = self._full(registry, db)
        created = _loads(
            tool.create_agent(name="calc", instructions="i", model_id="gpt-5.4", tool_names=["calculator"])
        )
        got = _loads(tool.get_agent("calc"))
        # create_* and get_* must report tools the same way (toolkit name, not expanded fns).
        assert created["tools"] == ["calculator"]
        assert got["tools"] == ["calculator"]


# ----------------------------------------------------------------------
# Enable flags
# ----------------------------------------------------------------------


class TestEnableFlags:
    def test_default_enables_agents_only(self, registry, db):
        tool = StudioTools(registry=registry, db=db)
        assert tool.enable_agents is True
        assert tool.enable_teams is False
        assert tool.enable_workflows is False
        names = set(tool.functions.keys())
        assert "create_agent" in names
        assert "create_team" not in names
        assert "create_workflow" not in names

    def test_opt_in_teams(self, registry, db):
        tool = StudioTools(registry=registry, db=db, teams=True)
        assert tool.enable_agents is True  # agents stays on by default
        assert tool.enable_teams is True
        assert tool.enable_workflows is False
        names = set(tool.functions.keys())
        assert "create_team" in names

    def test_agents_disabled_explicitly(self, registry, db):
        tool = StudioTools(registry=registry, db=db, agents=False, teams=True)
        assert tool.enable_agents is False
        assert tool.enable_teams is True
        names = set(tool.functions.keys())
        assert "create_agent" not in names
        assert "create_team" in names

    def test_workflows_only(self, registry, db):
        tool = StudioTools(registry=registry, db=db, agents=False, workflows=True)
        assert tool.enable_agents is False
        assert tool.enable_teams is False
        assert tool.enable_workflows is True
        names = set(tool.functions.keys())
        assert "create_workflow" in names
        assert "create_agent" not in names

    def test_agents_list_auto_enables_teams_and_workflows(self, registry, db):
        tool = StudioTools(registry=registry, db=db, agents_list=[])
        assert tool.enable_agents is True
        assert tool.enable_teams is True
        assert tool.enable_workflows is True

    def test_teams_list_auto_enables_workflows(self, registry, db):
        tool = StudioTools(registry=registry, db=db, teams_list=[])
        assert tool.enable_workflows is True

    def test_explicit_flag_overrides_auto_enable(self, registry, db):
        # User passes agents_list but explicitly disables workflows.
        tool = StudioTools(registry=registry, db=db, agents_list=[], workflows=False)
        assert tool.enable_workflows is False

    def test_discovery_tools_always_registered(self, registry, db):
        # Even with everything disabled, discovery tools stay registered.
        tool = StudioTools(registry=registry, db=db, agents=False)
        names = set(tool.functions.keys())
        assert {
            "list_models",
            "list_tools",
            "list_functions",
            "list_dbs",
            "list_agents",
            "list_teams",
            "list_workflows",
        }.issubset(names)


# ----------------------------------------------------------------------
# Run serialization: non-JSON content must not crash run_* tools
# ----------------------------------------------------------------------


class _StubRunOutput:
    def __init__(self):
        self.content = datetime(2026, 1, 1)


class _StubAgent:
    id = "stub"
    name = "Stub"

    def run(self, message):
        return _StubRunOutput()

    async def arun(self, message):
        return _StubRunOutput()


class TestRunSerialization:
    def test_run_agent_serializes_non_json_content(self, registry, db):
        tool = StudioTools(registry=registry, db=db, agents_list=[_StubAgent()])
        out = _loads(tool.run_agent("stub", "hi"))
        assert "error" not in out
        assert out["content"].startswith("2026-01-01")

    @pytest.mark.asyncio
    async def test_arun_agent_serializes_non_json_content(self, registry, db):
        tool = StudioTools(registry=registry, db=db, agents_list=[_StubAgent()])
        out = _loads(await tool.arun_agent("stub", "hi"))
        assert "error" not in out
        assert out["content"].startswith("2026-01-01")


# ----------------------------------------------------------------------
# Non-cascading persistence: code-defined members should NOT land in DB
# ----------------------------------------------------------------------


class TestNoCascadePersistence:
    def test_create_team_does_not_persist_code_defined_member(self, registry, db):
        greeter = Agent(id="greeter-code", name="Greeter", model=OpenAIResponses(id="gpt-5.4"))
        tool = StudioTools(registry=registry, db=db, agents_list=[greeter])

        tool.create_agent(name="studio-agent", instructions="i", model_id="gpt-5.4")
        tool.create_team(
            name="mixed-team",
            instructions="i",
            member_ids=["greeter-code", "studio-agent"],
            model_id="gpt-5.4",
        )

        # Team row exists
        assert db.get_component("mixed-team") is not None
        # Studio-created agent row exists
        assert db.get_component("studio-agent") is not None
        # Code-defined agent MUST NOT be in DB
        assert db.get_component("greeter-code") is None

    def test_create_workflow_does_not_persist_code_defined_agent(self, registry, db):
        greeter = Agent(id="greeter-code", name="Greeter", model=OpenAIResponses(id="gpt-5.4"))
        tool = StudioTools(registry=registry, db=db, agents_list=[greeter])

        tool.create_workflow(
            name="wf",
            description="d",
            step_specs=[{"name": "s1", "agent_id": "greeter-code"}],
        )
        assert db.get_component("wf") is not None
        assert db.get_component("greeter-code") is None


# ----------------------------------------------------------------------
# Integration: whole lifecycle in order
# ----------------------------------------------------------------------


class TestLifecycle:
    def test_full_lifecycle(self, studio_versioned, db):
        # Create
        out = _loads(
            studio_versioned.create_agent(name="lc", instructions="orig", model_id="gpt-5.4", tool_names=["calculator"])
        )
        assert out["db_version"] == 1

        # Edit twice — should collapse into one draft
        studio_versioned.edit_agent(agent_id="lc", instructions="edit1")
        studio_versioned.edit_agent(agent_id="lc", instructions="edit2")

        versions: list[Dict[str, Any]] = _loads(studio_versioned.list_versions("lc"))["versions"]
        assert len(versions) == 2

        # Publish draft
        pub = _loads(studio_versioned.publish_component("lc"))
        assert pub["version"] == 2

        # Rollback
        rb = _loads(studio_versioned.set_current_version("lc", 1))
        assert rb["status"] == "set_current"

        # Delete
        _loads(studio_versioned.delete_agent("lc"))
        assert db.get_component("lc") is None
