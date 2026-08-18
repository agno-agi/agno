"""Unit tests for the StudioTools toolkit (studio-3.0 spec section 3.4).

Uses a real SqliteDb backed by a pytest tmp_path so the full component +
config persistence path is exercised, not mocked.

Every tool returns one JSON envelope (StudioResult): {ok, status, data,
error: {code, message, details, retryable}, warnings}. Tests branch on the
stable error codes, not on message prose.
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
from agno.tools.studio_schema import WorkflowStepSpec
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
def studio_unversioned(registry, db):
    return StudioTools(registry=registry, db=db, versions=False)


@pytest.fixture
def studio_schedules(registry, db):
    return StudioTools(registry=registry, db=db, schedules=True)


def _loads(s: str) -> Dict[str, Any]:
    return json.loads(s)


def _data(s: str) -> Dict[str, Any]:
    """The data half of a successful envelope; fails loudly on an error."""
    out = json.loads(s)
    assert out.get("ok") is True, out
    return out["data"]


def _error(s: str) -> Dict[str, Any]:
    """The error half of a failed envelope; fails loudly on a success."""
    out = json.loads(s)
    assert out.get("ok") is False, out
    return out["error"]


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


DISCOVERY_TOOLS = {
    "list_models",
    "list_tools",
    "list_functions",
    "list_knowledge",
    "list_schemas",
    "list_components",
    "get_component",
}

LIFECYCLE_TOOLS = {"validate_component", "archive_component", "restore_component"}

VERSIONING_TOOLS = {
    "list_versions",
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
    def test_default_registers_agents_discovery_lifecycle_and_versions(self, studio):
        expected = DISCOVERY_TOOLS | LIFECYCLE_TOOLS | VERSIONING_TOOLS | {"create_agent", "edit_agent", "run_agent"}
        assert expected == set(studio.functions.keys())

    def test_versioning_tools_registered_by_default(self, studio):
        assert studio.enable_versions is True
        assert VERSIONING_TOOLS.issubset(set(studio.functions.keys()))
        assert VERSIONING_TOOLS.issubset(set(studio.async_functions.keys()))

    def test_versions_false_removes_versioning_tools(self, studio_unversioned):
        assert studio_unversioned.enable_versions is False
        assert not VERSIONING_TOOLS & set(studio_unversioned.functions.keys())
        assert not VERSIONING_TOOLS & set(studio_unversioned.async_functions.keys())

    def test_schedule_tools_not_registered_by_default(self, studio):
        assert studio.enable_schedules is False
        assert not SCHEDULE_TOOLS & set(studio.functions.keys())
        assert not SCHEDULE_TOOLS & set(studio.async_functions.keys())

    def test_schedules_flag_registers_schedule_tools(self, studio_schedules):
        assert studio_schedules.enable_schedules is True
        assert SCHEDULE_TOOLS.issubset(set(studio_schedules.functions.keys()))
        assert SCHEDULE_TOOLS.issubset(set(studio_schedules.async_functions.keys()))

    def test_management_tools_are_shared_with_scheduler_toolkit(self, studio_schedules):
        from agno.tools.scheduler import SchedulerTools

        for tool_name in SCHEDULE_TOOLS - {"create_schedule"}:
            sync_owner = studio_schedules.functions[tool_name].entrypoint.__self__
            async_owner = studio_schedules.async_functions[tool_name].entrypoint.__self__
            assert isinstance(sync_owner, SchedulerTools), tool_name
            assert isinstance(async_owner, SchedulerTools), tool_name
        assert studio_schedules.functions["create_schedule"].entrypoint.__self__ is studio_schedules

    def test_instructions_carry_the_lifecycle_contract(self, studio):
        instructions = studio.instructions or ""
        assert "publish_component" in instructions
        assert "get_component" in instructions
        assert "archive_component" in instructions

    def test_add_instructions_defaults_on_and_respects_override(self, registry, db):
        assert StudioTools(registry=registry, db=db).add_instructions is True
        assert StudioTools(registry=registry, db=db, add_instructions=False).add_instructions is False

    def test_default_does_not_register_team_or_workflow_tools(self, studio):
        names = set(studio.functions.keys())
        for absent in ("create_team", "create_workflow", "edit_team", "edit_workflow"):
            assert absent not in names

    def test_async_surface_matches_sync_surface(self, studio):
        assert set(studio.async_functions.keys()) == set(studio.functions.keys())

    def test_async_surface_matches_when_everything_is_enabled(self, registry, db):
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

    def test_default_confirmation_pauses_on_deletion_shaped_tools(self, registry, db):
        assert StudioTools(registry=registry, db=db).requires_confirmation_tools == [
            "archive_component",
            "delete_version",
        ]
        with_schedules = StudioTools(registry=registry, db=db, schedules=True)
        assert with_schedules.requires_confirmation_tools == [
            "archive_component",
            "delete_version",
            "delete_schedule",
        ]

    def test_default_confirmation_skips_unregistered_tools(self, registry, db):
        assert StudioTools(registry=registry, db=db, versions=False).requires_confirmation_tools == [
            "archive_component"
        ]

    def test_caller_owns_the_confirmation_list_including_empty(self, registry, db):
        assert StudioTools(registry=registry, db=db, requires_confirmation_tools=[]).requires_confirmation_tools == []
        custom = StudioTools(registry=registry, db=db, requires_confirmation_tools=["create_agent"])
        assert custom.requires_confirmation_tools == ["create_agent"]


# ----------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------


class TestDiscovery:
    def test_list_models(self, studio):
        data = _data(studio.list_models())
        ids = {m["id"] for m in data["models"]}
        assert ids == {"gpt-5.4", "gpt-5.5"}

    def test_list_tools_rows_carry_kind_buildable_source_and_functions(self, studio):
        data = _data(studio.list_tools())
        rows = {t["name"]: t for t in data["tools"]}
        assert "calculator" in rows
        assert "websearch" in rows  # DuckDuckGoTools registers as 'websearch'
        calculator = rows["calculator"]
        assert calculator["kind"] == "toolkit"
        assert calculator["buildable"] is True
        assert calculator["source"] == "declared"
        function_names = {f["name"] for f in calculator["functions"]}
        assert "add" in function_names
        for entry in calculator["functions"]:
            assert set(entry) == {"name", "description", "mutating"}

    def test_list_functions(self, registry, db):
        def transform_content(value: str) -> str:
            """Transform content for a workflow step."""
            return value.upper()

        registry.functions.append(transform_content)
        studio = StudioTools(registry=registry, db=db)

        data = _data(studio.list_functions())
        assert data["count"] == 1
        assert data["functions"][0]["name"] == "transform_content"
        assert data["functions"][0]["description"] == "Transform content for a workflow step."
        assert data["functions"][0]["signature"] == "(value: str) -> str"

    def test_list_knowledge_and_schemas_report_exact_names(self, registry, db):
        from pydantic import BaseModel

        class Report(BaseModel):
            text: str

        class FakeKnowledge:
            name = "handbook"

        registry.add_schema(Report)
        registry.add_knowledge(FakeKnowledge())
        studio = StudioTools(registry=registry, db=db)

        assert _data(studio.list_knowledge())["knowledge"] == ["handbook"]
        assert _data(studio.list_schemas())["schemas"] == ["Report"]

    def test_list_components_merges_code_and_db_with_source(self, registry, db):
        code_agent = Agent(id="code-only", name="Code Only", model=OpenAIResponses(id="gpt-5.4"))
        tool = StudioTools(registry=registry, db=db, agents_list=[code_agent])
        tool.create_agent(name="math-king", instructions="i", model_id="gpt-5.4")

        data = _data(tool.list_components(component_type="agent"))
        by_id = {row["id"]: row for row in data["components"]}
        assert by_id["code-only"]["source"] == "code"
        assert by_id["math-king"]["source"] == "db"
        assert by_id["math-king"]["latest_version"] == 1
        assert by_id["math-king"]["latest_stage"] == "draft"
        assert by_id["math-king"]["current_version"] is None

    def test_list_components_shows_current_version_after_publish(self, studio):
        studio.create_agent(name="live-one", instructions="i", model_id="gpt-5.4", publish=True)
        data = _data(studio.list_components(component_type="agent"))
        row = next(r for r in data["components"] if r["id"] == "live-one")
        assert row["current_version"] == 1
        assert row["latest_stage"] == "published"

    def test_list_components_dedupes_when_code_shadows_db(self, registry, db):
        tool = StudioTools(registry=registry, db=db)
        tool.create_agent(name="shared", instructions="i", model_id="gpt-5.4")

        code_agent = Agent(id="shared", name="Shared Code", model=OpenAIResponses(id="gpt-5.4"))
        tool2 = StudioTools(registry=registry, db=db, agents_list=[code_agent])

        data = _data(tool2.list_components(component_type="agent"))
        shared_entries = [row for row in data["components"] if row["id"] == "shared"]
        assert len(shared_entries) == 1
        assert shared_entries[0]["source"] == "code"

    def test_list_components_dedupes_code_without_id_by_name(self, registry, db):
        tool = StudioTools(registry=registry, db=db)
        tool.create_agent(name="Shared Name", instructions="i", model_id="gpt-5.4")

        code_agent = Agent(name="Shared Name", model=OpenAIResponses(id="gpt-5.4"))
        tool2 = StudioTools(registry=registry, db=db, agents_list=[code_agent])

        data = _data(tool2.list_components(component_type="agent"))
        shared_entries = [row for row in data["components"] if row["name"] == "Shared Name"]
        assert len(shared_entries) == 1
        assert shared_entries[0]["source"] == "code"

    def test_list_components_keeps_db_row_whose_id_equals_a_code_name(self, registry, db):
        # A code agent id="code-1" is NAMED "support"; a distinct DB agent has id
        # "support". Exact ids win on every resolution path, so the listing must
        # not hide the DB row behind the code agent's display name.
        seed = StudioTools(registry=registry, db=db)
        seed.create_agent(name="support", instructions="i", model_id="gpt-5.4")

        code_agent = Agent(id="code-1", name="support", model=OpenAIResponses(id="gpt-5.4"))
        studio = StudioTools(registry=registry, db=db, agents_list=[code_agent])
        ids = {row["id"] for row in _data(studio.list_components())["components"]}
        assert "code-1" in ids
        assert "support" in ids

    def test_list_components_covers_teams_and_workflows(self, registry, db):
        tool = StudioTools(registry=registry, db=db, teams=True, workflows=True)
        tool.create_agent(name="a1", instructions="i", model_id="gpt-5.4")
        tool.create_team(name="squad", instructions="i", member_ids=["a1"], model_id="gpt-5.4")
        tool.create_workflow(name="pipeline", steps=[{"name": "s1", "agent_id": "a1"}])

        rows = _data(tool.list_components())["components"]
        types = {row["id"]: row["component_type"] for row in rows}
        assert types["squad"] == "team"
        assert types["pipeline"] == "workflow"
        assert types["a1"] == "agent"

    def test_list_components_rejects_an_unknown_type(self, studio):
        assert _error(studio.list_components(component_type="bot"))["code"] == "invalid_request"


# ----------------------------------------------------------------------
# Creation
# ----------------------------------------------------------------------


class TestCreateAgent:
    def test_create_is_a_draft_by_default(self, studio, db):
        data = _data(
            studio.create_agent(
                name="news-scout",
                instructions="Summarize tech news.",
                model_id="gpt-5.4",
                tool_names=["calculator"],
            )
        )
        assert data["id"] == "news-scout"
        assert data["version"] == 1
        assert data["stage"] == "draft"
        assert data["is_current"] is False

        component = db.get_component("news-scout")
        assert component is not None
        assert component["component_type"] == "agent"
        assert _data(studio.get_component("news-scout"))["tools"] == ["calculator"]

    def test_create_status_is_created(self, studio):
        out = _loads(studio.create_agent(name="statused", instructions="i", model_id="gpt-5.4"))
        assert out["status"] == "created"

    def test_publish_true_makes_version_one_live(self, studio, db):
        data = _data(studio.create_agent(name="live", instructions="i", model_id="gpt-5.4", publish=True))
        assert data["stage"] == "published"
        assert data["is_current"] is True
        assert db.get_config("live")["stage"] == "published"

    def test_unknown_model_returns_model_not_found(self, studio):
        error = _error(studio.create_agent(name="x", instructions="i", model_id="does-not-exist", tool_names=[]))
        assert error["code"] == "model_not_found"

    def test_unknown_tool_returns_tool_not_found(self, studio):
        error = _error(studio.create_agent(name="x", instructions="i", model_id="gpt-5.4", tool_names=["nonexistent"]))
        assert error["code"] == "tool_not_found"

    def test_create_without_tools(self, studio):
        _data(studio.create_agent(name="plain", instructions="i", model_id="gpt-5.4"))
        assert _data(studio.get_component("plain"))["tools"] == []

    def test_id_collision_is_a_conflict_carrying_the_existing_id(self, studio):
        first = _data(studio.create_agent(name="My Agent", instructions="i", model_id="gpt-5.4"))
        assert first["id"] == "my-agent"

        for colliding_name in ("my-agent", "My--Agent"):
            error = _error(studio.create_agent(name=colliding_name, instructions="i", model_id="gpt-5.4"))
            assert error["code"] == "component_conflict"
            assert error["details"]["existing_component_id"] == "my-agent"

    def test_same_display_name_conflict_points_at_the_existing_component(self, studio):
        _data(studio.create_agent(name="Analyst", instructions="i", model_id="gpt-5.4", component_id="custom-analyst"))
        error = _error(studio.create_agent(name="Analyst", instructions="i", model_id="gpt-5.4"))
        assert error["code"] == "component_conflict"
        assert error["details"]["existing_component_id"] == "custom-analyst"

    def test_component_ids_share_global_namespace(self, registry, db):
        tool = StudioTools(registry=registry, db=db, teams=True)
        tool.create_agent(name="member", instructions="i", model_id="gpt-5.4")
        team = _data(tool.create_team(name="Reporter", instructions="i", member_ids=["member"], model_id="gpt-5.4"))
        assert team["id"] == "reporter"

        error = _error(tool.create_agent(name="reporter", instructions="i", model_id="gpt-5.4"))
        assert error["code"] == "component_conflict"
        assert error["details"]["existing_component_id"] == "reporter"

    def test_explicit_component_id_overrides_the_name_mint(self, studio):
        first = _data(studio.create_agent(name="Twin", instructions="i", model_id="gpt-5.4"))
        assert first["id"] == "twin"
        # An explicit id sidesteps the display-name duplicate check, so a
        # deliberate same-name fork stays possible -- the remedy the conflict
        # message offers.
        second = _data(
            studio.create_agent(name="Twin", instructions="i", model_id="gpt-5.4", component_id="twin-custom")
        )
        assert second["id"] == "twin-custom"

    @pytest.mark.parametrize("bad_id", ["has space", "has/slash", "has?query", "has#frag", "has%pct"])
    def test_invalid_explicit_component_id_is_refused(self, studio, bad_id):
        error = _error(studio.create_agent(name="x", instructions="i", model_id="gpt-5.4", component_id=bad_id))
        assert error["code"] == "invalid_component_id"

    def test_persist_failure_returns_internal_error_without_leaking(self, studio, db, monkeypatch):
        def fail_upsert_config(*args, **kwargs):
            raise RuntimeError("persist failed: dsn=postgres://secret")

        monkeypatch.setattr(db, "upsert_config", fail_upsert_config)

        error = _error(studio.create_agent(name="broken", instructions="i", model_id="gpt-5.4"))
        assert error["code"] == "internal_error"
        assert "secret" not in error["message"]

    @pytest.mark.asyncio
    async def test_async_create_agent_persists_component(self, studio, db):
        out = _loads(await studio.acreate_agent(name="async-agent", instructions="i", model_id="gpt-5.4"))
        assert out["status"] == "created"
        assert db.get_component("async-agent") is not None

    def test_history_on_by_default(self, studio, db):
        studio.create_agent(name="mem", instructions="i", model_id="gpt-5.4")
        assert _data(studio.get_component("mem"))["add_history_to_context"] is True

        config = db.get_config("mem")["config"]
        assert config["add_history_to_context"] is True
        assert config["num_history_runs"] == 3  # Agent.__init__ normalization

    def test_stateless_opt_out_omits_history_from_config(self, studio, db):
        studio.create_agent(name="stateless", instructions="i", model_id="gpt-5.4", add_history_to_context=False)

        # to_dict omits falsy add_history_to_context, so the key is absent from
        # the config and the curated view.
        config = db.get_config("stateless")["config"]
        assert "add_history_to_context" not in config
        assert "add_history_to_context" not in _data(studio.get_component("stateless"))

    def test_explicit_num_history_runs_round_trips(self, studio, db):
        studio.create_agent(name="deep", instructions="i", model_id="gpt-5.4", num_history_runs=10, publish=True)

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
        assert out["ok"] is True
        config = db.get_config("async-stateless")["config"]
        assert "add_history_to_context" not in config

    def test_datetime_on_by_default(self, studio, db):
        studio.create_agent(name="dated", instructions="i", model_id="gpt-5.4")
        assert _data(studio.get_component("dated"))["add_datetime_to_context"] is True
        assert db.get_config("dated")["config"]["add_datetime_to_context"] is True

    def test_datetime_opt_out_omits_key_from_config(self, studio, db):
        studio.create_agent(name="undated", instructions="i", model_id="gpt-5.4", add_datetime_to_context=False)

        config = db.get_config("undated")["config"]
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

        data = _data(studio.list_tools())
        names = [t["name"] for t in data["tools"]]
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

        data = _data(
            studio.create_agent(name="web-search-agent", instructions="Search the web.", tool_names=[search.name])
        )
        assert data["id"] == "web-search-agent"
        assert _data(studio.get_component("web-search-agent"))["tools"] == [search.name]

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

        error = _error(studio.create_agent(name="x", instructions="i", tool_names=["dup"]))
        assert error["code"] == "invalid_request"
        assert "ambiguous" in error["message"]

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

        data = _data(
            studio.create_agent(
                name="guided-agent",
                instructions="Base agent guidance.",
                model_id="gpt-5.5",
                tool_names=[toolkit.name],
                publish=True,
            )
        )
        assert data["id"] == "guided-agent"

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

        error = _error(studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs"]))

        assert error["code"] == "invalid_request"
        assert "agno_docs" in error["message"]
        assert db.get_component("docs-agent") is None

    def test_edit_agent_refuses_unconnected_toolkit(self, db):
        toolkit = Toolkit(name="agno_docs")
        studio = StudioTool(registry=self._registry(db, toolkit), db=db)
        studio.create_agent(name="docs-agent", instructions="i")

        error = _error(studio.edit_agent(agent_id="docs-agent", tool_names=["agno_docs"]))

        assert error["code"] == "invalid_request"
        assert "agno_docs" in error["message"]

    def test_create_agent_persists_connected_toolkit_functions(self, db):
        toolkit = Toolkit(name="agno_docs")
        self._connect(toolkit)
        studio = StudioTool(registry=self._registry(db, toolkit), db=db)

        out = _loads(studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs"], publish=True))
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
        studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs"], publish=True)

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
    @pytest.fixture
    def studio_teams(self, registry, db):
        return StudioTools(registry=registry, db=db, teams=True)

    def _make_members(self, studio_teams, publish=True):
        studio_teams.create_agent(name="a1", instructions="i", model_id="gpt-5.4", publish=publish)
        studio_teams.create_agent(name="a2", instructions="i", model_id="gpt-5.4", publish=publish)

    def test_happy_path_is_a_draft(self, studio_teams, db):
        self._make_members(studio_teams)
        data = _data(
            studio_teams.create_team(
                name="squad",
                instructions="coordinate",
                member_ids=["a1", "a2"],
                model_id="gpt-5.4",
            )
        )
        assert data["member_ids"] == ["a1", "a2"]
        assert data["stage"] == "draft"
        assert db.get_component("squad")["component_type"] == "team"

    def test_publish_true_with_published_members(self, studio_teams):
        self._make_members(studio_teams)
        data = _data(
            studio_teams.create_team(
                name="live-squad", instructions="i", member_ids=["a1"], model_id="gpt-5.4", publish=True
            )
        )
        assert data["stage"] == "published"
        assert data["is_current"] is True

    def test_publishing_with_a_draft_member_is_refused(self, studio_teams):
        studio_teams.create_agent(name="draft-member", instructions="i", model_id="gpt-5.4")
        error = _error(
            studio_teams.create_team(
                name="eager", instructions="i", member_ids=["draft-member"], model_id="gpt-5.4", publish=True
            )
        )
        assert error["code"] == "invalid_request"
        assert "Publish the child first" in error["message"]

    def test_draft_team_may_reference_a_draft_member(self, studio_teams):
        studio_teams.create_agent(name="draft-member", instructions="i", model_id="gpt-5.4")
        data = _data(
            studio_teams.create_team(name="patient", instructions="i", member_ids=["draft-member"], model_id="gpt-5.4")
        )
        assert data["stage"] == "draft"

    def test_missing_member_returns_component_not_found(self, studio_teams):
        self._make_members(studio_teams)
        error = _error(
            studio_teams.create_team(
                name="squad",
                instructions="i",
                member_ids=["a1", "ghost"],
                model_id="gpt-5.4",
            )
        )
        assert error["code"] == "component_not_found"
        assert error["details"]["missing"] == ["ghost"]

    def test_empty_members_returns_invalid_request(self, studio_teams):
        error = _error(studio_teams.create_team(name="squad", instructions="i", member_ids=[], model_id="gpt-5.4"))
        assert error["code"] == "invalid_request"

    def test_unknown_mode_is_refused(self, studio_teams):
        self._make_members(studio_teams)
        error = _error(
            studio_teams.create_team(
                name="squad", instructions="i", member_ids=["a1"], model_id="gpt-5.4", mode="committee"
            )
        )
        assert error["code"] == "invalid_request"

    def test_mode_round_trips(self, studio_teams):
        self._make_members(studio_teams)
        _data(
            studio_teams.create_team(
                name="router-squad", instructions="i", member_ids=["a1"], model_id="gpt-5.4", mode="route"
            )
        )
        assert _data(studio_teams.get_component("router-squad"))["mode"] == "route"

    def test_history_and_datetime_on_by_default(self, studio_teams, db):
        self._make_members(studio_teams)
        studio_teams.create_team(name="squad", instructions="i", member_ids=["a1"], model_id="gpt-5.4")

        config = db.get_config("squad", version=1)["config"]
        assert config["add_history_to_context"] is True
        assert config["num_history_runs"] == 3  # Team.__init__ normalization
        assert config["add_datetime_to_context"] is True

    def test_stateless_opt_out_omits_history_from_config(self, studio_teams, db):
        self._make_members(studio_teams)
        studio_teams.create_team(
            name="squad",
            instructions="i",
            member_ids=["a1"],
            model_id="gpt-5.4",
            add_history_to_context=False,
            add_datetime_to_context=False,
        )

        # to_dict omits falsy flags, so the keys are absent.
        config = db.get_config("squad", version=1)["config"]
        assert "add_history_to_context" not in config
        assert "add_datetime_to_context" not in config

    def test_explicit_num_history_runs_round_trips(self, studio_teams, db):
        self._make_members(studio_teams)
        studio_teams.create_team(
            name="squad", instructions="i", member_ids=["a1"], model_id="gpt-5.4", num_history_runs=10, publish=True
        )

        config = db.get_config("squad")["config"]
        assert config["num_history_runs"] == 10

        team = studio_teams._load_team_from_db("squad")
        assert team.add_history_to_context is True
        assert team.num_history_runs == 10

    def test_toolkit_default_num_history_runs_applies(self, registry, db):
        tool = StudioTools(registry=registry, db=db, teams=True, default_num_history_runs=5)
        tool.create_agent(name="a1", instructions="i", model_id="gpt-5.4", publish=True)
        tool.create_team(name="five", instructions="i", member_ids=["a1"], model_id="gpt-5.4")

        config = db.get_config("five", version=1)["config"]
        assert config["num_history_runs"] == 5

    @pytest.mark.asyncio
    async def test_async_create_team_stateless(self, studio_teams, db):
        self._make_members(studio_teams)
        out = _loads(
            await studio_teams.acreate_team(
                name="async-squad",
                instructions="i",
                member_ids=["a1"],
                model_id="gpt-5.4",
                add_history_to_context=False,
            )
        )
        assert out["ok"] is True
        config = db.get_config("async-squad", version=1)["config"]
        assert "add_history_to_context" not in config


class TestCreateWorkflow:
    @pytest.fixture
    def studio_workflows(self, registry, db):
        return StudioTools(registry=registry, db=db, workflows=True)

    def _make_agents(self, studio_workflows, publish=True):
        studio_workflows.create_agent(name="a1", instructions="i", model_id="gpt-5.4", publish=publish)
        studio_workflows.create_agent(name="a2", instructions="i", model_id="gpt-5.4", publish=publish)

    def test_happy_path(self, studio_workflows, db):
        self._make_agents(studio_workflows)
        data = _data(
            studio_workflows.create_workflow(
                name="pipeline",
                description="two steps",
                steps=[
                    {"name": "s1", "agent_id": "a1"},
                    {"name": "s2", "agent_id": "a2"},
                ],
            )
        )
        assert data["steps"] == ["s1", "s2"]
        assert data["stage"] == "draft"
        assert db.get_component("pipeline")["component_type"] == "workflow"

    def test_empty_steps_returns_invalid_request(self, studio_workflows):
        error = _error(studio_workflows.create_workflow(name="x", steps=[]))
        assert error["code"] == "invalid_request"

    def test_missing_agent_in_step_returns_component_not_found(self, studio_workflows):
        error = _error(studio_workflows.create_workflow(name="x", steps=[{"name": "s1", "agent_id": "ghost"}]))
        assert error["code"] == "component_not_found"

    def test_step_without_executor_returns_invalid_request(self, studio_workflows):
        error = _error(studio_workflows.create_workflow(name="x", steps=[{"name": "s1"}]))
        assert error["code"] == "invalid_request"

    def test_publishing_with_a_draft_step_agent_is_refused(self, studio_workflows):
        studio_workflows.create_agent(name="draft-step", instructions="i", model_id="gpt-5.4")
        error = _error(
            studio_workflows.create_workflow(
                name="eager", steps=[{"name": "s1", "agent_id": "draft-step"}], publish=True
            )
        )
        assert error["code"] == "invalid_request"
        assert "Publish the child first" in error["message"]


class TestCompoundWorkflowSteps:
    """WorkflowStepSpec is recursive: parallel, loop, condition, router, and
    named sequential groups nest plain steps."""

    @pytest.fixture
    def studio_compound(self, registry, db):
        def score_check(step_input) -> bool:
            """Evaluate whether the pipeline should continue."""
            return True

        def pick_route(step_input):
            """Pick a route."""
            return []

        registry.functions.extend([score_check, pick_route])
        studio = StudioTools(registry=registry, db=db, workflows=True)
        studio.create_agent(name="w", instructions="i", model_id="gpt-5.4", publish=True)
        return studio

    def test_compound_workflow_builds_and_reads_back(self, studio_compound):
        data = _data(
            studio_compound.create_workflow(
                name="Compound",
                steps=[
                    {"name": "s1", "agent_id": "w"},
                    {"type": "parallel", "name": "par", "steps": [{"name": "p1", "agent_id": "w"}]},
                    {
                        "type": "loop",
                        "name": "lp",
                        "max_iterations": 2,
                        "steps": [{"name": "l1", "agent_id": "w"}],
                        "end_condition_function": "score_check",
                    },
                    {
                        "type": "condition",
                        "name": "cond",
                        "evaluator_function": "score_check",
                        "steps": [{"name": "c1", "agent_id": "w"}],
                        "else_steps": [{"name": "c2", "agent_id": "w"}],
                    },
                    {
                        "type": "router",
                        "name": "rt",
                        "selector_function": "pick_route",
                        "choices": [{"name": "r1", "agent_id": "w"}],
                    },
                ],
                publish=True,
            )
        )
        assert data["steps"] == ["s1", "par", "lp", "cond", "rt"]

        view = _data(studio_compound.get_component("compound"))
        assert view["steps"] == [
            {"type": "Step", "name": "s1"},
            {"type": "Parallel", "name": "par"},
            {"type": "Loop", "name": "lp"},
            {"type": "Condition", "name": "cond"},
            {"type": "Router", "name": "rt"},
        ]
        assert _data(studio_compound.validate_component("compound"))["valid"] is True

    def test_condition_accepts_a_cel_expression(self, studio_compound):
        data = _data(
            studio_compound.create_workflow(
                name="Cel Flow",
                steps=[
                    {
                        "type": "condition",
                        "name": "gate",
                        "evaluator_function": 'input.message != ""',
                        "steps": [{"name": "c1", "agent_id": "w"}],
                    }
                ],
            )
        )
        assert data["steps"] == ["gate"]

    def test_function_step_resolves_a_registered_function(self, studio_compound):
        data = _data(
            studio_compound.create_workflow(name="Fn Flow", steps=[{"name": "fs", "function_name": "score_check"}])
        )
        assert data["steps"] == ["fs"]

    def test_unknown_function_in_a_plain_step(self, studio_compound):
        error = _error(studio_compound.create_workflow(name="x", steps=[{"name": "fs", "function_name": "ghostfn"}]))
        assert error["code"] == "function_not_found"

    def test_unknown_evaluator_that_looks_like_a_name_is_refused(self, studio_compound):
        # An alphanumeric-ish value is a function reference, not a CEL
        # expression; a typo must not silently become CEL.
        error = _error(
            studio_compound.create_workflow(
                name="x",
                steps=[
                    {
                        "type": "loop",
                        "name": "l",
                        "steps": [{"name": "s", "agent_id": "w"}],
                        "end_condition_function": "ghostfn",
                    }
                ],
            )
        )
        assert error["code"] == "function_not_found"
        assert error["details"]["name"] == "ghostfn"

    def test_router_without_selector_is_refused(self, studio_compound):
        error = _error(
            studio_compound.create_workflow(
                name="x", steps=[{"type": "router", "name": "r", "choices": [{"name": "c", "agent_id": "w"}]}]
            )
        )
        assert error["code"] == "invalid_request"

    def test_condition_without_evaluator_is_refused(self, studio_compound):
        error = _error(
            studio_compound.create_workflow(
                name="x", steps=[{"type": "condition", "name": "c", "steps": [{"name": "s", "agent_id": "w"}]}]
            )
        )
        assert error["code"] == "invalid_request"

    def test_compound_step_with_an_executor_is_refused(self, studio_compound):
        error = _error(
            studio_compound.create_workflow(
                name="x",
                steps=[{"type": "parallel", "name": "p", "agent_id": "w", "steps": [{"name": "s", "agent_id": "w"}]}],
            )
        )
        assert error["code"] == "invalid_request"


class TestWorkflowStepSpecCoercion:
    """Direct Python callers pass plain dicts; they coerce through the same
    WorkflowStepSpec validation the framework applies to model tool calls."""

    @pytest.fixture
    def studio_workflows(self, registry, db):
        studio = StudioTools(registry=registry, db=db, workflows=True)
        studio.create_agent(name="a1", instructions="i", model_id="gpt-5.4", publish=True)
        return studio

    def test_two_executors_name_the_offending_index(self, studio_workflows):
        error = _error(
            studio_workflows.create_workflow(
                name="x",
                steps=[
                    {"name": "ok", "agent_id": "a1"},
                    {"name": "bad", "agent_id": "a1", "function_name": "fn"},
                ],
            )
        )
        assert error["code"] == "invalid_request"
        assert error["details"]["index"] == 1
        assert "exactly one" in error["message"]

    def test_unknown_step_type_is_refused(self, studio_workflows):
        error = _error(studio_workflows.create_workflow(name="x", steps=[{"type": "spiral", "name": "s"}]))
        assert error["code"] == "invalid_request"

    def test_invalid_nested_step_is_refused(self, studio_workflows):
        error = _error(
            studio_workflows.create_workflow(
                name="x", steps=[{"type": "parallel", "name": "p", "steps": [{"name": "empty"}]}]
            )
        )
        assert error["code"] == "invalid_request"

    def test_compound_without_nested_steps_is_refused(self, studio_workflows):
        error = _error(studio_workflows.create_workflow(name="x", steps=[{"type": "parallel", "name": "p"}]))
        assert error["code"] == "invalid_request"

    def test_spec_objects_are_accepted_directly(self, studio_workflows):
        data = _data(studio_workflows.create_workflow(name="typed", steps=[WorkflowStepSpec(name="s1", agent_id="a1")]))
        assert data["steps"] == ["s1"]


# ----------------------------------------------------------------------
# Edit: append-only drafts by default, immediate publish with versions=False
# ----------------------------------------------------------------------


class TestEditAgent:
    def _create(self, studio, publish=True):
        return _data(
            studio.create_agent(
                name="tutor", instructions="orig", model_id="gpt-5.4", tool_names=["calculator"], publish=publish
            )
        )

    def test_edit_produces_draft_v2(self, studio):
        self._create(studio)
        out = _loads(studio.edit_agent(agent_id="tutor", instructions="updated"))
        assert out["status"] == "edited"
        assert out["data"]["stage"] == "draft"
        assert out["data"]["draft_version"] == 2

    def test_second_edit_appends_a_new_draft(self, studio):
        # Append-only history (studio-3.0 spec section 3.2): the old in-place
        # draft reuse let two editors silently overwrite each other; now both
        # edits survive as versions and publish takes the latest by default.
        self._create(studio)
        studio.edit_agent(agent_id="tutor", instructions="updated once")
        data = _data(studio.edit_agent(agent_id="tutor", instructions="updated twice"))
        assert data["draft_version"] == 3

        versions = _data(studio.list_versions("tutor"))
        stages = [v["stage"] for v in versions["versions"]]
        assert stages.count("draft") == 2
        assert stages.count("published") == 1

    def test_successive_partial_edits_accumulate(self, studio):
        # A second edit must build on the pending draft, not reset to the
        # published config (which would silently discard the first edit).
        self._create(studio)
        studio.edit_agent(agent_id="tutor", instructions="new instructions")
        studio.edit_agent(agent_id="tutor", description="new description")

        latest = _data(studio.get_component("tutor"))
        assert latest["instructions"] == "new instructions"
        assert latest["description"] == "new description"

    def test_edit_turns_history_off_and_keeps_other_fields(self, studio):
        self._create(studio)
        out = _loads(studio.edit_agent(agent_id="tutor", add_history_to_context=False))
        assert out["status"] == "edited"

        got = _data(studio.get_component("tutor"))
        # to_dict omits the falsy flag, so the curated view drops the key.
        assert "add_history_to_context" not in got
        assert got["instructions"] == "orig"
        assert got["tools"] == ["calculator"]

    def test_edit_num_history_runs_only_keeps_history_on(self, studio):
        self._create(studio)
        studio.edit_agent(agent_id="tutor", num_history_runs=7)

        got = _data(studio.get_component("tutor"))
        assert got["add_history_to_context"] is True  # untouched from create
        assert got["num_history_runs"] == 7

    def test_edit_turns_datetime_off_and_keeps_other_fields(self, studio):
        self._create(studio)
        studio.edit_agent(agent_id="tutor", add_datetime_to_context=False)

        got = _data(studio.get_component("tutor"))
        assert "add_datetime_to_context" not in got
        assert got["instructions"] == "orig"
        assert got["tools"] == ["calculator"]

    def test_edit_unknown_agent_returns_component_not_found(self, studio):
        assert _error(studio.edit_agent(agent_id="ghost", instructions="x"))["code"] == "component_not_found"

    def test_edit_unknown_model_returns_model_not_found(self, studio):
        self._create(studio)
        assert _error(studio.edit_agent(agent_id="tutor", model_id="does-not-exist"))["code"] == "model_not_found"

    def test_edit_unknown_tool_returns_tool_not_found(self, studio):
        self._create(studio)
        assert _error(studio.edit_agent(agent_id="tutor", tool_names=["nonexistent"]))["code"] == "tool_not_found"


class TestEditRename:
    def test_rename_keeps_the_id_stable(self, studio):
        _data(studio.create_agent(name="Old Name", instructions="i", model_id="gpt-5.4", publish=True))
        data = _data(studio.edit_agent("old-name", name="New Name"))
        assert data["id"] == "old-name"

        got = _data(studio.get_component("old-name"))
        assert got["id"] == "old-name"
        assert got["name"] == "New Name"

    def test_listing_shows_the_new_name_only_after_publish(self, studio):
        _data(studio.create_agent(name="Old Name", instructions="i", model_id="gpt-5.4", publish=True))
        studio.edit_agent("old-name", name="New Name")

        def listed_name():
            rows = _data(studio.list_components(component_type="agent"))["components"]
            return next(r["name"] for r in rows if r["id"] == "old-name")

        assert listed_name() == "Old Name"
        _data(studio.publish_component("old-name"))
        assert listed_name() == "New Name"

    def test_the_new_display_name_resolves_after_publish(self, studio):
        _data(studio.create_agent(name="Old Name", instructions="i", model_id="gpt-5.4", publish=True))
        studio.edit_agent("old-name", name="New Name")
        studio.publish_component("old-name")
        assert _data(studio.get_component("New Name"))["id"] == "old-name"


class TestEditConcurrency:
    def test_expected_version_mismatch_is_a_retryable_conflict(self, studio):
        _data(studio.create_agent(name="cas", instructions="i", model_id="gpt-5.4", publish=True))
        _data(studio.edit_agent("cas", description="first"))  # latest is now 2

        error = _error(studio.edit_agent("cas", description="second", expected_version=1))
        assert error["code"] == "version_conflict"
        assert error["retryable"] is True
        assert error["details"]["latest_version"] == 2

    def test_matching_expected_version_passes(self, studio):
        _data(studio.create_agent(name="cas", instructions="i", model_id="gpt-5.4", publish=True))
        data = _data(studio.edit_agent("cas", description="first", expected_version=1))
        assert data["draft_version"] == 2
        data = _data(studio.edit_agent("cas", description="second", expected_version=2))
        assert data["draft_version"] == 3


class TestNoVersionSurface:
    def test_creates_publish_immediately_without_the_version_tools(self, registry, db):
        # versions=False removes publish_component from the surface, so a
        # draft would be strandable; creates go live immediately instead.
        studio = StudioTools(registry=registry, db=db, versions=False)
        out = _loads(studio.create_agent(name="No Ladder", instructions="hi", model_id="gpt-5.4"))
        assert out["ok"] and out["data"]["stage"] == "published", out
        assert db.get_component(out["data"]["id"])["current_version"] == 1
        assert "publish_component" not in studio.functions


class TestEditPublish:
    def test_edit_with_publish_goes_live_immediately(self, studio):
        _data(studio.create_agent(name="pub", instructions="i", model_id="gpt-5.4", publish=True))
        data = _data(studio.edit_agent("pub", description="live now", publish=True))
        assert data["version"] == 2
        assert data["stage"] == "published"

        got = _data(studio.get_component("pub"))
        assert got["version"] == 2
        assert got["is_current"] is True


class TestEditWithoutVersioning:
    """With versions=False, edits publish immediately -- no draft ladder."""

    def test_edit_publishes_immediately(self, studio_unversioned, db):
        studio_unversioned.create_agent(name="tutor", instructions="orig", model_id="gpt-5.4", publish=True)
        data = _data(studio_unversioned.edit_agent(agent_id="tutor", instructions="updated"))
        assert data["stage"] == "published"
        assert data["version"] == 2

        configs = db.list_configs("tutor")
        assert [c["stage"] for c in configs] == ["published", "published"]
        assert db.get_config("tutor")["version"] == 2

    def test_second_edit_creates_new_published_version(self, studio_unversioned, db):
        studio_unversioned.create_agent(name="tutor", instructions="orig", model_id="gpt-5.4", publish=True)
        studio_unversioned.edit_agent(agent_id="tutor", instructions="edit1")
        data = _data(studio_unversioned.edit_agent(agent_id="tutor", instructions="edit2"))
        assert data["version"] == 3
        assert db.get_config("tutor")["version"] == 3


class TestEditTeam:
    @pytest.fixture
    def studio_teams(self, registry, db):
        return StudioTools(registry=registry, db=db, teams=True)

    def _setup(self, studio_teams):
        studio_teams.create_agent(name="a1", instructions="i", model_id="gpt-5.4", publish=True)
        studio_teams.create_agent(name="a2", instructions="i", model_id="gpt-5.4", publish=True)
        studio_teams.create_team(name="squad", instructions="orig", member_ids=["a1"], model_id="gpt-5.4", publish=True)

    def test_edit_team_members_appends_a_draft(self, studio_teams):
        self._setup(studio_teams)
        data = _data(studio_teams.edit_team(team_id="squad", member_ids=["a1", "a2"]))
        assert data["stage"] == "draft"
        assert _data(studio_teams.get_component("squad"))["member_ids"] == ["a1", "a2"]

    def test_edit_team_missing_member_returns_component_not_found(self, studio_teams):
        self._setup(studio_teams)
        assert _error(studio_teams.edit_team(team_id="squad", member_ids=["ghost"]))["code"] == "component_not_found"

    def test_edit_team_empty_members_is_refused(self, studio_teams):
        self._setup(studio_teams)
        assert _error(studio_teams.edit_team(team_id="squad", member_ids=[]))["code"] == "invalid_request"

    def test_edit_turns_history_off_and_keeps_other_fields(self, studio_teams):
        self._setup(studio_teams)
        out = _loads(studio_teams.edit_team(team_id="squad", add_history_to_context=False))
        assert out["status"] == "edited"

        got = _data(studio_teams.get_component("squad"))
        assert "add_history_to_context" not in got
        assert got["instructions"] == "orig"
        assert got["member_ids"] == ["a1"]

    def test_edit_num_history_runs_only_keeps_history_on(self, studio_teams):
        self._setup(studio_teams)
        studio_teams.edit_team(team_id="squad", num_history_runs=7)

        got = _data(studio_teams.get_component("squad"))
        assert got["add_history_to_context"] is True  # untouched from create
        assert got["num_history_runs"] == 7

    def test_edit_mode_round_trips(self, studio_teams):
        self._setup(studio_teams)
        studio_teams.edit_team(team_id="squad", mode="broadcast")
        assert _data(studio_teams.get_component("squad"))["mode"] == "broadcast"

    @pytest.mark.asyncio
    async def test_async_edit_team_datetime_off(self, studio_teams):
        self._setup(studio_teams)
        out = _loads(await studio_teams.aedit_team(team_id="squad", add_datetime_to_context=False))
        assert out["status"] == "edited"
        assert "add_datetime_to_context" not in _data(studio_teams.get_component("squad"))


class TestEditWorkflow:
    @pytest.fixture
    def studio_workflows(self, registry, db):
        return StudioTools(registry=registry, db=db, workflows=True)

    def _setup(self, studio_workflows):
        studio_workflows.create_agent(name="a1", instructions="i", model_id="gpt-5.4", publish=True)
        studio_workflows.create_agent(name="a2", instructions="i", model_id="gpt-5.4", publish=True)
        studio_workflows.create_workflow(
            name="pipeline", description="orig", steps=[{"name": "s1", "agent_id": "a1"}], publish=True
        )

    def test_edit_workflow_description_produces_a_draft(self, studio_workflows):
        self._setup(studio_workflows)
        data = _data(studio_workflows.edit_workflow(workflow_id="pipeline", description="updated"))
        assert data["stage"] == "draft"
        assert data["draft_version"] == 2
        assert _data(studio_workflows.get_component("pipeline"))["description"] == "updated"

    def test_edit_workflow_replaces_steps(self, studio_workflows):
        self._setup(studio_workflows)
        _data(studio_workflows.edit_workflow(workflow_id="pipeline", steps=[{"name": "s2", "agent_id": "a2"}]))
        view = _data(studio_workflows.get_component("pipeline"))
        assert [s["name"] for s in view["steps"]] == ["s2"]

    def test_edit_workflow_bad_step_is_refused(self, studio_workflows):
        self._setup(studio_workflows)
        error = _error(
            studio_workflows.edit_workflow(workflow_id="pipeline", steps=[{"name": "s1", "agent_id": "ghost"}])
        )
        assert error["code"] == "component_not_found"


# ----------------------------------------------------------------------
# Coverage fields: the create/edit surface round-trips through get_component
# ----------------------------------------------------------------------


class TestCoverageFields:
    @pytest.fixture
    def studio_refs(self, registry, db):
        from pydantic import BaseModel

        class Report(BaseModel):
            text: str

        class FakeKnowledge:
            name = "handbook"

        registry.add_schema(Report)
        registry.add_knowledge(FakeKnowledge())
        return StudioTools(registry=registry, db=db)

    def test_text_and_flag_fields_round_trip(self, studio_refs):
        _data(
            studio_refs.create_agent(
                name="rich",
                instructions="i",
                model_id="gpt-5.4",
                role="analyst",
                markdown=True,
                expected_output="a table",
                additional_context="extra context",
                tool_call_limit=5,
            )
        )
        got = _data(studio_refs.get_component("rich"))
        assert got["role"] == "analyst"
        assert got["markdown"] is True
        assert got["expected_output"] == "a table"
        assert got["additional_context"] == "extra context"
        assert got["tool_call_limit"] == 5

    def test_empty_string_clears_a_text_field(self, studio_refs):
        _data(studio_refs.create_agent(name="rich", instructions="i", model_id="gpt-5.4", role="analyst"))
        _data(studio_refs.edit_agent("rich", role=""))
        assert "role" not in _data(studio_refs.get_component("rich"))

    def test_zero_clears_the_tool_call_limit(self, studio_refs):
        _data(studio_refs.create_agent(name="rich", instructions="i", model_id="gpt-5.4", tool_call_limit=5))
        _data(studio_refs.edit_agent("rich", tool_call_limit=0))
        assert "tool_call_limit" not in _data(studio_refs.get_component("rich"))

    def test_empty_list_clears_the_tools(self, studio_refs):
        _data(studio_refs.create_agent(name="tooled", instructions="i", model_id="gpt-5.4", tool_names=["calculator"]))
        assert _data(studio_refs.get_component("tooled"))["tools"] == ["calculator"]
        _data(studio_refs.edit_agent("tooled", tool_names=[]))
        assert _data(studio_refs.get_component("tooled"))["tools"] == []

    def test_omitted_fields_keep_their_stored_values(self, studio_refs):
        _data(studio_refs.create_agent(name="keep", instructions="i", model_id="gpt-5.4", role="analyst"))
        _data(studio_refs.edit_agent("keep", description="only this"))
        got = _data(studio_refs.get_component("keep"))
        assert got["role"] == "analyst"
        assert got["description"] == "only this"

    def test_knowledge_attaches_and_detaches(self, studio_refs):
        _data(studio_refs.create_agent(name="kb", instructions="i", model_id="gpt-5.4", knowledge_name="handbook"))
        assert _data(studio_refs.get_component("kb"))["knowledge_name"] == "handbook"

        _data(studio_refs.edit_agent("kb", knowledge_name=""))
        assert "knowledge_name" not in _data(studio_refs.get_component("kb"))

        _data(studio_refs.edit_agent("kb", knowledge_name="handbook"))
        assert _data(studio_refs.get_component("kb"))["knowledge_name"] == "handbook"

    def test_output_schema_attaches_and_detaches(self, studio_refs):
        _data(
            studio_refs.create_agent(name="shaped", instructions="i", model_id="gpt-5.4", output_schema_name="Report")
        )
        assert _data(studio_refs.get_component("shaped"))["output_schema_name"] == "Report"

        _data(studio_refs.edit_agent("shaped", output_schema_name=""))
        assert "output_schema_name" not in _data(studio_refs.get_component("shaped"))

    def test_reasoning_model_attaches_and_detaches(self, studio_refs):
        _data(
            studio_refs.create_agent(name="thinker", instructions="i", model_id="gpt-5.4", reasoning_model_id="gpt-5.5")
        )
        assert _data(studio_refs.get_component("thinker"))["reasoning_model_id"] == "gpt-5.5"

        _data(studio_refs.edit_agent("thinker", reasoning_model_id=""))
        assert "reasoning_model_id" not in _data(studio_refs.get_component("thinker"))

    def test_enable_agentic_memory_round_trips(self, studio_refs):
        _data(studio_refs.create_agent(name="mem", instructions="i", model_id="gpt-5.4", enable_agentic_memory=True))
        assert _data(studio_refs.get_component("mem"))["enable_agentic_memory"] is True

    def test_metadata_round_trips(self, studio_refs):
        _data(studio_refs.create_agent(name="meta", instructions="i", model_id="gpt-5.4", metadata={"team": "growth"}))
        assert _data(studio_refs.get_component("meta"))["metadata"] == {"team": "growth"}

    def test_unknown_knowledge_returns_knowledge_not_found(self, studio_refs):
        error = _error(studio_refs.create_agent(name="x", instructions="i", model_id="gpt-5.4", knowledge_name="ghost"))
        assert error["code"] == "knowledge_not_found"

    def test_unknown_schema_returns_schema_not_found(self, studio_refs):
        error = _error(
            studio_refs.create_agent(name="x", instructions="i", model_id="gpt-5.4", output_schema_name="Ghost")
        )
        assert error["code"] == "schema_not_found"

    def test_unknown_memory_manager_returns_memory_manager_not_found(self, studio_refs):
        error = _error(
            studio_refs.create_agent(name="x", instructions="i", model_id="gpt-5.4", memory_manager_id="ghost")
        )
        assert error["code"] == "memory_manager_not_found"

    def test_unknown_reasoning_model_returns_model_not_found(self, studio_refs):
        error = _error(
            studio_refs.create_agent(name="x", instructions="i", model_id="gpt-5.4", reasoning_model_id="ghost")
        )
        assert error["code"] == "model_not_found"


# ----------------------------------------------------------------------
# Versioning
# ----------------------------------------------------------------------


class TestVersioning:
    def _create_and_edit(self, studio):
        studio.create_agent(
            name="tutor", instructions="orig", model_id="gpt-5.4", tool_names=["calculator"], publish=True
        )
        studio.edit_agent(agent_id="tutor", instructions="updated")

    def test_list_versions_returns_both(self, studio):
        self._create_and_edit(studio)
        data = _data(studio.list_versions("tutor"))
        assert data["count"] == 2
        stages = sorted(v["stage"] for v in data["versions"])
        assert stages == ["draft", "published"]

    def test_get_component_reads_an_exact_version(self, studio):
        self._create_and_edit(studio)
        pinned = _data(studio.get_component("tutor", version=1))
        assert pinned["version"] == 1
        assert pinned["stage"] == "published"
        assert pinned["is_current"] is True
        assert pinned["instructions"] == "orig"

    def test_get_component_default_is_the_latest_version(self, studio):
        # The latest version is what you just edited -- the draft, not the
        # live pointer. The live pointer travels alongside as current_version.
        self._create_and_edit(studio)
        latest = _data(studio.get_component("tutor"))
        assert latest["version"] == 2
        assert latest["stage"] == "draft"
        assert latest["is_current"] is False
        assert latest["current_version"] == 1
        assert latest["latest_version"] == 2

    def test_unknown_version_returns_version_not_found(self, studio):
        self._create_and_edit(studio)
        assert _error(studio.get_component("tutor", version=99))["code"] == "version_not_found"

    def test_list_versions_marks_current(self, studio):
        self._create_and_edit(studio)
        by_version = {v["version"]: v for v in _data(studio.list_versions("tutor"))["versions"]}
        assert by_version[1]["is_current"] is True
        assert by_version[2]["is_current"] is False

        studio.publish_component("tutor")
        by_version = {v["version"]: v for v in _data(studio.list_versions("tutor"))["versions"]}
        assert by_version[2]["is_current"] is True
        assert by_version[1]["is_current"] is False

    def test_draft_metadata_not_visible_until_publish(self, studio, db):
        studio.create_agent(name="tutor", instructions="i", model_id="gpt-5.4", description="original", publish=True)
        studio.edit_agent(agent_id="tutor", description="draft-only")
        assert db.get_component("tutor")["description"] == "original"

        studio.publish_component("tutor")
        assert db.get_component("tutor")["description"] == "draft-only"

    def test_publish_promotes_draft_to_current(self, studio):
        self._create_and_edit(studio)
        data = _data(studio.publish_component("tutor"))
        assert data["version"] == 2

        versions = _data(studio.list_versions("tutor"))
        stages = [v["stage"] for v in versions["versions"]]
        assert stages.count("published") == 2
        assert stages.count("draft") == 0

    def test_publish_already_published_version_is_noop(self, studio):
        self._create_and_edit(studio)
        studio.publish_component("tutor")  # draft v2 -> published

        # Re-publishing the same (now published) version must not raise the db's
        # "Cannot update published config" error; it is an idempotent no-op.
        out = _loads(studio.publish_component("tutor", version=2))
        assert out["status"] == "already_published"
        assert out["data"]["version"] == 2

    def test_publish_unknown_version_returns_version_not_found(self, studio):
        studio.create_agent(name="tutor", instructions="i", model_id="gpt-5.4", publish=True)
        assert _error(studio.publish_component("tutor", version=99))["code"] == "version_not_found"

    def test_publish_without_draft_returns_invalid_request(self, studio):
        studio.create_agent(name="tutor", instructions="i", model_id="gpt-5.4", publish=True)
        assert _error(studio.publish_component("tutor"))["code"] == "invalid_request"

    def test_publish_cas_guards_the_live_pointer(self, studio):
        self._create_and_edit(studio)
        error = _error(studio.publish_component("tutor", expected_current_version=7))
        assert error["code"] == "version_conflict"
        assert error["retryable"] is True
        assert error["details"]["current_version"] == 1

        data = _data(studio.publish_component("tutor", expected_current_version=1))
        assert data["version"] == 2

    def test_set_current_version_rollback(self, studio):
        self._create_and_edit(studio)
        studio.publish_component("tutor")  # v2 published & current
        out = _loads(studio.set_current_version("tutor", 1))
        assert out["status"] == "set_current"
        assert out["data"]["version"] == 1

    def test_set_current_unknown_version_returns_version_not_found(self, studio):
        self._create_and_edit(studio)
        assert _error(studio.set_current_version("tutor", 9))["code"] == "version_not_found"

    def test_delete_draft_version(self, studio):
        self._create_and_edit(studio)
        out = _loads(studio.delete_version("tutor", 2))
        assert out["status"] == "deleted"

        versions = _data(studio.list_versions("tutor"))
        assert versions["count"] == 1
        assert versions["versions"][0]["version"] == 1

    def test_delete_published_version_is_refused(self, studio):
        self._create_and_edit(studio)
        # v1 is published+current: history is immutable.
        error = _error(studio.delete_version("tutor", 1))
        assert error["code"] == "invalid_request"


# ----------------------------------------------------------------------
# Validation (dry-run rebuild)
# ----------------------------------------------------------------------


class TestValidateComponent:
    def test_valid_component_reports_valid(self, studio):
        studio.create_agent(name="clean", instructions="i", model_id="gpt-5.4", tool_names=["calculator"])
        data = _data(studio.validate_component("clean"))
        assert data["valid"] is True
        assert data["version"] == 1
        assert data["stage"] == "draft"

    def test_validate_an_exact_version(self, studio):
        studio.create_agent(name="clean", instructions="i", model_id="gpt-5.4", publish=True)
        studio.edit_agent("clean", description="draft change")
        data = _data(studio.validate_component("clean", version=2))
        assert data["valid"] is True
        assert data["version"] == 2

    def test_missing_registry_tool_fails_validation(self, registry, db):
        # Build against the full registry, validate against one that lost the
        # toolkit: the stored config references tools the rebuild cannot bind.
        full = StudioTools(registry=registry, db=db)
        full.create_agent(name="armed", instructions="i", model_id="gpt-5.4", tool_names=["calculator"])

        partial_registry = Registry(name="Partial", models=[OpenAIResponses(id="gpt-5.4")], dbs=[db])
        partial = StudioTools(registry=partial_registry, db=db)
        error = _error(partial.validate_component("armed"))
        assert error["code"] == "validation_failed"

    def test_unknown_component_returns_component_not_found(self, studio):
        assert _error(studio.validate_component("ghost"))["code"] == "component_not_found"

    def test_unknown_version_returns_version_not_found(self, studio):
        studio.create_agent(name="clean", instructions="i", model_id="gpt-5.4")
        assert _error(studio.validate_component("clean", version=9))["code"] == "version_not_found"


# ----------------------------------------------------------------------
# Schedules: component-aware schedule tools with schedules=True
# ----------------------------------------------------------------------


@pytest.mark.skipif(
    find_spec("croniter") is None or find_spec("pytz") is None,
    reason="scheduler extras not installed (pip install agno[scheduler])",
)
class TestSchedules:
    def _create_target_agent(self, studio, name="digest"):
        return _data(studio.create_agent(name=name, instructions="i", model_id="gpt-5.4", publish=True))

    def _create_schedule(self, studio, **overrides):
        params = {
            "name": "daily-digest",
            "cron": "0 9 * * *",
            "target_type": "agent",
            "target_id": "digest",
            "message": "Send the daily digest.",
        }
        params.update(overrides)
        out = _loads(studio.create_schedule(**params))
        if out.get("ok"):
            return {"status": out["status"], **out["data"]}
        return out

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
        assert out["error"]["code"] == "component_not_found"
        assert "Agent not found: ghost" in out["error"]["message"]

    def test_bad_target_type_returns_error(self, studio_schedules):
        self._create_target_agent(studio_schedules)
        out = self._create_schedule(studio_schedules, target_type="cron-job")
        assert out["error"]["code"] == "component_not_found"
        assert "Invalid target_type" in out["error"]["message"]

    def test_invalid_cron_returns_error(self, studio_schedules):
        self._create_target_agent(studio_schedules)
        out = self._create_schedule(studio_schedules, cron="not-a-cron")
        assert out["error"]["code"] == "invalid_request"
        assert "Invalid cron expression" in out["error"]["message"]

    def test_invalid_timezone_returns_error(self, studio_schedules):
        self._create_target_agent(studio_schedules)
        out = self._create_schedule(studio_schedules, timezone="Mars/Olympus")
        assert out["error"]["code"] == "invalid_request"
        assert "Invalid timezone" in out["error"]["message"]

    def test_empty_message_returns_error(self, studio_schedules):
        self._create_target_agent(studio_schedules)
        out = self._create_schedule(studio_schedules, message="   ")
        assert out["error"]["code"] == "invalid_request"
        assert "message" in out["error"]["message"]

    def test_same_name_create_is_a_conflict_and_update_changes_cadence(self, studio_schedules):
        # Create means create (studio-3.0 spec section 3.5): a reused name can
        # no longer silently repoint an existing schedule; update_schedule is
        # the explicit edit path and the target stays immutable.
        self._create_target_agent(studio_schedules)
        first = self._create_schedule(studio_schedules)
        second = self._create_schedule(studio_schedules, cron="30 18 * * *")

        assert second["error"]["code"] == "schedule_conflict"
        assert "update_schedule" in second["error"]["message"]

        updated = _loads(studio_schedules.update_schedule(first["id"], cron="30 18 * * *"))
        assert updated["ok"] and updated["data"]["cron"] == "30 18 * * *"

        listed = _loads(_tool(studio_schedules, "list_schedules")())
        assert listed["count"] == 1
        assert listed["schedules"][0]["cron"] == "30 18 * * *"

    def test_update_schedule_changes_message_and_stamps_provenance(self, studio_schedules, db):
        self._create_target_agent(studio_schedules)
        created = self._create_schedule(studio_schedules)
        out = _loads(studio_schedules.update_schedule(created["id"], message="New prompt."))
        assert out["ok"], out
        row = db.get_schedule(created["id"])
        assert row["payload"] == {"message": "New prompt."}

    def test_update_schedule_requires_a_field(self, studio_schedules):
        self._create_target_agent(studio_schedules)
        created = self._create_schedule(studio_schedules)
        out = _loads(studio_schedules.update_schedule(created["id"]))
        assert out["error"]["code"] == "invalid_request"

    def test_schedule_refuses_a_draft_only_target(self, studio_schedules):
        # A schedule fires the live published version; a draft target would
        # 404 on every tick.
        _data(studio_schedules.create_agent(name="draft-target", instructions="i", model_id="gpt-5.4"))
        out = self._create_schedule(studio_schedules, target_id="draft-target")
        assert out["error"]["code"] == "target_not_published"

    def test_create_stamps_studio_provenance(self, studio_schedules, db):
        self._create_target_agent(studio_schedules)
        created = self._create_schedule(studio_schedules)
        row = db.get_schedule(created["id"])
        assert row["managed_by"] == "studio"
        assert row["target_type"] == "agent" and row["target_id"] == "digest"

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
        assert out["data"]["endpoint"] == "/agents/digest/runs"

    def test_archive_cascade_disables_schedules_and_warns(self, studio_schedules, db):
        # Archiving a component must not leave live schedules firing at a 404;
        # the archive result carries the count so the model can relay it.
        self._create_target_agent(studio_schedules)
        created = self._create_schedule(studio_schedules)

        archived = _loads(studio_schedules.archive_component("digest"))
        assert archived["ok"], archived
        assert any("1 schedule" in w for w in archived["warnings"]), archived["warnings"]

        row = db.get_schedule(created["id"])
        assert row["enabled"] in (False, 0)
        assert row["disabled_reason"] == "target_archived:agent:digest"

    def test_enable_refuses_schedule_whose_target_is_archived(self, studio_schedules):
        self._create_target_agent(studio_schedules)
        created = self._create_schedule(studio_schedules)
        studio_schedules.archive_component("digest")

        out = _loads(_tool(studio_schedules, "enable_schedule")(created["id"]))
        assert "archived" in out["error"]
        assert "Restore" in out["error"]

        # Restoring the target makes enable work again.
        restored = _loads(studio_schedules.restore_component("digest"))
        assert restored["ok"], restored
        enabled = _loads(_tool(studio_schedules, "enable_schedule")(created["id"]))
        assert enabled["status"] == "enabled"


# ----------------------------------------------------------------------
# Archive / restore (deletion is not offered; archive is terminal)
# ----------------------------------------------------------------------


class TestArchive:
    def test_archive_retires_the_component(self, studio, db):
        studio.create_agent(name="temp", instructions="i", model_id="gpt-5.4", publish=True)
        out = _loads(studio.archive_component("temp"))
        assert out["status"] == "archived"
        assert db.get_component("temp") is None
        assert db.get_component("temp", include_deleted=True) is not None

    def test_restore_reverses_the_archive(self, studio, db):
        studio.create_agent(name="temp", instructions="i", model_id="gpt-5.4", publish=True)
        studio.archive_component("temp")
        out = _loads(studio.restore_component("temp"))
        assert out["status"] == "restored"
        assert db.get_component("temp") is not None
        assert _data(studio.get_component("temp"))["id"] == "temp"

    def test_archive_unknown_component_returns_component_not_found(self, studio):
        assert _error(studio.archive_component("ghost"))["code"] == "component_not_found"

    def test_archive_by_display_name_is_refused_naming_the_exact_id(self, studio):
        studio.create_agent(name="Radar Scout", instructions="i", model_id="gpt-5.4", publish=True)
        error = _error(studio.archive_component("Radar Scout"))
        assert error["code"] == "invalid_request"
        assert "radar-scout" in error["message"]
        assert _loads(studio.archive_component("radar-scout"))["status"] == "archived"

    def test_archive_refuses_while_a_dependent_pins_the_component(self, registry, db):
        tool = StudioTools(registry=registry, db=db, teams=True)
        tool.create_agent(name="member", instructions="i", model_id="gpt-5.4", publish=True)
        tool.create_team(name="crew", instructions="i", member_ids=["member"], model_id="gpt-5.4", publish=True)

        error = _error(tool.archive_component("member"))
        assert error["code"] == "dependency_conflict"
        assert "crew" in error["message"]

        assert _loads(tool.archive_component("crew"))["status"] == "archived"
        assert _loads(tool.archive_component("member"))["status"] == "archived"

    def test_archiving_an_archived_component_reports_already_archived(self, studio):
        studio.create_agent(name="temp", instructions="i", model_id="gpt-5.4", publish=True)
        studio.archive_component("temp")
        assert _loads(studio.archive_component("temp"))["status"] == "already_archived"

    def test_restore_of_a_live_component_is_refused(self, studio):
        studio.create_agent(name="temp", instructions="i", model_id="gpt-5.4", publish=True)
        assert _error(studio.restore_component("temp"))["code"] == "invalid_request"

    def test_restore_unknown_component_returns_component_not_found(self, studio):
        assert _error(studio.restore_component("ghost"))["code"] == "component_not_found"

    def test_archive_targets_the_db_row_when_a_live_agent_shadows_the_id(self, registry, db):
        studio = StudioTools(registry=registry, db=db)
        studio.create_agent(name="temp", instructions="i", model_id="gpt-5.4", publish=True)

        class ShadowAgent:
            id = "temp"
            name = "temp"

            def delete(self, **kwargs):
                raise AssertionError("archive_component should not call delete() on live agents")

        tool = StudioTools(registry=registry, db=db, agents_list=[ShadowAgent()])

        out = _loads(tool.archive_component("temp"))
        assert out["status"] == "archived"
        assert db.get_component("temp") is None


# ----------------------------------------------------------------------
# Lookup priority
# ----------------------------------------------------------------------


class TestLookup:
    def test_find_agent_finds_just_created_draft_via_db(self, studio):
        # A draft is not dispatchable, but it IS readable: the read lookup
        # reaches it without a publish.
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
        studio.create_agent(name="persisted", instructions="i", model_id="gpt-5.4", publish=True)
        fresh = StudioTools(registry=registry, db=db)
        found = fresh._find_agent("persisted")
        assert found is not None
        assert found.id == "persisted"

    def test_edit_code_defined_agent_is_rejected(self, studio, registry, db):
        # A code-defined (live) agent shadows any DB row at lookup time, so editing
        # it would write an unreachable draft. edit_* must reject it instead of
        # silently returning "edited".
        studio.create_agent(name="shared", instructions="db", model_id="gpt-5.4", publish=True)
        live = Agent(id="shared", name="Shared", model=OpenAIResponses(id="gpt-5.4"), instructions="live")
        tool = StudioTools(registry=registry, db=db, agents_list=[live])

        error = _error(tool.edit_agent(agent_id="shared", instructions="updated-live"))

        assert error["code"] == "invalid_request"
        assert "code-defined" in error["message"]
        assert live.instructions == "live"


# ----------------------------------------------------------------------
# Type guards and the exactness of the tools view
# ----------------------------------------------------------------------


class TestTypeGuards:
    def _full(self, registry, db):
        return StudioTools(registry=registry, db=db, teams=True, workflows=True)

    def test_get_component_reads_any_type(self, registry, db):
        tool = self._full(registry, db)
        tool.create_agent(name="member", instructions="i", model_id="gpt-5.4", publish=True)
        tool.create_team(name="squad", instructions="i", member_ids=["member"], model_id="gpt-5.4")

        assert _data(tool.get_component("squad"))["component_type"] == "team"
        assert _data(tool.get_component("member"))["component_type"] == "agent"

    def test_run_agent_rejects_team_id(self, registry, db):
        tool = self._full(registry, db)
        tool.create_agent(name="member", instructions="i", model_id="gpt-5.4", publish=True)
        tool.create_team(name="squad", instructions="i", member_ids=["member"], model_id="gpt-5.4", publish=True)

        out = _loads(_tool(tool, "run_agent")("squad", message="hi"))
        assert "error" in out

    def test_team_member_rejects_workflow_id(self, registry, db):
        tool = self._full(registry, db)
        tool.create_agent(name="a1", instructions="i", model_id="gpt-5.4", publish=True)
        tool.create_workflow(name="flow", steps=[{"name": "s1", "agent_id": "a1"}])

        # A workflow id is neither an agent nor a team, so it cannot be a member.
        error = _error(tool.create_team(name="squad", instructions="i", member_ids=["flow"], model_id="gpt-5.4"))
        assert error["code"] == "component_not_found"
        assert "flow" in error["message"]

    def test_workflow_step_agent_id_rejects_team_id(self, registry, db):
        tool = self._full(registry, db)
        tool.create_agent(name="member", instructions="i", model_id="gpt-5.4", publish=True)
        tool.create_team(name="squad", instructions="i", member_ids=["member"], model_id="gpt-5.4")

        # 'squad' is a team, so an agent_id step pointing at it must error.
        error = _error(tool.create_workflow(name="flow", steps=[{"name": "s1", "agent_id": "squad"}]))
        assert error["code"] == "component_not_found"

    def test_tools_view_is_exact(self, registry, db):
        tool = self._full(registry, db)
        tool.create_agent(name="whole", instructions="i", model_id="gpt-5.4", tool_names=["calculator"])
        tool.create_agent(name="partial", instructions="i", model_id="gpt-5.4", tool_names=["add"])

        # A complete toolkit selection collapses to the toolkit name; a single
        # attached function stays that function -- the read-then-edit loop can
        # never silently widen a selection to the whole toolkit.
        assert _data(tool.get_component("whole"))["tools"] == ["calculator"]
        assert _data(tool.get_component("partial"))["tools"] == ["add"]

    def test_ambiguous_display_name_returns_candidates(self, studio):
        studio.create_agent(name="Twin", instructions="i", model_id="gpt-5.4")
        studio.create_agent(name="Twin", instructions="i", model_id="gpt-5.4", component_id="twin-2")

        error = _error(studio.get_component("Twin"))
        assert error["code"] == "ambiguous_reference"
        assert set(error["details"]["candidates"]) == {"twin", "twin-2"}


# ----------------------------------------------------------------------
# Run previews (owner-gated exact-version dispatch)
# ----------------------------------------------------------------------


class TestRunPreviewGates:
    def test_preview_of_a_missing_version_returns_version_not_found(self, studio):
        studio.create_agent(name="draft-bot", instructions="i", model_id="gpt-5.4")
        assert _error(studio.run_agent("draft-bot", "hi", version=9))["code"] == "version_not_found"

    def test_another_owner_cannot_preview_a_draft(self, studio):
        from agno.run.base import RunContext

        alice = RunContext(run_id="r1", session_id="s1", user_id="alice")
        bob = RunContext(run_id="r2", session_id="s2", user_id="bob")
        studio.create_agent(name="private-draft", instructions="i", model_id="gpt-5.4", _agno_run_context=alice)

        error = _error(studio.run_agent("private-draft", "hi", version=1, _agno_run_context=bob))
        assert error["code"] == "component_not_found"


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
        assert "create_team" in set(tool.functions.keys())

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
        assert DISCOVERY_TOOLS.issubset(set(tool.functions.keys()))


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

        tool.create_agent(name="studio-agent", instructions="i", model_id="gpt-5.4", publish=True)
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

        tool.create_workflow(name="wf", steps=[{"name": "s1", "agent_id": "greeter-code"}])
        assert db.get_component("wf") is not None
        assert db.get_component("greeter-code") is None


# ----------------------------------------------------------------------
# Integration: whole lifecycle in order
# ----------------------------------------------------------------------


class TestLifecycle:
    def test_full_lifecycle(self, studio, db):
        # Create a draft, publish it
        data = _data(studio.create_agent(name="lc", instructions="orig", model_id="gpt-5.4", tool_names=["calculator"]))
        assert data["version"] == 1
        assert data["stage"] == "draft"
        assert _data(studio.validate_component("lc"))["valid"] is True
        assert _data(studio.publish_component("lc"))["version"] == 1

        # Edit twice -- append-only history keeps both drafts
        studio.edit_agent(agent_id="lc", instructions="edit1")
        studio.edit_agent(agent_id="lc", instructions="edit2")
        assert len(_data(studio.list_versions("lc"))["versions"]) == 3

        # Publish promotes the latest draft
        assert _data(studio.publish_component("lc"))["version"] == 3

        # Rollback
        assert _loads(studio.set_current_version("lc", 1))["status"] == "set_current"

        # Archive, then restore
        assert _loads(studio.archive_component("lc"))["status"] == "archived"
        assert db.get_component("lc") is None
        assert _loads(studio.restore_component("lc"))["status"] == "restored"
        assert db.get_component("lc") is not None


def test_studio_loads_component_with_broken_refs_for_repair(tmp_path):
    """StudioTools read/edit paths load leniently: a component whose registry
    references are broken must still load so an edit can repair it."""
    db = SqliteDb(db_file=str(tmp_path / "studio_repair.db"))

    def search(query: str) -> str:
        """Search for a query."""
        return f"results for {query}"

    agent = Agent(id="repair-agent", name="Repair Agent", model=OpenAIResponses(id="gpt-5.5"), tools=[search])
    agent.save(db=db)

    # Registry lacks the tool the saved agent references
    studio = StudioTools(registry=Registry(), db=db)
    loaded = studio._load_agent_from_db("repair-agent")

    assert loaded is not None
    assert loaded.id == "repair-agent"


def _edit_version(out: Dict[str, Any]) -> int:
    """The version an edit produced, draft or published."""
    data = out["data"]
    return data.get("version") or data.get("draft_version")


class TestEditPreservation:
    """Edits round-trip through leniently loaded objects; the persisted config
    must not lose what the load could not resolve, nor its member pins."""

    def test_description_edit_preserves_unresolved_output_schema(self, tmp_path):
        from pydantic import BaseModel

        class Report(BaseModel):
            text: str

        db = SqliteDb(db_file=str(tmp_path / "preserve.db"))
        Agent(id="schema-agent", name="S", model=OpenAIResponses(id="gpt-5.5"), output_schema=Report).save(db=db)

        studio = StudioTools(registry=Registry(), db=db)
        out = _loads(studio.edit_agent("schema-agent", description="edited"))
        assert out.get("status") == "edited"

        row = db.get_config(component_id="schema-agent", version=_edit_version(out))
        assert row["config"]["output_schema"] == "Report"
        assert row["config"]["description"] == "edited"

    def test_team_edit_repins_members(self, tmp_path):
        from agno.team.team import Team

        db = SqliteDb(db_file=str(tmp_path / "repin_team.db"))
        member = Agent(id="rp-member", name="Member")
        Team(id="rp-team", name="Team", members=[member]).save(db=db)

        studio = StudioTools(registry=Registry(), db=db, teams=True)
        out = _loads(studio.edit_team("rp-team", description="edited"))
        assert out.get("status") == "edited"

        links = db.get_links(component_id="rp-team", version=_edit_version(out))
        assert [link["child_component_id"] for link in links] == ["rp-member"]
        assert all(link["child_version"] is not None for link in links)

    def test_workflow_edit_repins_step_members(self, tmp_path):
        from agno.workflow.step import Step
        from agno.workflow.workflow import Workflow

        db = SqliteDb(db_file=str(tmp_path / "repin_wf.db"))
        agent = Agent(id="rw-agent", name="A")
        Workflow(id="rw-wf", name="WF", steps=[Step(name="s1", agent=agent)]).save(db=db)

        studio = StudioTools(registry=Registry(), db=db, workflows=True)
        out = _loads(studio.edit_workflow("rw-wf", description="edited"))
        assert out.get("status") == "edited"

        links = db.get_links(component_id="rw-wf", version=_edit_version(out))
        assert "rw-agent" in [link["child_component_id"] for link in links]


class TestSnapshotSafety:
    def test_create_team_pins_members_at_creation(self, tmp_path):
        db = SqliteDb(db_file=str(tmp_path / "create_pin.db"))
        Agent(id="cp-member", name="Member").save(db=db)
        model = OpenAIResponses(id="gpt-5.5")
        studio = StudioTools(registry=Registry(models=[model], dbs=[db]), db=db, teams=True)

        data = _data(studio.create_team(name="CP Crew", instructions="i", member_ids=["cp-member"], model_id="gpt-5.5"))

        links = db.get_links(component_id=data["id"], version=1)
        assert [link["child_component_id"] for link in links] == ["cp-member"]

    def test_unrelated_edit_carries_base_pins_forward(self, tmp_path):
        from agno.team.team import Team

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

        links = db.get_links(component_id="cf-team", version=_edit_version(out))
        assert [link["child_version"] for link in links if link["link_kind"] == "member"] == [base_pin]

    def test_unrelated_edit_keeps_the_stored_db_reference(self, tmp_path):
        from agno.db.base import ComponentType

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

        row = db.get_config(component_id="opaque-agent", version=_edit_version(out))
        assert row["config"]["db"] == stored_db
        assert row["config"]["description"] == "edited"


class TestEditIdentityStability:
    def test_description_edit_keeps_step_ids_and_per_step_pins(self, tmp_path):
        """An unrelated edit must not re-mint step_ids: carried-forward link
        keys name steps by step_id, so churn orphans every pin."""
        from agno.workflow.step import Step
        from agno.workflow.workflow import Workflow

        db = SqliteDb(db_file=str(tmp_path / "stepid.db"))
        agent = Agent(id="si-agent", name="A")
        Workflow(id="si-wf", name="WF", steps=[Step(name="s1", agent=agent)]).save(db=db)
        base_ids = [s["step_id"] for s in db.get_config(component_id="si-wf")["config"]["steps"]]

        studio = StudioTools(registry=Registry(dbs=[db]), db=db, workflows=True)
        out = _loads(studio.edit_workflow("si-wf", description="edited"))
        assert out.get("status") == "edited"

        version = _edit_version(out)
        new_config = db.get_config(component_id="si-wf", version=version)["config"]
        assert [s["step_id"] for s in new_config["steps"]] == base_ids
        link_keys = {link["link_key"] for link in db.get_links(component_id="si-wf", version=version)}
        assert link_keys <= set(base_ids)

    def test_description_edit_keeps_auxiliary_model_keys(self, tmp_path):
        """to_dict emits reasoning/parser/output models that from_dict does not
        yet consume; an unrelated edit must not persist their loss."""
        from agno.db.base import ComponentType

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

        config = db.get_config(component_id="aux-agent", version=_edit_version(out))["config"]
        assert config["reasoning_model"] == aux
        assert config["parser_model"] == aux
        assert config["output_model"] == aux


class TestPinProvenance:
    def test_links_skip_children_shadowed_by_code_defined_components(self, tmp_path):
        """A code-defined component with the child's exact id wins resolution,
        so pinning the same-id db shadow row would bind an unrelated config."""
        from agno.team.team import Team

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

        db = SqliteDb(db_file=str(tmp_path / "modelkeep.db"))
        db.upsert_component(component_id="fm-agent", component_type=ComponentType.AGENT, name="A")
        stored_model = {"provider": "OpenAI", "id": "gpt-5.5", "future_config": {"region": "private"}}
        db.upsert_config(
            component_id="fm-agent",
            config={"id": "fm-agent", "name": "A", "model": stored_model},
            stage="published",
        )

        studio = StudioTools(registry=Registry(models=[OpenAIResponses(id="gpt-5.4")], dbs=[db]), db=db)
        out = _loads(studio.edit_agent("fm-agent", description="edited"))
        assert out.get("status") == "edited"
        assert db.get_config(component_id="fm-agent", version=_edit_version(out))["config"]["model"] == stored_model

        # An explicit model edit still replaces it.
        out = _loads(studio.edit_agent("fm-agent", model_id="gpt-5.4"))
        assert out.get("status") == "edited"
        replaced = db.get_config(component_id="fm-agent", version=_edit_version(out))["config"]["model"]
        assert replaced.get("id") == "gpt-5.4"

    def test_step_workflow_pins_are_not_suppressed_by_a_same_id_agent(self, tmp_path):
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


class TestMemberBinding:
    """The single-catalog binder invariants (the multi-db db_id selector is
    gone; everything binds against the one catalog db)."""

    def _studio(self, db, **kwargs):
        model = OpenAIResponses(id="gpt-5.5")
        registry = Registry(models=[model], dbs=[db])
        return StudioTools(registry=registry, db=db, teams=True, workflows=True, **kwargs)

    def test_create_refuses_an_id_claimed_by_code_and_the_db(self, tmp_path):
        db = SqliteDb(id="cat", db_file=str(tmp_path / "amb.db"))
        Agent(id="both", name="DB Row").save(db=db)
        code_agent = Agent(id="both", name="Live Code")
        studio = self._studio(db, agents_list=[code_agent])

        error = _error(studio.create_team(name="AT", instructions="i", member_ids=["both"], model_id="gpt-5.5"))

        assert error["code"] == "invalid_request"
        assert "claimed by both" in error["message"]

    def test_agents_list_member_survives_a_strict_reload(self, tmp_path):
        """List members mirror into the registry, so a stored reference to
        them rehydrates instead of vanishing."""
        from agno.team.team import get_team_by_id

        db = SqliteDb(id="cat", db_file=str(tmp_path / "list.db"))
        list_agent = Agent(id="listed", name="Listed")
        studio = self._studio(db, agents_list=[list_agent])

        data = _data(
            studio.create_team(name="LT", instructions="i", member_ids=["listed"], model_id="gpt-5.5", publish=True)
        )

        loaded = get_team_by_id(db=db, id=data["id"], registry=studio.registry, strict=True)
        assert loaded is not None
        assert loaded.members[0].id == "listed"


class TestSourceConsistency:
    def test_construction_refuses_distinct_list_and_registry_objects_sharing_an_id(self):
        registry_agent = Agent(id="split", name="Registry Object")
        list_agent = Agent(id="split", name="List Object")

        with pytest.raises(ValueError, match="distinct components with id 'split'"):
            StudioTools(registry=Registry(agents=[registry_agent]), agents_list=[list_agent])

        # The same object in both places is consistent and accepted.
        shared = Agent(id="shared", name="Shared")
        StudioTools(registry=Registry(agents=[shared]), agents_list=[shared])

    def test_edit_workflow_step_replacement_refuses_code_db_ambiguity(self, tmp_path):
        from agno.workflow.step import Step
        from agno.workflow.workflow import Workflow

        db = SqliteDb(id="cat", db_file=str(tmp_path / "ewb.db"))
        Agent(id="amb", name="DB Row").save(db=db)
        clean = Agent(id="clean", name="Clean")
        clean.save(db=db)
        Workflow(id="ew-wf", name="WF", steps=[Step(name="s1", agent=clean)]).save(db=db)
        code_agent = Agent(id="amb", name="Live Code")
        model = OpenAIResponses(id="gpt-5.5")
        studio = StudioTools(
            registry=Registry(models=[model], dbs=[db]), db=db, workflows=True, agents_list=[code_agent]
        )

        error = _error(studio.edit_workflow("ew-wf", steps=[{"name": "s1", "agent_id": "amb"}]))

        assert "claimed by both" in error["message"]

    def test_create_pins_the_version_the_binder_selected(self, tmp_path):
        """The binder's verified snapshot decides the pin: a publish between
        its reads refuses, a publish after them stays self-consistent."""
        db = SqliteDb(id="cat", db_file=str(tmp_path / "snap.db"))
        member = Agent(id="sn-member", name="M", description="v1")
        member.save(db=db)
        model = OpenAIResponses(id="gpt-5.5")
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
            error = _error(
                studio.create_team(name="SN", instructions="i", member_ids=["sn-member"], model_id="gpt-5.5")
            )
        finally:
            del db.get_config
        assert "changed while it was being referenced" in error["message"]

        # A publish AFTER the verified snapshot leaves a self-consistent pin:
        # the committed version rides through to the link and the reload.
        member.description = "v1"
        member.save(db=db)
        committed = db.get_config(component_id="sn-member")["version"]
        state["calls"] = 0
        db.get_config = racy_get_config(3)
        try:
            data = _data(
                studio.create_team(
                    name="SN2", instructions="i", member_ids=["sn-member"], model_id="gpt-5.5", publish=True
                )
            )
        finally:
            del db.get_config

        from agno.team.team import get_team_by_id

        links = db.get_links(component_id=data["id"], version=1)
        pins = [link["child_version"] for link in links if link["link_kind"] == "member"]
        assert pins == [committed]
        loaded = get_team_by_id(db=db, id=data["id"], strict=True)
        assert loaded is not None
        assert loaded.members[0].description == "v1"


class TestResolutionPrecedence:
    def test_agent_appended_to_the_live_list_after_construction_reloads(self, tmp_path):
        from agno.team.team import get_team_by_id

        db = SqliteDb(id="cat", db_file=str(tmp_path / "late.db"))
        live: list = []
        model = OpenAIResponses(id="gpt-5.5")
        studio = StudioTools(registry=Registry(models=[model], dbs=[db]), db=db, teams=True, agents_list=live)
        live.append(Agent(id="late", name="Late Arrival"))

        data = _data(
            studio.create_team(name="LL", instructions="i", member_ids=["late"], model_id="gpt-5.5", publish=True)
        )

        loaded = get_team_by_id(db=db, id=data["id"], registry=studio.registry, strict=True)
        assert loaded is not None
        assert loaded.members[0].id == "late"

    def test_replaced_live_list_entry_refuses_instead_of_reload_flipping(self, tmp_path):
        db = SqliteDb(id="cat", db_file=str(tmp_path / "replace.db"))
        original = Agent(id="swap", name="Original")
        live = [original]
        model = OpenAIResponses(id="gpt-5.5")
        studio = StudioTools(registry=Registry(models=[model], dbs=[db]), db=db, teams=True, agents_list=live)
        live[0] = Agent(id="swap", name="Replacement")

        error = _error(studio.create_team(name="RL", instructions="i", member_ids=["swap"], model_id="gpt-5.5"))

        assert "not the registry's object" in error["message"]

    def test_publishing_create_refuses_a_draft_only_child(self, tmp_path):
        from agno.db.base import ComponentType

        db = SqliteDb(id="cat", db_file=str(tmp_path / "draft.db"))
        db.upsert_component(component_id="draft-child", component_type=ComponentType.AGENT, name="D")
        db.upsert_config(component_id="draft-child", config={"id": "draft-child", "name": "D"}, stage="draft")
        model = OpenAIResponses(id="gpt-5.5")
        studio = StudioTools(registry=Registry(models=[model], dbs=[db]), db=db, teams=True)

        error = _error(
            studio.create_team(
                name="DC", instructions="i", member_ids=["draft-child"], model_id="gpt-5.5", publish=True
            )
        )

        assert "Publish the child first" in error["message"]
