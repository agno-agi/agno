"""Unit tests for StudioTools toolkit.

Uses a real SqliteDb backed by a pytest tmp_path so the full component +
config persistence path is exercised, not mocked.
"""

import json
import time
from datetime import datetime
from importlib.util import find_spec
from typing import Any, Dict

import pytest

from agno.agent import Agent
from agno.agent._tools import parse_tools
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.session import AgentSession
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


@pytest.fixture
def studio_schedules(registry, db):
    return StudioTools(registry=registry, db=db, schedules=True)


def _loads(s: str) -> Dict[str, Any]:
    return json.loads(s)


def _tool(toolkit: StudioTools, name: str):
    """The registered entrypoint for a tool -- what an agent actually calls."""
    return toolkit.functions[name].entrypoint


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

SCHEDULE_TOOLS = {
    "create_schedule",
    "list_schedules",
    "get_schedule",
    "get_schedule_runs",
    "trigger_schedule",
    "enable_schedule",
    "disable_schedule",
    "delete_schedule",
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

    def test_schedule_tools_not_registered_by_default(self, studio):
        assert studio.enable_schedules is False
        assert not SCHEDULE_TOOLS & set(studio.functions.keys())
        assert not SCHEDULE_TOOLS & set(studio.async_functions.keys())
        assert "Schedules:" not in studio.instructions

    def test_schedules_flag_registers_schedule_tools(self, studio_schedules):
        assert studio_schedules.enable_schedules is True
        assert SCHEDULE_TOOLS.issubset(set(studio_schedules.functions.keys()))
        assert SCHEDULE_TOOLS.issubset(set(studio_schedules.async_functions.keys()))
        assert "Schedules:" in studio_schedules.instructions

    def test_management_tools_are_shared_with_scheduler_toolkit(self, studio_schedules):
        from agno.tools.scheduler import SchedulerTools

        for tool_name in SCHEDULE_TOOLS - {"create_schedule"}:
            sync_owner = studio_schedules.functions[tool_name].entrypoint.__self__
            async_owner = studio_schedules.async_functions[tool_name].entrypoint.__self__
            assert isinstance(sync_owner, SchedulerTools), tool_name
            assert isinstance(async_owner, SchedulerTools), tool_name
        assert studio_schedules.functions["create_schedule"].entrypoint.__self__ is studio_schedules

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

    def test_list_agents_keeps_db_component_whose_id_equals_a_code_name(self, registry, db):
        # A code agent id="code-1" is *named* "support"; a distinct DB agent has id "support".
        # get_/run_/edit_ all resolve "support" to the DB component (exact id wins), so the
        # listing must not hide it behind the code agent's name.
        seed = StudioTools(registry=registry, db=db)
        seed.create_agent(name="support", instructions="i", model_id="gpt-5.4")  # DB id "support"

        code_agent = Agent(id="code-1", name="support", model=OpenAIResponses(id="gpt-5.4"))
        studio = StudioTools(registry=registry, db=db, agents_list=[code_agent])
        out = _loads(studio.list_agents())
        ids = {a["id"] for a in out["agents"]}
        assert "code-1" in ids
        assert "support" in ids  # DB component stays discoverable, not shadowed by the code name

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

    def test_history_on_by_default(self, studio, db):
        out = _loads(studio.create_agent(name="mem", instructions="i", model_id="gpt-5.4"))
        assert out["add_history_to_context"] is True

        config = db.get_config("mem")["config"]
        assert config["add_history_to_context"] is True
        assert config["num_history_runs"] == 3  # Agent.__init__ normalization

    def test_stateless_opt_out_omits_history_from_config(self, studio, db):
        out = _loads(
            studio.create_agent(name="stateless", instructions="i", model_id="gpt-5.4", add_history_to_context=False)
        )
        assert out["add_history_to_context"] is False

        # to_dict omits falsy add_history_to_context, so the key is absent.
        config = db.get_config("stateless")["config"]
        assert "add_history_to_context" not in config

    def test_explicit_num_history_runs_round_trips(self, studio, db):
        studio.create_agent(name="deep", instructions="i", model_id="gpt-5.4", num_history_runs=10)

        config = db.get_config("deep")["config"]
        assert config["num_history_runs"] == 10

        agent = studio._load_agent_from_db("deep")
        assert agent.add_history_to_context is True
        assert agent.num_history_runs == 10

    def test_toolkit_default_num_history_runs_applies(self, registry, db):
        tool = StudioTools(registry=registry, db=db, default_num_history_runs=5)
        tool.create_agent(name="five", instructions="i", model_id="gpt-5.4")

        config = db.get_config("five")["config"]
        assert config["num_history_runs"] == 5

    @pytest.mark.asyncio
    async def test_async_create_agent_stateless(self, studio, db):
        out = _loads(
            await studio.acreate_agent(
                name="async-stateless", instructions="i", model_id="gpt-5.4", add_history_to_context=False
            )
        )
        assert out["add_history_to_context"] is False
        config = db.get_config("async-stateless")["config"]
        assert "add_history_to_context" not in config

    def test_datetime_on_by_default(self, studio, db):
        out = _loads(studio.create_agent(name="dated", instructions="i", model_id="gpt-5.4"))
        assert out["add_datetime_to_context"] is True

        config = db.get_config("dated")["config"]
        assert config["add_datetime_to_context"] is True

    def test_datetime_opt_out_omits_key_from_config(self, studio, db):
        out = _loads(
            studio.create_agent(name="undated", instructions="i", model_id="gpt-5.4", add_datetime_to_context=False)
        )
        assert out["add_datetime_to_context"] is False

        # to_dict omits falsy add_datetime_to_context, so the key is absent.
        config = db.get_config("undated")["config"]
        assert "add_datetime_to_context" not in config

    @pytest.mark.asyncio
    async def test_async_create_agent_datetime_opt_out(self, studio, db):
        out = _loads(
            await studio.acreate_agent(
                name="async-undated", instructions="i", model_id="gpt-5.4", add_datetime_to_context=False
            )
        )
        assert out["add_datetime_to_context"] is False
        config = db.get_config("async-undated")["config"]
        assert "add_datetime_to_context" not in config


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

    def test_find_tool_by_function_name_stamps_owning_toolkit(self, db):
        """Selecting a toolkit member by its function name hands back a bare
        Function; it must carry its toolkit attribution so a component saved
        with it keeps the "toolkit" key (see Registry.rehydrate_function)."""

        def read_file(path: str) -> str:
            """Read a file."""
            return path

        registry = Registry(
            name="Stamp Registry",
            tools=[Toolkit(name="agent_files", tools=[read_file])],
            models=[OpenAIResponses(id="gpt-5.5")],
            dbs=[db],
        )
        studio = StudioTool(registry=registry, db=db)

        member = studio._find_tool("read_file")

        assert isinstance(member, Function)
        assert member.owning_toolkit == "agent_files"


class TestToolkitInstructionPersistence:
    def test_source_toolkit_survives_every_copy_path(self):
        """The live Toolkit must survive both copy entry points, including
        pydantic's own model_copy(deep=True), which calls __deepcopy__() with
        no memo."""
        from copy import deepcopy

        from pydantic import BaseModel

        def read_file(path: str) -> str:
            return path

        toolkit = Toolkit(name="agent_files", tools=[read_file])
        function = toolkit.get_functions()["read_file"].model_copy()
        function.source_toolkit = toolkit

        assert deepcopy(function).source_toolkit is toolkit
        assert function.model_copy(deep=True).source_toolkit is toolkit
        assert BaseModel.model_copy(function, deep=True).source_toolkit is toolkit

        # The pin must not overwrite a stand-in the in-progress copy already
        # made: one original may not end up with two stand-ins.
        copied_toolkit, copied_function = deepcopy([toolkit, function])
        assert copied_function.source_toolkit is copied_toolkit

    def test_db_loaded_agent_includes_live_toolkit_guidance_once(self, db):
        creation_guidance = "CREATION_TOOLKIT_GUIDANCE"
        live_guidance = "LIVE_TOOLKIT_GUIDANCE"
        first_guidance = "FIRST_FUNCTION_GUIDANCE"
        second_guidance = "SECOND_FUNCTION_GUIDANCE"

        def first_tool() -> str:
            return "first"

        def second_tool() -> str:
            return "second"

        toolkit = Toolkit(
            name="guided_tools",
            tools=[first_tool, second_tool],
            instructions=creation_guidance,
            add_instructions=True,
        )
        toolkit.functions["first_tool"].instructions = first_guidance
        toolkit.functions["second_tool"].instructions = second_guidance
        registry = Registry(
            tools=[toolkit],
            models=[OpenAIResponses(id="gpt-5.5")],
            dbs=[db],
        )
        studio = StudioTools(registry=registry, db=db)

        result = _loads(
            studio.create_agent(
                name="guided-agent",
                instructions="Base agent guidance.",
                model_id="gpt-5.5",
                tool_names=[toolkit.name],
            )
        )
        assert result["status"] == "created"

        persisted_tools = db.get_config("guided-agent")["config"]["tools"]
        assert len(persisted_tools) == 2
        assert all(tool["toolkit"] == toolkit.name for tool in persisted_tools)
        assert all("instructions" not in tool for tool in persisted_tools)
        assert all("add_instructions" not in tool for tool in persisted_tools)

        # A registry edit after persistence must be visible on the next load.
        toolkit.instructions = live_guidance

        loaded = studio._load_agent_from_db("guided-agent")
        assert loaded is not None
        # AgentOS request resolution deep-copies DB-loaded components.
        loaded = loaded.deep_copy()
        assert loaded.tools is not None
        assert loaded.model is not None
        assert all(isinstance(tool, Function) for tool in loaded.tools)
        assert all(tool.source_toolkit is toolkit for tool in loaded.tools if isinstance(tool, Function))

        model_tools = parse_tools(agent=loaded, tools=loaded.tools, model=loaded.model)
        assert loaded._tool_instructions == [first_guidance, second_guidance, live_guidance]
        message = loaded.get_system_message(
            session=AgentSession(session_id="test-session", agent_id=loaded.id),
            tools=model_tools,
        )

        assert message is not None
        assert isinstance(message.content, str)
        assert creation_guidance not in message.content
        assert message.content.count(live_guidance) == 1


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

    def test_history_and_datetime_on_by_default(self, studio, db):
        self._make_members(studio)
        out = _loads(studio.create_team(name="squad", instructions="i", member_ids=["a1"], model_id="gpt-5.4"))
        assert out["add_history_to_context"] is True
        assert out["add_datetime_to_context"] is True

        config = db.get_config("squad")["config"]
        assert config["add_history_to_context"] is True
        assert config["num_history_runs"] == 3  # Team.__init__ normalization
        assert config["add_datetime_to_context"] is True

    def test_stateless_opt_out_omits_history_from_config(self, studio, db):
        self._make_members(studio)
        out = _loads(
            studio.create_team(
                name="squad",
                instructions="i",
                member_ids=["a1"],
                model_id="gpt-5.4",
                add_history_to_context=False,
                add_datetime_to_context=False,
            )
        )
        assert out["add_history_to_context"] is False
        assert out["add_datetime_to_context"] is False

        # to_dict omits falsy flags, so the keys are absent.
        config = db.get_config("squad")["config"]
        assert "add_history_to_context" not in config
        assert "add_datetime_to_context" not in config

    def test_explicit_num_history_runs_round_trips(self, studio, db):
        self._make_members(studio)
        studio.create_team(name="squad", instructions="i", member_ids=["a1"], model_id="gpt-5.4", num_history_runs=10)

        config = db.get_config("squad")["config"]
        assert config["num_history_runs"] == 10

        team = studio._load_team_from_db("squad")
        assert team.add_history_to_context is True
        assert team.num_history_runs == 10

    def test_toolkit_default_num_history_runs_applies(self, registry, db):
        tool = StudioTools(registry=registry, db=db, default_num_history_runs=5)
        tool.create_agent(name="a1", instructions="i", model_id="gpt-5.4")
        tool.create_team(name="five", instructions="i", member_ids=["a1"], model_id="gpt-5.4")

        config = db.get_config("five")["config"]
        assert config["num_history_runs"] == 5

    @pytest.mark.asyncio
    async def test_async_create_team_stateless(self, studio, db):
        self._make_members(studio)
        out = _loads(
            await studio.acreate_team(
                name="async-squad",
                instructions="i",
                member_ids=["a1"],
                model_id="gpt-5.4",
                add_history_to_context=False,
            )
        )
        assert out["add_history_to_context"] is False
        config = db.get_config("async-squad")["config"]
        assert "add_history_to_context" not in config


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

    def test_edit_turns_history_off_and_keeps_other_fields(self, studio):
        self._create(studio)
        out = _loads(studio.edit_agent(agent_id="tutor", add_history_to_context=False))
        assert out["status"] == "edited"

        got = _loads(studio.get_agent("tutor"))
        assert got["add_history_to_context"] is False
        assert got["instructions"] == "orig"
        assert got["tools"] == ["calculator"]

    def test_edit_num_history_runs_only_keeps_history_on(self, studio):
        self._create(studio)
        _loads(studio.edit_agent(agent_id="tutor", num_history_runs=7))

        got = _loads(studio.get_agent("tutor"))
        assert got["add_history_to_context"] is True  # untouched from create
        assert got["num_history_runs"] == 7

    def test_history_edit_accumulates_in_same_draft(self, studio_versioned):
        self._create(studio_versioned)
        studio_versioned.edit_agent(agent_id="tutor", add_history_to_context=False)
        out = _loads(studio_versioned.edit_agent(agent_id="tutor", description="new description"))

        draft = _loads(studio_versioned.get_version("tutor", version=out["draft_version"]))
        assert "add_history_to_context" not in draft["config"]  # history off survives edit 2
        assert draft["config"]["description"] == "new description"

    def test_get_agent_reports_history_settings(self, studio):
        self._create(studio)
        got = _loads(studio.get_agent("tutor"))
        assert got["add_history_to_context"] is True
        assert got["num_history_runs"] == 3

    def test_edit_turns_datetime_off_and_keeps_other_fields(self, studio):
        self._create(studio)
        out = _loads(studio.edit_agent(agent_id="tutor", add_datetime_to_context=False))
        assert out["status"] == "edited"

        got = _loads(studio.get_agent("tutor"))
        assert got["add_datetime_to_context"] is False
        assert got["instructions"] == "orig"
        assert got["tools"] == ["calculator"]

    def test_get_agent_reports_datetime_setting(self, studio):
        self._create(studio)
        got = _loads(studio.get_agent("tutor"))
        assert got["add_datetime_to_context"] is True

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

    def test_edit_turns_history_off_and_keeps_other_fields(self, studio):
        self._setup(studio)
        out = _loads(studio.edit_team(team_id="squad", add_history_to_context=False))
        assert out["status"] == "edited"

        got = _loads(studio.get_team("squad"))
        assert got["add_history_to_context"] is False
        assert got["instructions"] == "orig"
        assert got["member_ids"] == ["a1"]

    def test_edit_num_history_runs_only_keeps_history_on(self, studio):
        self._setup(studio)
        _loads(studio.edit_team(team_id="squad", num_history_runs=7))

        got = _loads(studio.get_team("squad"))
        assert got["add_history_to_context"] is True  # untouched from create
        assert got["num_history_runs"] == 7

    def test_get_team_reports_history_and_datetime_settings(self, studio):
        self._setup(studio)
        got = _loads(studio.get_team("squad"))
        assert got["add_history_to_context"] is True
        assert got["num_history_runs"] == 3
        assert got["add_datetime_to_context"] is True

    @pytest.mark.asyncio
    async def test_async_edit_team_datetime_off(self, studio):
        self._setup(studio)
        out = _loads(await studio.aedit_team(team_id="squad", add_datetime_to_context=False))
        assert out["status"] == "edited"

        got = _loads(studio.get_team("squad"))
        assert got["add_datetime_to_context"] is False


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
# Schedules: component-aware schedule tools with schedules=True
# ----------------------------------------------------------------------


@pytest.mark.skipif(
    find_spec("croniter") is None or find_spec("pytz") is None,
    reason="scheduler extras not installed (pip install agno[scheduler])",
)
class TestSchedules:
    def _create_target_agent(self, studio, name="digest"):
        return _loads(studio.create_agent(name=name, instructions="i", model_id="gpt-5.4"))

    def _create_schedule(self, studio, **overrides):
        params = {
            "name": "daily-digest",
            "cron": "0 9 * * *",
            "target_type": "agent",
            "target_id": "digest",
            "message": "Send the daily digest.",
        }
        params.update(overrides)
        return _loads(studio.create_schedule(**params))

    def test_create_schedule_for_created_agent_persists_endpoint_and_payload(self, studio_schedules):
        self._create_target_agent(studio_schedules)
        out = self._create_schedule(studio_schedules)

        assert out["status"] == "created"
        assert out["target_type"] == "agent"
        assert out["target_id"] == "digest"
        assert out["endpoint"] == "/agents/digest/runs"
        assert out["enabled"] is True

        schedule = studio_schedules._get_schedule_manager().get(out["id"])
        assert schedule is not None
        assert schedule.endpoint == "/agents/digest/runs"
        assert schedule.method == "POST"
        assert schedule.payload == {"message": "Send the daily digest."}

    def test_name_based_target_resolves_to_real_component_id(self, registry, db):
        live = Agent(id="live-agent", name="Live Agent", model=OpenAIResponses(id="gpt-5.4"))
        tool = StudioTools(registry=registry, db=db, agents_list=[live], schedules=True)

        out = self._create_schedule(tool, target_id="Live Agent")
        assert out["status"] == "created"
        assert out["target_id"] == "live-agent"
        assert out["endpoint"] == "/agents/live-agent/runs"

    def test_unknown_target_returns_error(self, studio_schedules):
        out = self._create_schedule(studio_schedules, target_id="ghost")
        assert "error" in out
        assert "Agent not found: ghost" in out["error"]

    def test_bad_target_type_returns_error(self, studio_schedules):
        self._create_target_agent(studio_schedules)
        out = self._create_schedule(studio_schedules, target_type="cron-job")
        assert "error" in out
        assert "Invalid target_type" in out["error"]

    def test_invalid_cron_returns_error(self, studio_schedules):
        self._create_target_agent(studio_schedules)
        out = self._create_schedule(studio_schedules, cron="not-a-cron")
        assert "error" in out
        assert "Invalid cron expression" in out["error"]

    def test_invalid_timezone_returns_error(self, studio_schedules):
        self._create_target_agent(studio_schedules)
        out = self._create_schedule(studio_schedules, timezone="Mars/Olympus")
        assert "error" in out
        assert "Invalid timezone" in out["error"]

    def test_empty_message_returns_error(self, studio_schedules):
        self._create_target_agent(studio_schedules)
        out = self._create_schedule(studio_schedules, message="   ")
        assert "error" in out
        assert "message" in out["error"]

    def test_same_name_create_updates_in_place(self, studio_schedules):
        self._create_target_agent(studio_schedules)
        first = self._create_schedule(studio_schedules)
        second = self._create_schedule(studio_schedules, cron="30 18 * * *")

        assert second["id"] == first["id"]
        assert second["cron"] == "30 18 * * *"

        listed = _loads(_tool(studio_schedules, "list_schedules")())
        assert listed["count"] == 1
        assert listed["schedules"][0]["cron"] == "30 18 * * *"

    def test_get_schedule_reports_endpoint_and_payload(self, studio_schedules):
        self._create_target_agent(studio_schedules)
        schedule_id = self._create_schedule(studio_schedules)["id"]

        out = _loads(_tool(studio_schedules, "get_schedule")(schedule_id))
        assert out["endpoint"] == "/agents/digest/runs"
        assert out["payload"] == {"message": "Send the daily digest."}

    def test_enable_disable_delete_roundtrip(self, studio_schedules):
        self._create_target_agent(studio_schedules)
        schedule_id = self._create_schedule(studio_schedules)["id"]

        disabled = _loads(_tool(studio_schedules, "disable_schedule")(schedule_id))
        assert disabled["status"] == "disabled"
        assert disabled["enabled"] is False
        assert _loads(_tool(studio_schedules, "list_schedules")(enabled_only=True))["count"] == 0

        enabled = _loads(_tool(studio_schedules, "enable_schedule")(schedule_id))
        assert enabled["status"] == "enabled"
        assert enabled["enabled"] is True
        assert _loads(_tool(studio_schedules, "list_schedules")(enabled_only=True))["count"] == 1

        deleted = _loads(_tool(studio_schedules, "delete_schedule")(schedule_id))
        assert deleted["status"] == "deleted"
        assert _loads(_tool(studio_schedules, "list_schedules")())["count"] == 0

    def test_delete_unknown_schedule_returns_error(self, studio_schedules):
        out = _loads(_tool(studio_schedules, "delete_schedule")("ghost"))
        assert "error" in out

    def test_get_schedule_runs_empty_for_new_schedule(self, studio_schedules):
        self._create_target_agent(studio_schedules)
        schedule_id = self._create_schedule(studio_schedules)["id"]
        out = _loads(_tool(studio_schedules, "get_schedule_runs")(schedule_id))
        assert out["runs"] == []
        assert out["count"] == 0

    def test_trigger_sets_next_run_at_to_now(self, studio_schedules):
        self._create_target_agent(studio_schedules)
        schedule_id = self._create_schedule(studio_schedules)["id"]

        out = _loads(_tool(studio_schedules, "trigger_schedule")(schedule_id))
        assert out["status"] == "triggered"
        assert out["id"] == schedule_id
        assert "poll interval" in out["note"]

        # The poller claims schedules with next_run_at <= now, so the trigger
        # must have moved next_run_at into the claimable window.
        schedule = studio_schedules._get_schedule_manager().get(schedule_id)
        assert schedule.next_run_at <= int(time.time())

    def test_trigger_disabled_schedule_returns_error(self, studio_schedules):
        self._create_target_agent(studio_schedules)
        schedule_id = self._create_schedule(studio_schedules)["id"]
        _tool(studio_schedules, "disable_schedule")(schedule_id)

        out = _loads(_tool(studio_schedules, "trigger_schedule")(schedule_id))
        assert "error" in out
        assert "disabled" in out["error"]

    def test_trigger_unknown_schedule_returns_error(self, studio_schedules):
        out = _loads(_tool(studio_schedules, "trigger_schedule")("ghost"))
        assert "error" in out
        assert "Schedule not found" in out["error"]

    @pytest.mark.asyncio
    async def test_async_create_schedule(self, studio_schedules):
        self._create_target_agent(studio_schedules)
        out = _loads(
            await studio_schedules.acreate_schedule(
                name="async-digest",
                cron="0 9 * * *",
                target_type="agent",
                target_id="digest",
                message="Send it.",
            )
        )
        assert out["status"] == "created"
        assert out["endpoint"] == "/agents/digest/runs"


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

        out = _loads(_tool(tool, "run_agent")("squad", message="hi"))
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

    def run(self, message, stream=None, user_id=None, session_id=None):
        return _StubRunOutput()

    async def arun(self, message, stream=None, user_id=None, session_id=None):
        return _StubRunOutput()

    def deep_copy(self):
        # A distinct instance that shares state, the shape _fresh_copy accepts.
        clone = object.__new__(type(self))
        clone.__dict__ = self.__dict__
        return clone


class TestRunSerialization:
    def test_run_agent_serializes_non_json_content(self, registry, db):
        tool = StudioTools(registry=registry, db=db, agents_list=[_StubAgent()])
        out = _loads(_tool(tool, "run_agent")("stub", "hi"))
        assert "error" not in out
        assert out["content"].startswith("2026-01-01")

    @pytest.mark.asyncio
    async def test_arun_agent_serializes_non_json_content(self, registry, db):
        tool = StudioTools(registry=registry, db=db, agents_list=[_StubAgent()])
        out = _loads(await tool.async_functions["run_agent"].entrypoint("stub", "hi"))
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


def test_studio_loads_component_with_broken_refs_for_repair(tmp_path):
    """StudioTools read/edit paths load leniently: a component whose registry
    references are broken must still load so an edit can repair it."""
    from agno.db.sqlite import SqliteDb
    from agno.models.openai import OpenAIChat
    from agno.registry import Registry
    from agno.tools.studio import StudioTools

    db = SqliteDb(db_file=str(tmp_path / "studio_repair.db"))

    def search(query: str) -> str:
        """Search for a query."""
        return f"results for {query}"

    agent = Agent(id="repair-agent", name="Repair Agent", model=OpenAIChat(id="gpt-4o-mini"), tools=[search])
    agent.save(db=db)

    # Registry lacks the tool the saved agent references
    studio = StudioTools(registry=Registry(), db=db)
    loaded = studio._load_agent_from_db("repair-agent")

    assert loaded is not None
    assert loaded.id == "repair-agent"


class TestEditPreservation:
    """Edits round-trip through leniently loaded objects; the persisted config
    must not lose what the load could not resolve, nor its member pins."""

    def test_description_edit_preserves_unresolved_output_schema(self, tmp_path):
        from pydantic import BaseModel

        from agno.db.sqlite import SqliteDb
        from agno.models.openai import OpenAIChat
        from agno.registry import Registry
        from agno.tools.studio import StudioTools

        class Report(BaseModel):
            text: str

        db = SqliteDb(db_file=str(tmp_path / "preserve.db"))
        Agent(id="schema-agent", name="S", model=OpenAIChat(id="gpt-4o-mini"), output_schema=Report).save(db=db)

        studio = StudioTools(registry=Registry(), db=db)
        out = _loads(studio.edit_agent("schema-agent", description="edited"))
        assert out.get("status") == "edited"

        row = db.get_config(component_id="schema-agent")
        assert row["config"]["output_schema"] == "Report"
        assert row["config"]["description"] == "edited"

    def test_team_edit_repins_members(self, tmp_path):
        from agno.db.sqlite import SqliteDb
        from agno.registry import Registry
        from agno.team.team import Team
        from agno.tools.studio import StudioTools

        db = SqliteDb(db_file=str(tmp_path / "repin_team.db"))
        member = Agent(id="rp-member", name="Member")
        Team(id="rp-team", name="Team", members=[member]).save(db=db)

        studio = StudioTools(registry=Registry(), db=db, teams=True)
        out = _loads(studio.edit_team("rp-team", description="edited"))
        assert out.get("status") == "edited"

        version = out.get("version") or out.get("draft_version")
        links = db.get_links(component_id="rp-team", version=version)
        assert [link["child_component_id"] for link in links] == ["rp-member"]
        assert all(link["child_version"] is not None for link in links)

    def test_workflow_edit_repins_step_members(self, tmp_path):
        from agno.db.sqlite import SqliteDb
        from agno.registry import Registry
        from agno.tools.studio import StudioTools
        from agno.workflow.step import Step
        from agno.workflow.workflow import Workflow

        db = SqliteDb(db_file=str(tmp_path / "repin_wf.db"))
        agent = Agent(id="rw-agent", name="A")
        Workflow(id="rw-wf", name="WF", steps=[Step(name="s1", agent=agent)]).save(db=db)

        studio = StudioTools(registry=Registry(), db=db, workflows=True)
        out = _loads(studio.edit_workflow("rw-wf", description="edited"))
        assert out.get("status") == "edited"

        version = out.get("version") or out.get("draft_version")
        links = db.get_links(component_id="rw-wf", version=version)
        assert "rw-agent" in [link["child_component_id"] for link in links]


class TestSnapshotSafety:
    def test_create_team_pins_members_at_creation(self, tmp_path):
        from agno.db.sqlite import SqliteDb
        from agno.models.openai import OpenAIChat
        from agno.registry import Registry
        from agno.tools.studio import StudioTools

        db = SqliteDb(db_file=str(tmp_path / "create_pin.db"))
        Agent(id="cp-member", name="Member").save(db=db)
        model = OpenAIChat(id="gpt-4o-mini")
        studio = StudioTools(registry=Registry(models=[model], dbs=[db]), db=db, teams=True)

        out = _loads(
            studio.create_team(name="CP Crew", instructions="i", member_ids=["cp-member"], model_id="gpt-4o-mini")
        )
        assert out.get("status") == "created"

        links = db.get_links(component_id=out["id"], version=1)
        assert [link["child_component_id"] for link in links] == ["cp-member"]

    def test_unrelated_edit_carries_base_pins_forward(self, tmp_path):
        from agno.db.sqlite import SqliteDb
        from agno.registry import Registry
        from agno.team.team import Team
        from agno.tools.studio import StudioTools

        db = SqliteDb(db_file=str(tmp_path / "carry.db"))
        member = Agent(id="cf-member", name="Member", description="v1")
        Team(id="cf-team", name="Team", members=[member]).save(db=db)
        base_pin = next(
            link["child_version"]
            for link in db.get_links(component_id="cf-team", version=1)
            if link["link_kind"] == "member"
        )
        member.description = "v2"
        member.save(db=db)

        studio = StudioTools(registry=Registry(dbs=[db]), db=db, teams=True)
        out = _loads(studio.edit_team("cf-team", description="edited"))
        assert out.get("status") == "edited"

        version = out.get("version") or out.get("draft_version")
        links = db.get_links(component_id="cf-team", version=version)
        assert [link["child_version"] for link in links if link["link_kind"] == "member"] == [base_pin]

    def test_unrelated_edit_keeps_the_stored_db_reference(self, tmp_path):
        from agno.db.base import ComponentType
        from agno.db.sqlite import SqliteDb
        from agno.registry import Registry
        from agno.tools.studio import StudioTools

        db = SqliteDb(db_file=str(tmp_path / "dbref.db"))
        db.upsert_component(component_id="opaque-agent", component_type=ComponentType.AGENT, name="A")
        stored_db = {"id": "private", "type": "custom-opaque"}
        db.upsert_config(
            component_id="opaque-agent",
            config={"id": "opaque-agent", "name": "A", "db": stored_db},
            stage="published",
        )

        studio = StudioTools(registry=Registry(dbs=[db]), db=db)
        out = _loads(studio.edit_agent("opaque-agent", description="edited"))
        assert out.get("status") == "edited"

        row = db.get_config(component_id="opaque-agent")
        assert row["config"]["db"] == stored_db
        assert row["config"]["description"] == "edited"


class TestEditIdentityStability:
    def test_description_edit_keeps_step_ids_and_per_step_pins(self, tmp_path):
        """An unrelated edit must not re-mint step_ids: carried-forward link
        keys name steps by step_id, so churn orphans every pin."""
        from agno.db.sqlite import SqliteDb
        from agno.registry import Registry
        from agno.tools.studio import StudioTools
        from agno.workflow.step import Step
        from agno.workflow.workflow import Workflow

        db = SqliteDb(db_file=str(tmp_path / "stepid.db"))
        agent = Agent(id="si-agent", name="A")
        Workflow(id="si-wf", name="WF", steps=[Step(name="s1", agent=agent)]).save(db=db)
        base_ids = [s["step_id"] for s in db.get_config(component_id="si-wf")["config"]["steps"]]

        studio = StudioTools(registry=Registry(dbs=[db]), db=db, workflows=True)
        out = _loads(studio.edit_workflow("si-wf", description="edited"))
        assert out.get("status") == "edited"

        version = out.get("version") or out.get("draft_version")
        new_config = db.get_config(component_id="si-wf", version=version)["config"]
        assert [s["step_id"] for s in new_config["steps"]] == base_ids
        link_keys = {link["link_key"] for link in db.get_links(component_id="si-wf", version=version)}
        assert link_keys <= set(base_ids)

    def test_description_edit_keeps_auxiliary_model_keys(self, tmp_path):
        """to_dict emits reasoning/parser/output models that from_dict does not
        yet consume; an unrelated edit must not persist their loss."""
        from agno.db.base import ComponentType
        from agno.db.sqlite import SqliteDb
        from agno.registry import Registry
        from agno.tools.studio import StudioTools

        db = SqliteDb(db_file=str(tmp_path / "auxmodels.db"))
        db.upsert_component(component_id="aux-agent", component_type=ComponentType.AGENT, name="A")
        aux = {"provider": "OpenAI", "id": "gpt-5.5"}
        db.upsert_config(
            component_id="aux-agent",
            config={
                "id": "aux-agent",
                "name": "A",
                "reasoning_model": aux,
                "parser_model": aux,
                "output_model": aux,
                "parser_model_prompt": "parse",
            },
            stage="published",
        )

        studio = StudioTools(registry=Registry(dbs=[db]), db=db)
        out = _loads(studio.edit_agent("aux-agent", description="edited"))
        assert out.get("status") == "edited"

        config = db.get_config(component_id="aux-agent")["config"]
        assert config["reasoning_model"] == aux
        assert config["parser_model"] == aux
        assert config["output_model"] == aux


class TestPinProvenance:
    def test_links_skip_children_shadowed_by_code_defined_components(self, tmp_path):
        """A code-defined component with the child's exact id wins resolution,
        so pinning the same-id db shadow row would bind an unrelated config."""
        from agno.db.sqlite import SqliteDb
        from agno.registry import Registry
        from agno.team.team import Team
        from agno.tools.studio import StudioTools

        db = SqliteDb(db_file=str(tmp_path / "shadow.db"))
        Agent(id="dual", name="DB Shadow").save(db=db)
        code_agent = Agent(id="dual", name="Live Code Agent")
        team = Team(id="sh-team", name="Team", members=[code_agent])

        studio = StudioTools(registry=Registry(dbs=[db]), db=db, teams=True, agents_list=[code_agent])
        links = studio._links_for_component(team)

        assert links == []

    def test_description_edit_preserves_the_exact_stored_model(self, tmp_path):
        """The primary model subtree is base-authoritative: a lossy round trip
        must not rewrite fields from_dict does not model."""
        from agno.db.base import ComponentType
        from agno.db.sqlite import SqliteDb
        from agno.models.openai import OpenAIChat
        from agno.registry import Registry
        from agno.tools.studio import StudioTools

        db = SqliteDb(db_file=str(tmp_path / "modelkeep.db"))
        db.upsert_component(component_id="fm-agent", component_type=ComponentType.AGENT, name="A")
        stored_model = {"provider": "OpenAI", "id": "gpt-5.5", "future_config": {"region": "private"}}
        db.upsert_config(
            component_id="fm-agent",
            config={"id": "fm-agent", "name": "A", "model": stored_model},
            stage="published",
        )

        studio = StudioTools(registry=Registry(models=[OpenAIChat(id="gpt-4o-mini")], dbs=[db]), db=db)
        out = _loads(studio.edit_agent("fm-agent", description="edited"))
        assert out.get("status") == "edited"
        assert db.get_config(component_id="fm-agent")["config"]["model"] == stored_model

        # An explicit model edit still replaces it.
        out = _loads(studio.edit_agent("fm-agent", model_id="gpt-4o-mini"))
        assert out.get("status") == "edited"
        assert db.get_config(component_id="fm-agent")["config"]["model"].get("id") == "gpt-4o-mini"


class TestTargetDbBinding:
    def _studio(self, db, **kwargs):
        from agno.models.openai import OpenAIChat
        from agno.registry import Registry
        from agno.tools.studio import StudioTools

        model = OpenAIChat(id="gpt-4o-mini")
        registry = Registry(models=[model], dbs=kwargs.pop("dbs"))
        return StudioTools(registry=registry, db=db, teams=True, workflows=True, **kwargs), model

    def test_create_refuses_a_member_absent_from_the_target_db(self, tmp_path):
        from agno.db.sqlite import SqliteDb

        db_a = SqliteDb(id="cat-a", db_file=str(tmp_path / "a.db"))
        db_b = SqliteDb(id="cat-b", db_file=str(tmp_path / "b.db"))
        Agent(id="only-a", name="A").save(db=db_a)
        studio, _ = self._studio(db_a, dbs=[db_a, db_b])

        out = _loads(
            studio.create_team(
                name="XT", instructions="i", member_ids=["only-a"], db_id="cat-b", model_id="gpt-4o-mini"
            )
        )

        assert "not stored in db 'cat-b'" in out.get("error", "")

    def test_create_into_b_binds_and_pins_bs_row(self, tmp_path):
        """A same-id child existing in both catalogs must resolve, pin and
        reload exclusively from the selected target db."""
        from agno.db.sqlite import SqliteDb
        from agno.team.team import get_team_by_id

        db_a = SqliteDb(id="cat-a", db_file=str(tmp_path / "a2.db"))
        db_b = SqliteDb(id="cat-b", db_file=str(tmp_path / "b2.db"))
        Agent(id="dual", name="A", description="from-A").save(db=db_a)
        Agent(id="dual", name="A", description="from-B").save(db=db_b)
        studio, _ = self._studio(db_a, dbs=[db_a, db_b])

        out = _loads(
            studio.create_team(name="BT", instructions="i", member_ids=["dual"], db_id="cat-b", model_id="gpt-4o-mini")
        )
        assert out.get("status") == "created"

        loaded = get_team_by_id(db=db_b, id=out["id"], strict=True)
        assert loaded is not None
        assert loaded.members[0].description == "from-B"

    def test_create_refuses_an_id_claimed_by_code_and_the_target_db(self, tmp_path):
        from agno.db.sqlite import SqliteDb

        db = SqliteDb(id="cat", db_file=str(tmp_path / "amb.db"))
        Agent(id="both", name="DB Row").save(db=db)
        code_agent = Agent(id="both", name="Live Code")
        studio, _ = self._studio(db, dbs=[db], agents_list=[code_agent])

        out = _loads(studio.create_team(name="AT", instructions="i", member_ids=["both"], model_id="gpt-4o-mini"))

        assert "claimed by both" in out.get("error", "")

    def test_agents_list_member_survives_a_strict_reload(self, tmp_path):
        """List members mirror into the registry, so a stored reference to
        them rehydrates instead of vanishing."""
        from agno.db.sqlite import SqliteDb
        from agno.team.team import get_team_by_id

        db = SqliteDb(id="cat", db_file=str(tmp_path / "list.db"))
        list_agent = Agent(id="listed", name="Listed")
        studio, _ = self._studio(db, dbs=[db], agents_list=[list_agent])

        out = _loads(studio.create_team(name="LT", instructions="i", member_ids=["listed"], model_id="gpt-4o-mini"))
        assert out.get("status") == "created"

        loaded = get_team_by_id(db=db, id=out["id"], registry=studio.registry, strict=True)
        assert loaded is not None
        assert loaded.members[0].id == "listed"


class TestSourceConsistency:
    def test_construction_refuses_distinct_list_and_registry_objects_sharing_an_id(self):
        from agno.registry import Registry
        from agno.tools.studio import StudioTools

        registry_agent = Agent(id="split", name="Registry Object")
        list_agent = Agent(id="split", name="List Object")

        with pytest.raises(ValueError, match="distinct components with id 'split'"):
            StudioTools(registry=Registry(agents=[registry_agent]), agents_list=[list_agent])

        # The same object in both places is consistent and accepted.
        shared = Agent(id="shared", name="Shared")
        StudioTools(registry=Registry(agents=[shared]), agents_list=[shared])

    def test_edit_workflow_step_replacement_refuses_code_db_ambiguity(self, tmp_path):
        from agno.db.sqlite import SqliteDb
        from agno.models.openai import OpenAIChat
        from agno.registry import Registry
        from agno.tools.studio import StudioTools
        from agno.workflow.step import Step
        from agno.workflow.workflow import Workflow

        db = SqliteDb(id="cat", db_file=str(tmp_path / "ewb.db"))
        Agent(id="amb", name="DB Row").save(db=db)
        clean = Agent(id="clean", name="Clean")
        clean.save(db=db)
        Workflow(id="ew-wf", name="WF", steps=[Step(name="s1", agent=clean)]).save(db=db)
        code_agent = Agent(id="amb", name="Live Code")
        model = OpenAIChat(id="gpt-4o-mini")
        studio = StudioTools(
            registry=Registry(models=[model], dbs=[db]), db=db, workflows=True, agents_list=[code_agent]
        )

        out = _loads(studio.edit_workflow("ew-wf", step_specs=[{"name": "s1", "agent_id": "amb"}]))

        assert "claimed by both" in out.get("error", "")

    def test_create_refuses_a_same_id_row_of_the_wrong_type(self, tmp_path):
        from agno.db.sqlite import SqliteDb
        from agno.models.openai import OpenAIChat
        from agno.registry import Registry
        from agno.team.team import Team
        from agno.tools.studio import StudioTools

        db_a = SqliteDb(id="cat-a", db_file=str(tmp_path / "wt_a.db"))
        db_b = SqliteDb(id="cat-b", db_file=str(tmp_path / "wt_b.db"))
        Agent(id="typed", name="Agent In A").save(db=db_a)
        Team(id="typed", name="Team In B", members=[Agent(id="tm", name="M")]).save(db=db_b)
        model = OpenAIChat(id="gpt-4o-mini")
        studio = StudioTools(registry=Registry(models=[model], dbs=[db_a, db_b]), db=db_a, teams=True)

        out = _loads(
            studio.create_team(name="WT", instructions="i", member_ids=["typed"], db_id="cat-b", model_id="gpt-4o-mini")
        )

        assert "as a" in out.get("error", "") and "not the referenced type" in out.get("error", "")

    def test_create_pins_the_version_the_binder_selected(self, tmp_path):
        """The binder's verified snapshot decides the pin: a publish between
        its reads refuses, a publish after them stays self-consistent."""
        from agno.db.sqlite import SqliteDb
        from agno.models.openai import OpenAIChat
        from agno.registry import Registry
        from agno.tools.studio import StudioTools

        db = SqliteDb(id="cat", db_file=str(tmp_path / "snap.db"))
        member = Agent(id="sn-member", name="M", description="v1")
        member.save(db=db)
        model = OpenAIChat(id="gpt-4o-mini")
        studio = StudioTools(registry=Registry(models=[model], dbs=[db]), db=db, teams=True)

        real_get_config = db.get_config
        state = {"calls": 0}

        def racy_get_config(trigger_call):
            def wrapper(component_id=None, version=None, **kwargs):
                row = real_get_config(component_id=component_id, version=version, **kwargs)
                if component_id == "sn-member":
                    state["calls"] += 1
                    if state["calls"] == trigger_call:
                        member.description = "v2"
                        member.save(db=db)
                return row

            return wrapper

        # A publish BETWEEN the binder's snapshot and verify reads is detected
        # and refused rather than persisted torn.
        db.get_config = racy_get_config(2)
        try:
            out = _loads(
                studio.create_team(name="SN", instructions="i", member_ids=["sn-member"], model_id="gpt-4o-mini")
            )
        finally:
            del db.get_config
        assert "changed while it was being referenced" in out.get("error", "")

        # A publish AFTER the verified snapshot leaves a self-consistent pin:
        # the committed version rides through to the link and the reload.
        member.description = "v1"
        member.save(db=db)
        committed = db.get_config(component_id="sn-member")["version"]
        state["calls"] = 0
        db.get_config = racy_get_config(3)
        try:
            out = _loads(
                studio.create_team(name="SN2", instructions="i", member_ids=["sn-member"], model_id="gpt-4o-mini")
            )
        finally:
            del db.get_config

        assert out.get("status") == "created"
        from agno.team.team import get_team_by_id

        links = db.get_links(component_id=out["id"], version=1)
        pins = [link["child_version"] for link in links if link["link_kind"] == "member"]
        assert pins == [committed]
        loaded = get_team_by_id(db=db, id=out["id"], strict=True)
        assert loaded is not None
        assert loaded.members[0].description == "v1"

    def test_member_existing_only_in_the_target_db_resolves(self, tmp_path):
        from agno.db.sqlite import SqliteDb
        from agno.models.openai import OpenAIChat
        from agno.registry import Registry
        from agno.team.team import get_team_by_id
        from agno.tools.studio import StudioTools

        db_a = SqliteDb(id="cat-a", db_file=str(tmp_path / "only_a.db"))
        db_b = SqliteDb(id="cat-b", db_file=str(tmp_path / "only_b.db"))
        Agent(id="b-only", name="B Only").save(db=db_b)
        model = OpenAIChat(id="gpt-4o-mini")
        studio = StudioTools(registry=Registry(models=[model], dbs=[db_a, db_b]), db=db_a, teams=True)

        out = _loads(
            studio.create_team(
                name="BO", instructions="i", member_ids=["b-only"], db_id="cat-b", model_id="gpt-4o-mini"
            )
        )
        assert out.get("status") == "created"

        loaded = get_team_by_id(db=db_b, id=out["id"], strict=True)
        assert loaded is not None
        assert loaded.members[0].id == "b-only"

    def test_step_workflow_pins_are_not_suppressed_by_a_same_id_agent(self, tmp_path):
        from agno.db.sqlite import SqliteDb
        from agno.registry import Registry
        from agno.tools.studio import StudioTools
        from agno.workflow.step import Step, StepInput, StepOutput
        from agno.workflow.workflow import Workflow

        def leaf(step_input: StepInput) -> StepOutput:
            return StepOutput(content="x")

        db = SqliteDb(id="cat", db_file=str(tmp_path / "swf.db"))
        sub = Workflow(id="sub-flow", name="Sub", steps=[Step(name="x", executor=leaf)])
        sub.save(db=db)
        parent = Workflow(id="par-flow", name="Par", steps=[Step(name="n", workflow=sub)])
        lookalike_agent = Agent(id="sub-flow", name="Unrelated Agent")

        studio = StudioTools(registry=Registry(dbs=[db]), db=db, workflows=True, agents_list=[lookalike_agent])
        links = studio._links_for_component(parent)

        nested = [link for link in links if link["link_kind"] == "step_workflow"]
        assert nested and nested[0]["child_component_id"] == "sub-flow"


class TestResolutionPrecedence:
    def test_target_db_exact_id_beats_catalog_display_name(self, tmp_path):
        """A live component merely NAMED like a target-db id must not steal
        the reference from the target db's exact-id row."""
        from agno.db.sqlite import SqliteDb
        from agno.models.openai import OpenAIChat
        from agno.registry import Registry
        from agno.team.team import get_team_by_id
        from agno.tools.studio import StudioTools

        db_a = SqliteDb(id="cat-a", db_file=str(tmp_path / "prec_a.db"))
        db_b = SqliteDb(id="cat-b", db_file=str(tmp_path / "prec_b.db"))
        Agent(id="target-id", name="Target Row", description="from-target").save(db=db_b)
        impostor = Agent(id="impostor", name="target-id")
        model = OpenAIChat(id="gpt-4o-mini")
        studio = StudioTools(
            registry=Registry(models=[model], dbs=[db_a, db_b]), db=db_a, teams=True, agents_list=[impostor]
        )

        out = _loads(
            studio.create_team(
                name="PT", instructions="i", member_ids=["target-id"], db_id="cat-b", model_id="gpt-4o-mini"
            )
        )
        assert out.get("status") == "created"

        loaded = get_team_by_id(db=db_b, id=out["id"], strict=True)
        assert loaded is not None
        assert loaded.members[0].description == "from-target"

    def test_agent_appended_to_the_live_list_after_construction_reloads(self, tmp_path):
        from agno.db.sqlite import SqliteDb
        from agno.models.openai import OpenAIChat
        from agno.registry import Registry
        from agno.team.team import get_team_by_id
        from agno.tools.studio import StudioTools

        db = SqliteDb(id="cat", db_file=str(tmp_path / "late.db"))
        live: list = []
        model = OpenAIChat(id="gpt-4o-mini")
        studio = StudioTools(registry=Registry(models=[model], dbs=[db]), db=db, teams=True, agents_list=live)
        live.append(Agent(id="late", name="Late Arrival"))

        out = _loads(studio.create_team(name="LL", instructions="i", member_ids=["late"], model_id="gpt-4o-mini"))
        assert out.get("status") == "created"

        loaded = get_team_by_id(db=db, id=out["id"], registry=studio.registry, strict=True)
        assert loaded is not None
        assert loaded.members[0].id == "late"

    def test_replaced_live_list_entry_refuses_instead_of_reload_flipping(self, tmp_path):
        from agno.db.sqlite import SqliteDb
        from agno.models.openai import OpenAIChat
        from agno.registry import Registry
        from agno.tools.studio import StudioTools

        db = SqliteDb(id="cat", db_file=str(tmp_path / "replace.db"))
        original = Agent(id="swap", name="Original")
        live = [original]
        model = OpenAIChat(id="gpt-4o-mini")
        studio = StudioTools(registry=Registry(models=[model], dbs=[db]), db=db, teams=True, agents_list=live)
        live[0] = Agent(id="swap", name="Replacement")

        out = _loads(studio.create_team(name="RL", instructions="i", member_ids=["swap"], model_id="gpt-4o-mini"))

        assert "not the registry's object" in out.get("error", "")

    def test_create_refuses_a_draft_only_child(self, tmp_path):
        from agno.db.base import ComponentType
        from agno.db.sqlite import SqliteDb
        from agno.models.openai import OpenAIChat
        from agno.registry import Registry
        from agno.tools.studio import StudioTools

        db = SqliteDb(id="cat", db_file=str(tmp_path / "draft.db"))
        db.upsert_component(component_id="draft-child", component_type=ComponentType.AGENT, name="D")
        db.upsert_config(component_id="draft-child", config={"id": "draft-child", "name": "D"}, stage="draft")
        model = OpenAIChat(id="gpt-4o-mini")
        studio = StudioTools(registry=Registry(models=[model], dbs=[db]), db=db, teams=True)

        out = _loads(
            studio.create_team(name="DC", instructions="i", member_ids=["draft-child"], model_id="gpt-4o-mini")
        )

        assert "Publish the child first" in out.get("error", "")
