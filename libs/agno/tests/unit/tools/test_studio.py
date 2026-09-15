"""Unit tests for the StudioTools toolkit.

Uses a real SqliteDb backed by a pytest tmp_path so the full component +
config persistence path is exercised, not mocked.

Every tool returns one JSON envelope (StudioResult): {ok, status, data,
error: {code, message, details, retryable}, warnings}. Tests branch on the
stable error codes, not on message prose.
"""

import asyncio
import json
import threading
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
from agno.tools.studio import StudioTools
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
# Initialization
# ----------------------------------------------------------------------


DISCOVERY_TOOLS = {
    "list_models",
    "list_tools",
    "list_functions",
    "list_knowledge",
    "list_schemas",
    "list_learning",
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
    def test_default_registers_every_component_type_plus_discovery_and_versions(self, studio):
        expected = (
            DISCOVERY_TOOLS
            | LIFECYCLE_TOOLS
            | VERSIONING_TOOLS
            | {"create_agent", "edit_agent", "run_agent"}
            | {"create_team", "edit_team", "run_team"}
            | {"create_workflow", "edit_workflow", "run_workflow"}
        )
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

    def test_default_registers_team_and_workflow_tools(self, studio):
        names = set(studio.functions.keys())
        for present in ("create_team", "create_workflow", "edit_team", "edit_workflow"):
            assert present in names

    def test_async_surface_matches_sync_surface(self, studio):
        assert set(studio.async_functions.keys()) == set(studio.functions.keys())

    def test_async_surface_matches_when_everything_is_enabled(self, registry, db):
        tool = StudioTools(registry=registry, db=db)
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
            assert set(entry) == {"name", "description", "has_side_effects"}

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
        tool = StudioTools(registry=registry, db=db, include_agents=[code_agent])
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
        tool2 = StudioTools(registry=registry, db=db, include_agents=[code_agent])

        data = _data(tool2.list_components(component_type="agent"))
        shared_entries = [row for row in data["components"] if row["id"] == "shared"]
        assert len(shared_entries) == 1
        assert shared_entries[0]["source"] == "code"

    def test_list_components_dedupes_code_without_id_by_name(self, registry, db):
        tool = StudioTools(registry=registry, db=db)
        tool.create_agent(name="Shared Name", instructions="i", model_id="gpt-5.4")

        code_agent = Agent(name="Shared Name", model=OpenAIResponses(id="gpt-5.4"))
        tool2 = StudioTools(registry=registry, db=db, include_agents=[code_agent])

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
        studio = StudioTools(registry=registry, db=db, include_agents=[code_agent])
        ids = {row["id"] for row in _data(studio.list_components())["components"]}
        assert "code-1" in ids
        assert "support" in ids

    def test_list_components_covers_teams_and_workflows(self, registry, db):
        tool = StudioTools(registry=registry, db=db)
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
        tool = StudioTools(registry=registry, db=db)
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
        # Creates persist through the atomic create_component_with_config; a
        # failure there must not leave a component row behind (the id and
        # name would be permanently blocked by the strict-mint conflict).
        def fail_create(*args, **kwargs):
            raise RuntimeError("persist failed: dsn=postgres://secret")

        monkeypatch.setattr(db, "create_component_with_config", fail_create)
        monkeypatch.setattr(db, "upsert_config", fail_create)

        error = _error(studio.create_agent(name="broken", instructions="i", model_id="gpt-5.4"))
        assert error["code"] == "internal_error"
        assert "secret" not in error["message"]
        assert db.get_component("broken") is None

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
        studio = StudioTools(registry=registry, db=db)

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
        studio = StudioTools(registry=registry, db=db)

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
        studio = StudioTools(registry=registry, db=db)

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
        studio = StudioTools(registry=registry, db=db)

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
        studio = StudioTools(registry=self._registry(db, toolkit), db=db)

        error = _error(studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs"]))

        assert error["code"] == "invalid_request"
        assert "agno_docs" in error["message"]
        assert db.get_component("docs-agent") is None

    def test_edit_agent_refuses_unconnected_toolkit(self, db):
        toolkit = Toolkit(name="agno_docs")
        studio = StudioTools(registry=self._registry(db, toolkit), db=db)
        studio.create_agent(name="docs-agent", instructions="i")

        error = _error(studio.edit_agent(agent_id="docs-agent", tool_names=["agno_docs"]))

        assert error["code"] == "invalid_request"
        assert "agno_docs" in error["message"]

    def test_create_agent_persists_connected_toolkit_functions(self, db):
        toolkit = Toolkit(name="agno_docs")
        self._connect(toolkit)
        studio = StudioTools(registry=self._registry(db, toolkit), db=db)

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
        studio = StudioTools(registry=self._registry(db, toolkit), db=db)
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


class MCPTools(Toolkit):
    """Stub carrying the contract Studio's on-demand connect depends on:
    functions appear at connect() and survive close(), initialized flips with
    the session, close() skips uninitialized toolkits (so a failed connect
    needs _safe_cleanup), and an unreachable server can surface as a raised
    CancelledError escaping connect()'s own fail-soft handler. Named MCPTools
    on purpose -- Studio detects MCP toolkits by class name so the optional
    mcp extra is never imported."""

    def __init__(
        self,
        name="agno_docs",
        connect_succeeds=True,
        tool_count=1,
        connect_error=None,
        connect_delay=0.0,
        hang_after=None,
        fail_times=0,
        register_before_error=0,
        error_leaves_initialized=False,
        swallow_cancel=False,
        **kwargs,
    ):
        super().__init__(name=name, **kwargs)
        self.timeout_seconds = 5
        self._initialized = False
        self._connect_succeeds = connect_succeeds
        self._tool_count = tool_count
        self._connect_error = connect_error
        self._connect_delay = connect_delay
        self._hang_after = hang_after
        self._fail_times = fail_times
        self._register_before_error = register_before_error
        self._error_leaves_initialized = error_leaves_initialized
        self._swallow_cancel = swallow_cancel
        self.connect_count = 0
        self.close_count = 0
        self.safe_cleanup_count = 0

    @property
    def initialized(self) -> bool:
        return self._initialized

    def _register(self, count: int) -> None:
        for index in range(count):
            suffix = "" if index == 0 else f"_{index}"

            async def call_proxy(**kwargs) -> str:
                return "docs result"

            func = Function(
                name=f"search_docs{suffix}",
                description="Search the docs.",
                parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                entrypoint=call_proxy,
                skip_entrypoint_processing=True,
            )
            self.functions[func.name] = func

    async def connect(self, force: bool = False) -> None:
        self.connect_count += 1
        if self._connect_error is not None:
            raise self._connect_error
        if self._connect_delay:
            await asyncio.sleep(self._connect_delay)
        if self.connect_count <= self._fail_times:
            # A transient failure with tools already registered -- the
            # MCPToolbox shape: it registers the unfiltered superset first and
            # a filtering failure raises with that superset (and initialized)
            # in place.
            self._register(self._register_before_error)
            self._initialized = self._error_leaves_initialized
            raise RuntimeError("transient connect failure")
        if not self._connect_succeeds:
            # The real connect() is fail-soft for ordinary errors: it logs and
            # returns, leaving the toolkit empty.
            return
        self._register(self._tool_count if self._hang_after is None else self._hang_after)
        if self._hang_after is not None:
            if self._swallow_cancel:
                # A transport whose teardown never completes: the bounding
                # cancellation is absorbed, so the connect thread outlives its
                # join deadline.
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    await asyncio.Event().wait()
            else:
                # Models a transport that stops responding mid-handshake; only
                # cancellation ends it.
                await asyncio.Event().wait()
        self._initialized = True

    async def close(self) -> None:
        self.close_count += 1
        self._initialized = False

    async def _safe_cleanup(self) -> None:
        self.safe_cleanup_count += 1


class TestMCPToolkitOnDemandConnect:
    """A standalone process (no AgentOS lifespan) persists a registry MCP
    toolkit: _resolve_tools connects an unconnected MCP toolkit on demand,
    keeps the harvested functions, and releases the session so later runs
    reconnect on their own loop."""

    def _studio(self, db, toolkit):
        registry = Registry(
            name="MCP OnDemand Registry",
            tools=[toolkit],
            models=[OpenAIResponses(id="gpt-5.5")],
            dbs=[db],
        )
        return StudioTools(registry=registry, db=db)

    def test_create_agent_connects_unconnected_mcp_toolkit(self, db):
        toolkit = MCPTools()
        studio = self._studio(db, toolkit)

        out = _loads(studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs"], publish=True))

        assert out["status"] == "created"
        persisted_tools = db.get_config("docs-agent")["config"]["tools"]
        assert [t["name"] for t in persisted_tools] == ["search_docs"]
        assert toolkit.connect_count == 1

    def test_toolkit_is_released_after_harvest(self, db):
        toolkit = MCPTools()
        studio = self._studio(db, toolkit)

        _data(studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs"]))

        # The session must not stay bound to the private connect loop; the
        # registered functions must survive the release so the persisted
        # config and later per-run reconnects both have them.
        assert toolkit.close_count == 1
        assert not toolkit.initialized
        assert "search_docs" in toolkit.functions

    def test_persists_from_worker_thread_with_running_loop(self, db):
        """The standalone-arun shape that used to fail: a sync Studio tool
        executes via asyncio.to_thread while the agent's loop keeps running."""
        toolkit = MCPTools()
        studio = self._studio(db, toolkit)

        async def main():
            return await asyncio.to_thread(
                studio.create_agent,
                name="docs-agent",
                instructions="i",
                tool_names=["agno_docs"],
                publish=True,
            )

        out = _loads(asyncio.run(main()))

        assert out["ok"] is True, out
        persisted_tools = db.get_config("docs-agent")["config"]["tools"]
        assert [t["name"] for t in persisted_tools] == ["search_docs"]
        assert not toolkit.initialized

    def test_direct_call_on_running_loop_does_not_deadlock(self, db):
        toolkit = MCPTools()
        studio = self._studio(db, toolkit)

        async def main():
            return studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs"])

        out = _loads(asyncio.run(main()))

        assert out["ok"] is True, out
        assert toolkit.connect_count == 1

    def test_failed_connect_still_refuses(self, db):
        toolkit = MCPTools(connect_succeeds=False)
        studio = self._studio(db, toolkit)

        error = _error(studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs"]))

        assert error["code"] == "invalid_request"
        assert "agno_docs" in error["message"]
        assert db.get_component("docs-agent") is None
        assert toolkit.connect_count == 1
        # close() skips uninitialized toolkits, so a failed connect is cleaned
        # up through _safe_cleanup -- otherwise partially-entered transport
        # contexts would poison the next connect() attempt.
        assert toolkit.safe_cleanup_count == 1
        assert toolkit.close_count == 0

    def test_cancelled_error_from_connect_is_contained(self, db):
        """The mcp client surfaces an unreachable server as CancelledError,
        which escapes connect()'s own fail-soft handler. Studio must clean the
        toolkit up, keep connecting the rest of the list, and still refuse."""
        broken = MCPTools(name="agno_docs", connect_error=asyncio.CancelledError())
        working = MCPTools(name="agno_search")
        registry = Registry(
            name="MCP OnDemand Registry",
            tools=[broken, working],
            models=[OpenAIResponses(id="gpt-5.5")],
            dbs=[db],
        )
        studio = StudioTools(registry=registry, db=db)

        error = _error(
            studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs", "agno_search"])
        )

        assert error["code"] == "invalid_request"
        assert "agno_docs" in error["message"]
        assert "agno_search" not in error["message"]
        assert broken.safe_cleanup_count == 1
        assert broken.close_count == 0
        # The failure did not kill the connect pass mid-list.
        assert working.connect_count == 1
        assert not working.initialized

    def test_connect_that_finds_no_tools_refuses_and_releases(self, db):
        toolkit = MCPTools(tool_count=0)
        studio = self._studio(db, toolkit)

        error = _error(studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs"]))

        assert error["code"] == "invalid_request"
        # A successfully connected but toolless session must not stay bound to
        # the private connect loop.
        assert toolkit.close_count == 1
        assert not toolkit.initialized

    def test_already_connected_toolkit_is_left_alone(self, db):
        toolkit = MCPTools()
        asyncio.run(toolkit.connect())
        studio = self._studio(db, toolkit)

        _data(studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs"]))

        assert toolkit.connect_count == 1  # only the explicit connect above
        assert toolkit.close_count == 0
        assert toolkit.initialized

    def test_hung_connect_is_bounded_and_refused(self, db, monkeypatch):
        monkeypatch.setattr("agno.tools.studio._MCP_CONNECT_SLACK_SECONDS", 0.2)
        toolkit = MCPTools(hang_after=0)
        toolkit.timeout_seconds = 0.1
        studio = self._studio(db, toolkit)

        start = time.monotonic()
        error = _error(studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs"]))
        elapsed = time.monotonic() - start

        assert error["code"] == "invalid_request"
        assert elapsed < 5
        assert toolkit.safe_cleanup_count == 1
        assert db.get_component("docs-agent") is None

    def test_partially_registered_hung_connect_is_refused_and_cleared(self, db, monkeypatch):
        """A connect interrupted mid-registration holds a partial function
        list; the create must be refused and the leftovers cleared -- an
        unconnected toolkit with functions would be persisted as-is by any
        LATER call."""
        monkeypatch.setattr("agno.tools.studio._MCP_CONNECT_SLACK_SECONDS", 0.2)
        toolkit = MCPTools(tool_count=2, hang_after=1)
        toolkit.timeout_seconds = 0.1
        studio = self._studio(db, toolkit)

        error = _error(studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs"]))

        assert error["code"] == "invalid_request"
        assert "agno_docs" in error["message"]
        assert not toolkit.functions  # the partial registration was cleared
        assert db.get_component("docs-agent") is None

    def test_retry_after_transient_failure_reconnects_and_persists_fully(self, db):
        """The first create fails mid-connect with one of two tools already
        registered; the retry must reconnect (not persist the leftover)."""
        toolkit = MCPTools(tool_count=2, fail_times=1, register_before_error=1)
        studio = self._studio(db, toolkit)

        error = _error(studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs"]))
        assert error["code"] == "invalid_request"

        data = _data(studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs"]))
        assert data["id"] == "docs-agent"
        persisted_tools = db.get_latest_config("docs-agent")["config"]["tools"]
        assert sorted(t["name"] for t in persisted_tools) == ["search_docs", "search_docs_1"]
        assert toolkit.connect_count == 2

    def test_failed_filter_superset_is_not_persisted_on_retry(self, db):
        """MCPToolbox registers the unfiltered superset before filtering and a
        filter failure raises with that superset (and initialized) in place.
        The retry must reconnect and persist only the filtered set."""
        toolkit = MCPTools(tool_count=1, fail_times=1, register_before_error=2, error_leaves_initialized=True)
        studio = self._studio(db, toolkit)

        error = _error(studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs"]))
        assert error["code"] == "invalid_request"
        assert toolkit.close_count == 1  # the initialized-but-failed toolkit was released
        assert not toolkit.functions  # the unfiltered superset was cleared

        data = _data(studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs"]))
        assert data["id"] == "docs-agent"
        persisted_tools = db.get_latest_config("docs-agent")["config"]["tools"]
        assert [t["name"] for t in persisted_tools] == ["search_docs"]

    def test_abandoned_connect_blocks_retry_until_its_thread_dies(self, db, monkeypatch):
        """A connect that absorbs its bounding cancellation outlives the join
        deadline. Its partial functions are still live under the zombie loop,
        so the first call must refuse them via the failed-ids channel, and a
        retry must not start a second connect against the same toolkit."""
        monkeypatch.setattr("agno.tools.studio._MCP_CONNECT_SLACK_SECONDS", 0.2)
        toolkit = MCPTools(hang_after=1, swallow_cancel=True)
        toolkit.timeout_seconds = 0.1
        studio = self._studio(db, toolkit)

        error = _error(studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs"]))
        assert error["code"] == "invalid_request"
        assert toolkit.functions  # zombie still holds its partial registration

        error = _error(studio.create_agent(name="docs-agent2", instructions="i", tool_names=["agno_docs"]))
        assert error["code"] == "invalid_request"
        assert toolkit.connect_count == 1  # no second connect raced the zombie

    def test_toolkit_connected_elsewhere_with_no_tools_is_not_touched(self, db):
        toolkit = MCPTools(tool_count=0)
        asyncio.run(toolkit.connect())  # e.g. the AgentOS lifespan connected it
        studio = self._studio(db, toolkit)

        error = _error(studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs"]))

        assert error["code"] == "invalid_request"
        assert toolkit.connect_count == 1  # only the explicit connect above
        # Its LIVE session, bound to another loop, must not be closed here.
        assert toolkit.close_count == 0
        assert toolkit.initialized

    def test_concurrent_creates_connect_once(self, db):
        """Parallel Studio tool calls each run in their own worker thread; the
        shared toolkit must be connected by exactly one of them -- MCPTools
        stages transport state on unlocked instance attributes, so concurrent
        connects corrupt each other."""
        toolkit = MCPTools(connect_delay=0.2)
        studio = self._studio(db, toolkit)
        barrier = threading.Barrier(2)
        results: Dict[str, str] = {}

        def create(name: str) -> None:
            barrier.wait()
            results[name] = studio.create_agent(name=name, instructions="i", tool_names=["agno_docs"])

        threads = [threading.Thread(target=create, args=(f"racer-{i}",)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert toolkit.connect_count == 1
        for payload in results.values():
            assert _loads(payload)["ok"] is True, payload

    def test_non_mcp_empty_toolkit_gets_no_connect_attempt(self, db):
        """The on-demand connect is scoped to MCP-shaped toolkits: a plain
        empty toolkit is refused as before, without Studio poking its
        connect() (which on connectable toolkits opens real resources)."""

        class RecordingToolkit(Toolkit):
            def __init__(self):
                super().__init__(name="agno_docs")
                self.connect_count = 0

            def connect(self) -> None:
                self.connect_count += 1

        toolkit = RecordingToolkit()
        studio = self._studio(db, toolkit)

        error = _error(studio.create_agent(name="docs-agent", instructions="i", tool_names=["agno_docs"]))

        assert error["code"] == "invalid_request"
        assert "agno_docs" in error["message"]
        assert toolkit.connect_count == 0

    def test_edit_agent_connects_on_demand(self, db):
        toolkit = MCPTools()
        studio = self._studio(db, toolkit)
        studio.create_agent(name="docs-agent", instructions="i")

        _data(studio.edit_agent(agent_id="docs-agent", tool_names=["agno_docs"]))

        persisted_tools = db.get_latest_config("docs-agent")["config"]["tools"]
        assert [t["name"] for t in persisted_tools] == ["search_docs"]
        assert toolkit.connect_count == 1


class TestRealMCPToolsContract:
    """Studio's on-demand connect duck-types the real MCPTools (by class name,
    so the optional mcp extra is never imported). Pin the pieces it relies on
    so drift in agno.tools.mcp surfaces here, not in a standalone process at
    persist time."""

    def test_real_mcp_tools_satisfies_the_on_demand_contract(self):
        pytest.importorskip("mcp")
        import inspect

        from agno.tools.mcp import MCPTools as RealMCPTools
        from agno.tools.studio import _is_mcp_toolkit

        assert isinstance(inspect.getattr_static(RealMCPTools, "initialized"), property)
        assert inspect.iscoroutinefunction(RealMCPTools.connect)
        assert inspect.iscoroutinefunction(RealMCPTools.close)
        assert inspect.iscoroutinefunction(RealMCPTools._safe_cleanup)

        toolkit = RealMCPTools(url="https://docs.example.com/mcp")
        assert _is_mcp_toolkit(toolkit)
        assert isinstance(toolkit.timeout_seconds, (int, float)) and toolkit.timeout_seconds > 0
        assert toolkit.initialized is False
        assert not toolkit.functions

    def test_real_close_keeps_the_harvested_functions(self):
        """The single most load-bearing property of the release design: the
        real close() tears down sessions but never touches functions. If a
        hygiene refactor ever clears them, the on-demand connect silently
        regresses into always-refuse in standalone processes."""
        pytest.importorskip("mcp")
        from agno.tools.mcp import MCPTools as RealMCPTools

        toolkit = RealMCPTools(url="https://docs.example.com/mcp")
        toolkit.functions["search_docs"] = Function(
            name="search_docs",
            parameters={"type": "object", "properties": {}},
            skip_entrypoint_processing=True,
        )
        toolkit._initialized = True
        # All teardown contexts are None, so close() no-ops through them.
        asyncio.run(toolkit.close())

        assert toolkit.initialized is False
        assert "search_docs" in toolkit.functions


class TestCreateTeam:
    @pytest.fixture
    def studio_teams(self, registry, db):
        return StudioTools(registry=registry, db=db)

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
        tool = StudioTools(registry=registry, db=db, default_num_history_runs=5)
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
        return StudioTools(registry=registry, db=db)

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
        studio = StudioTools(registry=registry, db=db)
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
        # The view is the full WorkflowStepSpec tree, so a read can feed a
        # steps edit: executors and nested children included, not just labels.
        steps_view = view["steps"]
        assert [(st["type"], st["name"]) for st in steps_view] == [
            ("step", "s1"),
            ("parallel", "par"),
            ("loop", "lp"),
            ("condition", "cond"),
            ("router", "rt"),
        ]
        assert steps_view[0]["agent_id"] == "w"
        assert steps_view[1]["steps"][0]["agent_id"] == "w"
        assert steps_view[2]["max_iterations"] == 2
        assert steps_view[2]["steps"][0]["type"] == "step"
        assert steps_view[3]["evaluator_function"]
        assert steps_view[3]["steps"], steps_view[3]
        assert steps_view[4]["selector_function"]
        assert steps_view[4]["choices"][0]["agent_id"] == "w"
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
        studio = StudioTools(registry=registry, db=db)
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
        # Append-only history: the old in-place
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
        return StudioTools(registry=registry, db=db)

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
        return StudioTools(registry=registry, db=db)

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

    def test_unknown_reasoning_model_returns_model_not_found(self, studio_refs):
        error = _error(
            studio_refs.create_agent(name="x", instructions="i", model_id="gpt-5.4", reasoning_model_id="ghost")
        )
        assert error["code"] == "model_not_found"


class TestLearningSurface:
    """learning_name wires a component to a LearningMachine the deployer
    declared on the Registry. The stored config carries a reference by name,
    never the machine's config, so the Registry stays the only place learning
    is authored; list_learning shows what is declared, namespace first."""

    @pytest.fixture
    def brain(self):
        from agno.learn import LearningMachine
        from agno.learn.config import LearningMode, UserMemoryConfig

        return LearningMachine(
            name="shared-brain",
            namespace="team_west",
            user_memory=UserMemoryConfig(mode=LearningMode.PROPOSE),
            entity_memory=True,
        )

    @pytest.fixture
    def studio_learning(self, registry, db, brain):
        registry.add_learning(brain)
        return StudioTools(registry=registry, db=db)

    # -- discovery ---------------------------------------------------------

    def test_list_learning_reads_declared_fields_without_binding_stores(self, studio_learning, brain):
        data = _data(studio_learning.list_learning())
        assert data["count"] == 1
        row = data["learning"][0]
        assert row["name"] == "shared-brain"
        assert row["namespace"] == "team_west"
        assert row["stores"] == {
            "user_memory": {"mode": "propose"},
            "entity_memory": {"mode": "agentic", "namespace": "team_west"},
        }
        assert row["model_id"] is None
        assert row["db"] is False
        assert row["knowledge"] is False
        # Listing must not build the machine's stores: a store built before the
        # machine has a db keeps db=None for the life of the process.
        assert brain._stores is None

    def test_list_learning_shows_store_namespace_bound_model_and_auto_learned_knowledge(self, registry, db):
        from agno.learn import LearningMachine
        from agno.learn.config import LearnedKnowledgeConfig

        class FakeKnowledge:
            name = "handbook"

        registry.add_learning(
            LearningMachine(
                name="kb-brain",
                namespace="team_west",
                knowledge=FakeKnowledge(),
                learned_knowledge=LearnedKnowledgeConfig(namespace="ops"),
                model=OpenAIResponses(id="gpt-5.5"),
            )
        )
        registry.add_learning(LearningMachine(name="auto-kb", knowledge=FakeKnowledge()))
        registry.add_learning(LearningMachine(user_memory=True))  # unnamed: not a registry resource
        studio = StudioTools(registry=registry, db=db)

        rows = {row["name"]: row for row in _data(studio.list_learning())["learning"]}
        assert set(rows) == {"kb-brain", "auto-kb"}
        # An explicit store namespace wins over the machine's.
        assert rows["kb-brain"]["stores"] == {"learned_knowledge": {"mode": "agentic", "namespace": "ops"}}
        assert rows["kb-brain"]["model_id"] == "gpt-5.5"
        assert rows["kb-brain"]["knowledge"] is True
        # learned_knowledge is auto-enabled by a bound knowledge and inherits the machine namespace.
        assert rows["auto-kb"]["stores"] == {"learned_knowledge": {"mode": "agentic", "namespace": "global"}}

    def test_list_learning_reports_a_store_instance_namespace_verbatim_and_custom_stores(self, registry, db):
        """A pre-built Store instance keeps its own config namespace at run
        time (the machine only rewrites Config inputs), so the row must say
        what the store will actually use, not the machine namespace."""
        from agno.learn import LearningMachine
        from agno.learn.config import EntityMemoryConfig
        from agno.learn.stores.entity_memory import EntityMemoryStore

        class TinyStore:
            def recall(self, **kwargs):
                return None

        machine = LearningMachine(
            name="instances",
            namespace="team_west",
            entity_memory=EntityMemoryStore(config=EntityMemoryConfig()),
            custom_stores={"tiny": TinyStore()},  # type: ignore[dict-item]
        )
        registry.add_learning(machine)
        studio = StudioTools(registry=registry, db=db)

        row = {r["name"]: r for r in _data(studio.list_learning())["learning"]}["instances"]
        assert row["stores"]["entity_memory"]["namespace"] == "global"
        assert row["stores"]["entity_memory"]["namespace"] == machine.stores["entity_memory"].config.namespace  # type: ignore[attr-defined]
        assert row["custom_stores"] == ["tiny"]

    @pytest.mark.asyncio
    async def test_alist_learning_matches_sync(self, studio_learning):
        assert _loads(await studio_learning.alist_learning()) == _loads(studio_learning.list_learning())

    # -- create / edit -----------------------------------------------------

    def test_create_agent_stores_a_reference_not_the_machine(self, studio_learning, db):
        _data(
            studio_learning.create_agent(
                name="learner", instructions="i", model_id="gpt-5.4", learning_name="shared-brain", publish=True
            )
        )
        assert db.get_config(component_id="learner", version=1)["config"]["learning"] == {"name": "shared-brain"}
        view = _data(studio_learning.get_component("learner"))
        assert view["learning_name"] == "shared-brain"

    def test_edit_agent_empty_string_detaches(self, studio_learning, db):
        _data(
            studio_learning.create_agent(
                name="learner", instructions="i", model_id="gpt-5.4", learning_name="shared-brain"
            )
        )
        out = _loads(studio_learning.edit_agent("learner", learning_name=""))
        assert "learning" not in db.get_config(component_id="learner", version=_edit_version(out))["config"]
        assert "learning_name" not in _data(studio_learning.get_component("learner"))

    def test_unknown_learning_returns_learning_not_found(self, studio_learning):
        error = _error(
            studio_learning.create_agent(name="x", instructions="i", model_id="gpt-5.4", learning_name="ghost")
        )
        assert error["code"] == "learning_not_found"
        assert error["details"]["name"] == "ghost"

        _data(studio_learning.create_agent(name="member", instructions="i", model_id="gpt-5.4", publish=True))
        error = _error(
            studio_learning.create_team(name="crew", instructions="i", member_ids=["member"], learning_name="ghost")
        )
        assert error["code"] == "learning_not_found"
        error = _error(studio_learning.edit_agent("member", learning_name="ghost"))
        assert error["code"] == "learning_not_found"
        _data(studio_learning.create_team(name="crew", instructions="i", member_ids=["member"]))
        error = _error(studio_learning.edit_team("crew", learning_name="ghost"))
        assert error["code"] == "learning_not_found"

    def test_ambiguous_learning_name_is_refused_not_bound_to_the_first(self, registry, db):
        """Two distinct machines under one name: binding the first would
        publish a component that strict dispatch then refuses."""
        from agno.learn import LearningMachine

        registry.add_learning(LearningMachine(name="dup", namespace="alpha", user_memory=True))
        registry.add_learning(LearningMachine(name="dup", namespace="beta", user_memory=True))
        studio = StudioTools(registry=registry, db=db)

        error = _error(studio.create_agent(name="x", instructions="i", model_id="gpt-5.4", learning_name="dup"))
        assert error["code"] == "ambiguous_reference"
        assert error["details"]["name"] == "dup"

    def test_team_forms_take_learning_name(self, studio_learning, db):
        _data(studio_learning.create_agent(name="member", instructions="i", model_id="gpt-5.4", publish=True))
        _data(
            studio_learning.create_team(
                name="crew", instructions="i", member_ids=["member"], learning_name="shared-brain", publish=True
            )
        )
        assert db.get_config(component_id="crew", version=1)["config"]["learning"] == {"name": "shared-brain"}
        assert _data(studio_learning.get_component("crew"))["learning_name"] == "shared-brain"

        out = _loads(studio_learning.edit_team("crew", learning_name=""))
        assert "learning" not in db.get_config(component_id="crew", version=_edit_version(out))["config"]

    @pytest.mark.asyncio
    async def test_async_forms_take_learning_name(self, studio_learning, db):
        _data(
            await studio_learning.acreate_agent(
                name="alearner", instructions="i", model_id="gpt-5.4", learning_name="shared-brain", publish=True
            )
        )
        assert db.get_config(component_id="alearner", version=1)["config"]["learning"] == {"name": "shared-brain"}
        _data(
            await studio_learning.acreate_team(
                name="acrew", instructions="i", member_ids=["alearner"], learning_name="shared-brain", publish=True
            )
        )
        assert db.get_config(component_id="acrew", version=1)["config"]["learning"] == {"name": "shared-brain"}

        out = _loads(await studio_learning.aedit_agent("alearner", learning_name=""))
        assert "learning" not in db.get_config(component_id="alearner", version=_edit_version(out))["config"]
        out = _loads(await studio_learning.aedit_team("acrew", learning_name=""))
        assert "learning" not in db.get_config(component_id="acrew", version=_edit_version(out))["config"]

    # -- shared-machine binding is disclosed in the result --------------------

    def test_wiring_an_unbound_machine_returns_warnings_on_create_and_edit(self, studio_learning, db):
        """The fixture machine declares neither db nor model: the caller is told,
        in the success envelope, that the first component to run binds both for
        every sharer. Sync and async, create and edit, agent and team."""
        out = _loads(
            studio_learning.create_agent(
                name="learner", instructions="i", model_id="gpt-5.4", learning_name="shared-brain", publish=True
            )
        )
        assert out["ok"] is True
        assert any("declares no db" in w and "first component to run" in w for w in out["warnings"])
        assert any("declares no model" in w for w in out["warnings"])
        assert any(f"'{db.id}'" in w for w in out["warnings"] if "declares no db" in w)

        out = _loads(studio_learning.edit_agent("learner", learning_name="shared-brain"))
        assert out["ok"] is True and out["status"] == "edited"
        assert any("declares no db" in w for w in out["warnings"])

        # An edit that does not touch learning carries no disclosure.
        out = _loads(studio_learning.edit_agent("learner", description="quiet"))
        assert out["ok"] is True and out["warnings"] == []

        out = _loads(
            studio_learning.create_team(
                name="crew", instructions="i", member_ids=["learner"], learning_name="shared-brain", publish=True
            )
        )
        assert out["ok"] is True
        assert any("declares no db" in w for w in out["warnings"])
        out = _loads(studio_learning.edit_team("crew", learning_name="shared-brain"))
        assert out["ok"] is True and any("declares no db" in w for w in out["warnings"])

    @pytest.mark.asyncio
    async def test_async_forms_return_the_same_warnings(self, studio_learning):
        out = _loads(
            await studio_learning.acreate_agent(
                name="alearner", instructions="i", model_id="gpt-5.4", learning_name="shared-brain", publish=True
            )
        )
        assert out["ok"] is True and any("declares no db" in w for w in out["warnings"])
        out = _loads(await studio_learning.aedit_agent("alearner", learning_name="shared-brain"))
        assert out["ok"] is True and any("declares no model" in w for w in out["warnings"])
        out = _loads(
            await studio_learning.acreate_team(
                name="acrew", instructions="i", member_ids=["alearner"], learning_name="shared-brain", publish=True
            )
        )
        assert out["ok"] is True and any("declares no db" in w for w in out["warnings"])
        out = _loads(await studio_learning.aedit_team("acrew", learning_name="shared-brain"))
        assert out["ok"] is True and any("declares no db" in w for w in out["warnings"])

    def test_a_fully_declared_machine_wires_without_warnings(self, registry, db):
        from agno.learn import LearningMachine

        registry.add_learning(
            LearningMachine(name="bound", db=db, model=OpenAIResponses(id="gpt-5.5"), user_memory=True)
        )
        studio = StudioTools(registry=registry, db=db)
        out = _loads(studio.create_agent(name="learner", instructions="i", model_id="gpt-5.4", learning_name="bound"))
        assert out["ok"] is True
        assert out["warnings"] == []

    def test_a_machine_bound_to_a_different_db_is_disclosed(self, registry, db, tmp_path):
        from agno.learn import LearningMachine

        other = SqliteDb(id="other-learning-db", db_file=str(tmp_path / "other.db"))
        registry.add_learning(
            LearningMachine(name="elsewhere", db=other, model=OpenAIResponses(id="gpt-5.5"), user_memory=True)
        )
        studio = StudioTools(registry=registry, db=db)
        out = _loads(
            studio.create_agent(name="learner", instructions="i", model_id="gpt-5.4", learning_name="elsewhere")
        )
        assert out["ok"] is True
        assert len(out["warnings"]) == 1
        assert "bound to db 'other-learning-db'" in out["warnings"][0]
        assert f"this component uses '{db.id}'" in out["warnings"][0]

    def test_different_files_with_omitted_ids_are_disclosed(self, tmp_path):
        """Neither db declares an id: the generated ids must still tell two
        physical databases apart, or this disclosure is silently suppressed
        (the ids used to collide because the seed expression ignored db_file
        whenever no engine was passed)."""
        from agno.learn import LearningMachine

        component_db = SqliteDb(db_file=str(tmp_path / "components.db"))
        machine_db = SqliteDb(db_file=str(tmp_path / "learning.db"))
        assert component_db.id != machine_db.id

        registry = Registry(
            models=[OpenAIResponses(id="gpt-5.4")],
            dbs=[component_db],
            learning=[
                LearningMachine(name="elsewhere", db=machine_db, model=OpenAIResponses(id="gpt-5.5"), user_memory=True)
            ],
        )
        studio = StudioTools(registry=registry, db=component_db)
        out = _loads(
            studio.create_agent(name="learner", instructions="i", model_id="gpt-5.4", learning_name="elsewhere")
        )
        assert out["ok"] is True
        assert len(out["warnings"]) == 1
        assert f"bound to db '{machine_db.id}'" in out["warnings"][0]
        assert f"this component uses '{component_db.id}'" in out["warnings"][0]

    # -- zero-config: the default machine ---------------------------------

    def test_enable_learning_stores_the_default_machine_and_rehydrates(self, studio_learning, db, registry):
        """enable_learning=True is the zero-config path: the config carries
        learning: True and the framework builds the default machine (user
        profile + user memory on the component's own db and model) at init."""
        from agno.agent._init import initialize_agent
        from agno.learn import LearningMachine
        from agno.os.utils import get_agent_by_id

        _data(
            studio_learning.create_agent(
                name="rememberer", instructions="i", model_id="gpt-5.4", enable_learning=True, publish=True
            )
        )
        assert db.get_config(component_id="rememberer", version=1)["config"]["learning"] is True
        assert _data(studio_learning.get_component("rememberer"))["learning"] is True

        agent = get_agent_by_id("rememberer", agents=None, db=db, registry=registry)
        assert agent.learning is True
        initialize_agent(agent)
        machine = agent.learning_machine
        assert isinstance(machine, LearningMachine)
        assert machine.name is None
        assert machine.user_profile is True and machine.user_memory is True
        assert machine.entity_memory is False and machine.learned_knowledge is False
        assert machine.db is not None
        assert machine.model is not None and machine.model.id == "gpt-5.4"

    def test_enable_learning_off_and_learning_name_precedence(self, studio_learning, db):
        _data(
            studio_learning.create_agent(name="rememberer", instructions="i", model_id="gpt-5.4", enable_learning=True)
        )

        out = _loads(studio_learning.edit_agent("rememberer", enable_learning=False))
        assert "learning" not in db.get_config(component_id="rememberer", version=_edit_version(out))["config"]

        # Both in one call: the registry reference wins over the default machine.
        out = _loads(studio_learning.edit_agent("rememberer", learning_name="shared-brain", enable_learning=True))
        assert db.get_config(component_id="rememberer", version=_edit_version(out))["config"]["learning"] == {
            "name": "shared-brain"
        }
        # enable_learning=False turns learning off whatever shape it had.
        out = _loads(studio_learning.edit_agent("rememberer", enable_learning=False))
        assert "learning" not in db.get_config(component_id="rememberer", version=_edit_version(out))["config"]

    def test_enable_learning_keeps_a_wired_machine_and_says_so(self, studio_learning, db):
        """enable_learning=True on a component already wired to a registry
        machine keeps the machine: replacing it would silently move the
        component off the shared namespace. The caller is told, and
        learning_name="" in the same call is the explicit way to switch."""
        _data(
            studio_learning.create_agent(
                name="learner", instructions="i", model_id="gpt-5.4", learning_name="shared-brain", publish=True
            )
        )
        out = _loads(studio_learning.edit_agent("learner", enable_learning=True))
        assert out["ok"] is True
        assert any("already wired to learning machine 'shared-brain'" in w for w in out["warnings"])
        assert db.get_config(component_id="learner", version=_edit_version(out))["config"]["learning"] == {
            "name": "shared-brain"
        }

        out = _loads(studio_learning.edit_agent("learner", learning_name="", enable_learning=True))
        assert out["warnings"] == []
        assert db.get_config(component_id="learner", version=_edit_version(out))["config"]["learning"] is True

    def test_empty_learning_name_drops_the_reference_and_enable_learning_decides(self, studio_learning, db):
        """learning_name="" means no registry reference, not "no learning":
        with enable_learning=True the default machine is wired, on create too.
        The legacy pair is dropped only when the call ends with learning wired."""
        from agno.memory.manager import MemoryManager

        out = _loads(
            studio_learning.create_agent(
                name="filler",
                instructions="i",
                model_id="gpt-5.4",
                enable_learning=True,
                learning_name="",
                publish=True,
            )
        )
        assert out["ok"] is True
        assert db.get_config(component_id="filler", version=1)["config"]["learning"] is True

        Agent(
            id="legacy-keep",
            name="Legacy",
            model=OpenAIResponses(id="gpt-5.5"),
            memory_manager=MemoryManager(id="mm-keep"),
            enable_agentic_memory=True,
        ).save(db=db)
        # Detach with nothing to detach: no learning, and the legacy pair stays.
        out = _loads(studio_learning.edit_agent("legacy-keep", learning_name=""))
        after = db.get_config(component_id="legacy-keep", version=_edit_version(out))["config"]
        assert "learning" not in after
        assert after["enable_agentic_memory"] is True
        assert after["memory_manager"] == {"registry_id": "mm-keep"}
        # Off stays off and also leaves the pair alone.
        out = _loads(studio_learning.edit_agent("legacy-keep", enable_learning=False, learning_name=""))
        after = db.get_config(component_id="legacy-keep", version=_edit_version(out))["config"]
        assert "learning" not in after and after["enable_agentic_memory"] is True
        # The default machine replaces the pair.
        out = _loads(studio_learning.edit_agent("legacy-keep", enable_learning=True, learning_name=""))
        after = db.get_config(component_id="legacy-keep", version=_edit_version(out))["config"]
        assert after["learning"] is True
        assert "enable_agentic_memory" not in after and "memory_manager" not in after

    def test_enable_learning_clears_the_legacy_memory_pair(self, registry, db):
        from agno.memory.manager import MemoryManager

        manager = MemoryManager(id="mm-stable")
        registry.memory_managers.append(manager)
        Agent(
            id="legacy-default",
            name="Legacy",
            model=OpenAIResponses(id="gpt-5.5"),
            memory_manager=manager,
            enable_agentic_memory=True,
        ).save(db=db)
        studio = StudioTools(registry=registry, db=db)

        out = _loads(studio.edit_agent("legacy-default", enable_learning=True))
        after = db.get_config(component_id="legacy-default", version=_edit_version(out))["config"]
        assert after["learning"] is True
        assert "enable_agentic_memory" not in after
        assert "memory_manager" not in after

    @pytest.mark.asyncio
    async def test_enable_learning_on_team_and_async_forms(self, studio_learning, db):
        _data(studio_learning.create_agent(name="member", instructions="i", model_id="gpt-5.4", publish=True))
        _data(
            studio_learning.create_team(
                name="crew", instructions="i", member_ids=["member"], enable_learning=True, publish=True
            )
        )
        assert db.get_config(component_id="crew", version=1)["config"]["learning"] is True
        out = _loads(await studio_learning.aedit_team("crew", enable_learning=False))
        assert "learning" not in db.get_config(component_id="crew", version=_edit_version(out))["config"]

        _data(
            await studio_learning.acreate_agent(
                name="arem", instructions="i", model_id="gpt-5.4", enable_learning=True, publish=True
            )
        )
        assert db.get_config(component_id="arem", version=1)["config"]["learning"] is True
        out = _loads(await studio_learning.aedit_agent("arem", enable_learning=False))
        assert "learning" not in db.get_config(component_id="arem", version=_edit_version(out))["config"]
        _data(
            await studio_learning.acreate_team(
                name="acrew", instructions="i", member_ids=["member"], enable_learning=True, publish=True
            )
        )
        assert db.get_config(component_id="acrew", version=1)["config"]["learning"] is True

    # -- learning only -----------------------------------------------------

    def test_wiring_learning_clears_the_legacy_memory_pair(self, registry, db, brain):
        """A component stored before Studio authored learning by reference can
        carry enable_agentic_memory and a memory manager, and get_component
        keeps showing the flag. Wiring learning drops both - registered or not
        - so the two update_user_memory tools can never coexist on a
        Studio-edited component, and the lenient-edit preserve step must not
        bring the unresolvable manager back."""
        from agno.memory.manager import MemoryManager

        registry.add_learning(brain)
        registered = MemoryManager(id="mm-stable")
        registry.memory_managers.append(registered)
        Agent(
            id="legacy",
            name="Legacy",
            model=OpenAIResponses(id="gpt-5.5"),
            memory_manager=registered,
            enable_agentic_memory=True,
        ).save(db=db)
        Agent(
            id="legacy-unresolvable",
            name="Legacy 2",
            model=OpenAIResponses(id="gpt-5.5"),
            memory_manager=MemoryManager(id="mm-gone"),
            enable_agentic_memory=True,
        ).save(db=db)
        before = db.get_config(component_id="legacy", version=1)["config"]
        assert before["enable_agentic_memory"] is True
        assert before["memory_manager"] == {"registry_id": "mm-stable"}

        studio = StudioTools(registry=registry, db=db)
        # Read-only visibility of the legacy flag survives its removal from the forms.
        assert _data(studio.get_component("legacy"))["enable_agentic_memory"] is True
        for component_id in ("legacy", "legacy-unresolvable"):
            out = _loads(studio.edit_agent(component_id, learning_name="shared-brain"))
            after = db.get_config(component_id=component_id, version=_edit_version(out))["config"]
            assert after["learning"] == {"name": "shared-brain"}, component_id
            assert "enable_agentic_memory" not in after, component_id
            assert "memory_manager" not in after, component_id
        assert _data(studio.get_component("legacy")).get("enable_agentic_memory") is None

    # -- edit preservation -------------------------------------------------

    def _saved_with_unregistered_machine(self, tmp_path, kind: str, component_id: str):
        from agno.learn import LearningMachine
        from agno.team.team import Team

        db = SqliteDb(db_file=str(tmp_path / f"preserve_{component_id}.db"))
        machine = LearningMachine(name="shared-brain", user_memory=True)
        if kind == "agent":
            Agent(id=component_id, name="L", model=OpenAIResponses(id="gpt-5.5"), learning=machine).save(db=db)
        else:
            Team(id=component_id, name="L", members=[Agent(id=f"{component_id}-m", name="M")], learning=machine).save(
                db=db
            )
        # Empty registry: the reference does not resolve, so the lenient edit base drops it.
        return db, StudioTools(registry=Registry(), db=db)

    def test_description_edit_preserves_unresolved_learning(self, tmp_path):
        db, studio = self._saved_with_unregistered_machine(tmp_path, "agent", "learn-agent")
        out = _loads(studio.edit_agent("learn-agent", description="edited"))
        assert out.get("status") == "edited"
        row = db.get_config(component_id="learn-agent", version=_edit_version(out))
        assert row["config"]["learning"] == {"name": "shared-brain"}
        assert row["config"]["description"] == "edited"

    @pytest.mark.asyncio
    async def test_async_description_edit_preserves_unresolved_learning(self, tmp_path):
        db, studio = self._saved_with_unregistered_machine(tmp_path, "agent", "learn-agent-async")
        out = _loads(await studio.aedit_agent("learn-agent-async", description="edited"))
        row = db.get_config(component_id="learn-agent-async", version=_edit_version(out))
        assert row["config"]["learning"] == {"name": "shared-brain"}

    def test_team_description_edit_preserves_unresolved_learning(self, tmp_path):
        db, studio = self._saved_with_unregistered_machine(tmp_path, "team", "learn-team")
        out = _loads(studio.edit_team("learn-team", description="edited"))
        row = db.get_config(component_id="learn-team", version=_edit_version(out))
        assert row["config"]["learning"] == {"name": "shared-brain"}

    @pytest.mark.asyncio
    async def test_async_team_description_edit_preserves_unresolved_learning(self, tmp_path):
        db, studio = self._saved_with_unregistered_machine(tmp_path, "team", "learn-team-async")
        out = _loads(await studio.aedit_team("learn-team-async", description="edited"))
        row = db.get_config(component_id="learn-team-async", version=_edit_version(out))
        assert row["config"]["learning"] == {"name": "shared-brain"}

    # -- visibility --------------------------------------------------------

    def test_inline_and_default_learning_stay_visible_in_the_view(self, registry, db):
        """Components stored before learning was authored by reference carry
        an inlined machine or the framework default; the preview must not hide
        that they learn, even though Studio cannot author either shape."""
        from agno.learn import LearningMachine

        Agent(
            id="inline-learn", name="I", model=OpenAIResponses(id="gpt-5.5"), learning=LearningMachine(user_memory=True)
        ).save(db=db)
        Agent(id="default-learn", name="D", model=OpenAIResponses(id="gpt-5.5"), learning=True).save(db=db)
        studio = StudioTools(registry=registry, db=db)

        assert _data(studio.get_component("inline-learn"))["learning"] == "inline"
        assert _data(studio.get_component("default-learn"))["learning"] is True
        assert "learning_name" not in _data(studio.get_component("inline-learn"))

    def test_named_inline_config_stays_inline_across_an_edit(self, registry, db):
        """A stored learning dict that carries a name PLUS store keys (the shape
        LearningMachine.to_dict() writes for a named machine, authorable over
        REST) is an inline machine, not a reference: the view says so, and an
        unrelated edit re-saves the stores instead of collapsing them to a
        bare reference no registry resolves."""
        from agno.db.base import ComponentType

        db.create_component_with_config(
            component_id="named-inline",
            component_type=ComponentType.AGENT,
            name="named-inline",
            config={
                "id": "named-inline",
                "name": "named-inline",
                "model": {"provider": "OpenAI", "id": "gpt-5.5"},
                "learning": {"name": "brain", "user_memory": True, "entity_memory": True, "namespace": "west"},
            },
            stage="published",
        )
        studio = StudioTools(registry=registry, db=db)
        assert _data(studio.get_component("named-inline"))["learning"] == "inline"

        out = _loads(studio.edit_agent("named-inline", description="edited", publish=True))
        after = db.get_config(component_id="named-inline", version=_edit_version(out))["config"]["learning"]
        assert after == {"user_memory": True, "entity_memory": True, "namespace": "west"}
        # and the new version still dispatches with no registry machine of that name
        from agno.os.utils import get_agent_by_id

        agent = get_agent_by_id("named-inline", agents=None, db=db, registry=registry)
        assert agent.learning.user_memory is True and agent.learning.name is None


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

    def test_first_publish_guard_accepts_zero_as_no_live_version(self, studio):
        """A component that has never been published has no live pointer; the
        guard spelled as 0 asserts exactly that and the publish lands as v1."""
        studio.create_agent(name="tutor", instructions="i", model_id="gpt-5.4")
        data = _data(studio.publish_component("tutor", version=1, expected_current_version=0))
        assert data["version"] == 1
        assert studio.db.get_component("tutor")["current_version"] == 1

    def test_first_publish_guard_zero_is_a_real_guard(self, studio):
        """0 is not "skip the check": once something is live it conflicts,
        retryable like any other genuine version conflict."""
        studio.create_agent(name="tutor", instructions="i", model_id="gpt-5.4", publish=True)
        studio.edit_agent("tutor", instructions="j")
        error = _error(studio.publish_component("tutor", expected_current_version=0))
        assert error["code"] == "version_conflict"
        assert error["retryable"] is True
        assert error["details"]["current_version"] == 1
        assert studio.db.get_component("tutor")["current_version"] == 1

    @pytest.mark.parametrize("expected", [1, -1, 7])
    def test_first_publish_guard_with_unsatisfiable_value_is_not_retryable(self, studio, expected):
        """No value but 0 can match a NULL live pointer, so the refusal is
        terminal and the message names the remedy (omit, or pass 0) rather
        than inviting a retry with a different number."""
        studio.create_agent(name="tutor", instructions="i", model_id="gpt-5.4")
        error = _error(studio.publish_component("tutor", version=1, expected_current_version=expected))
        assert error["code"] == "version_conflict"
        assert error["retryable"] is False
        assert error["details"]["current_version"] is None
        assert "has no live version yet" in error["message"]
        assert "pass 0" in error["message"]
        assert "Omit it" in error["message"]
        # Nothing was published: the draft is still the only version.
        assert studio.db.get_component("tutor")["current_version"] is None

    def test_first_publish_unguarded_still_publishes_v1(self, studio):
        studio.create_agent(name="tutor", instructions="i", model_id="gpt-5.4")
        assert _data(studio.publish_component("tutor", expected_current_version=None))["version"] == 1

    @pytest.mark.asyncio
    async def test_first_publish_guard_async_twin(self, studio):
        studio.create_agent(name="tutor", instructions="i", model_id="gpt-5.4")
        error = _error(await studio.apublish_component("tutor", version=1, expected_current_version=3))
        assert error["retryable"] is False
        data = _data(await studio.apublish_component("tutor", version=1, expected_current_version=0))
        assert data["version"] == 1

    def test_no_live_version_sentinel_is_int_only(self):
        from agno.db.base import current_version_matches, expects_no_live_version

        assert expects_no_live_version(0) is True
        assert expects_no_live_version(False) is False
        assert expects_no_live_version(1) is False
        assert current_version_matches(None, 0) is True
        assert current_version_matches(None, False) is False
        assert current_version_matches(1, True) is True  # unchanged lax behaviour, 1 == True

    def test_first_publish_guard_bool_is_not_the_sentinel(self, studio):
        """False == 0 in Python, but a boolean is not a version number: it
        must not pass as "nothing is live" (it never matched before either)."""
        studio.create_agent(name="tutor", instructions="i", model_id="gpt-5.4")
        error = _error(studio.publish_component("tutor", version=1, expected_current_version=False))
        assert error["code"] == "version_conflict"
        assert studio.db.get_component("tutor")["current_version"] is None

    def test_archive_guard_on_unpublished_component(self, studio):
        """archive_component takes the same guard and had the same dead end:
        a non-zero value against a NULL pointer is terminal with the remedy,
        0 archives, and neither path writes on refusal."""
        studio.create_agent(name="tutor", instructions="i", model_id="gpt-5.4")
        error = _error(studio.archive_component("tutor", expected_current_version=1))
        assert error["code"] == "version_conflict"
        assert error["retryable"] is False
        assert "pass 0" in error["message"]
        assert studio.db.get_component("tutor") is not None
        out = _loads(studio.archive_component("tutor", expected_current_version=0))
        assert out["status"] == "archived"
        assert studio.db.get_component("tutor") is None

    @pytest.mark.asyncio
    async def test_archive_guard_on_unpublished_component_async_twin(self, studio):
        studio.create_agent(name="tutor", instructions="i", model_id="gpt-5.4")
        error = _error(await studio.aarchive_component("tutor", expected_current_version=2))
        assert error["retryable"] is False
        out = _loads(await studio.aarchive_component("tutor", expected_current_version=0))
        assert out["status"] == "archived"

    def test_archive_guard_on_published_component_is_a_real_conflict(self, studio):
        studio.create_agent(name="tutor", instructions="i", model_id="gpt-5.4", publish=True)
        error = _error(studio.archive_component("tutor", expected_current_version=0))
        assert error["code"] == "version_conflict"
        assert error["retryable"] is True
        assert studio.db.get_component("tutor") is not None

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
# version: 0 -- models fill an Optional[int] documented "omit for the
# latest" with 0. Versions start at 1, so on a "which version" argument 0
# only ever means "unset"; on the expected_current_version guard it means
# "nothing is live" and must keep meaning that.
# ----------------------------------------------------------------------


class TestVersionZero:
    def _published(self, studio, name="tutor"):
        studio.create_agent(name=name, instructions="orig", model_id="gpt-5.4", publish=True)

    def test_get_component_treats_version_zero_as_latest(self, studio):
        """0 reads like an omitted argument instead of failing version_not_found."""
        self._published(studio)
        data = _data(studio.get_component("tutor", version=0))
        assert data["version"] == 1
        assert data["instructions"] == "orig"

    def test_get_component_version_zero_matches_omitting_it(self, studio):
        """Same answer as the documented spelling, drafts included."""
        self._published(studio)
        studio.edit_agent("tutor", instructions="updated")
        assert _data(studio.get_component("tutor", version=0)) == _data(studio.get_component("tutor"))

    def test_explicit_version_still_pins(self, studio):
        """The coercion is for 0 alone: a real version still selects itself."""
        self._published(studio)
        studio.edit_agent("tutor", instructions="updated")
        assert _data(studio.get_component("tutor", version=1))["instructions"] == "orig"
        assert _data(studio.get_component("tutor", version=2))["instructions"] == "updated"

    def test_negative_version_is_still_an_error(self, studio):
        """-1 is a wrong number, not an unset argument; it must not be coerced."""
        self._published(studio)
        assert _error(studio.get_component("tutor", version=-1))["code"] == "version_not_found"

    def test_unknown_version_is_still_an_error(self, studio):
        self._published(studio)
        assert _error(studio.get_component("tutor", version=99))["code"] == "version_not_found"

    @pytest.mark.asyncio
    async def test_aget_component_treats_version_zero_as_latest(self, studio):
        self._published(studio)
        assert _data(await studio.aget_component("tutor", version=0))["version"] == 1

    def test_publish_component_treats_version_zero_as_latest_draft(self, studio):
        """publish_component(version=0) publishes the newest draft, the same
        as omitting it, instead of failing version_not_found."""
        self._published(studio)
        studio.edit_agent("tutor", instructions="updated")
        assert _data(studio.publish_component("tutor", version=0))["version"] == 2

    def test_publish_component_says_it_reinterpreted_version_zero(self, studio):
        """Publishing moves the live pointer, so a caller whose argument was
        reinterpreted hears it on the envelope, not only in a debug log."""
        self._published(studio)
        studio.edit_agent("tutor", instructions="updated")
        out = _loads(studio.publish_component("tutor", version=0))
        assert any("version=0" in w for w in out["warnings"])

    def test_publish_component_is_silent_when_the_version_was_not_reinterpreted(self, studio):
        self._published(studio)
        studio.edit_agent("tutor", instructions="updated")
        out = _loads(studio.publish_component("tutor", version=2))
        assert not any("version=0" in w for w in out.get("warnings") or [])

    @pytest.mark.asyncio
    async def test_apublish_component_treats_version_zero_as_latest_draft(self, studio):
        self._published(studio)
        studio.edit_agent("tutor", instructions="updated")
        assert _data(await studio.apublish_component("tutor", version=0))["version"] == 2

    def test_validate_component_treats_version_zero_as_latest(self, studio):
        studio.create_agent(name="clean", instructions="i", model_id="gpt-5.4")
        data = _data(studio.validate_component("clean", version=0))
        assert data["valid"] is True
        assert data["version"] == 1

    @pytest.mark.asyncio
    async def test_avalidate_component_treats_version_zero_as_latest(self, studio):
        studio.create_agent(name="clean", instructions="i", model_id="gpt-5.4")
        assert _data(await studio.avalidate_component("clean", version=0))["version"] == 1

    @pytest.mark.parametrize("tool_name", ["edit_agent", "edit_team", "edit_workflow"])
    def test_edit_expected_version_zero_is_still_refused(self, studio, tool_name):
        """expected_version is a compare-and-set, not a version selector. 0 can
        never match a latest version, and refusing is the safe direction: reading
        it as "unset" would turn a guard the caller asked for into an unguarded
        append."""
        studio.create_agent(name="member", instructions="m", model_id="gpt-5.4", publish=True)
        targets = {
            "edit_agent": lambda: studio.create_agent(name="cas", instructions="i", model_id="gpt-5.4"),
            "edit_team": lambda: studio.create_team(name="cas", instructions="i", member_ids=["member"]),
            "edit_workflow": lambda: studio.create_workflow(name="cas", steps=[{"name": "s1", "agent_id": "member"}]),
        }
        targets[tool_name]()
        error = _error(getattr(studio, tool_name)("cas", description="second", expected_version=0))
        assert error["code"] == "version_conflict"
        # Nothing was appended: the refusal is not a partial write.
        assert _data(studio.list_versions("cas"))["count"] == 1

    def test_edit_expected_version_still_guards(self, studio):
        """The coercion must not blunt a real compare-and-set."""
        studio.create_agent(name="cas", instructions="i", model_id="gpt-5.4")
        assert _error(studio.edit_agent("cas", description="x", expected_version=7))["code"] == "version_conflict"
        assert _data(studio.edit_agent("cas", description="x", expected_version=1))["draft_version"] == 2

    @pytest.mark.asyncio
    async def test_aedit_agent_expected_version_zero_is_still_refused(self, studio):
        studio.create_agent(name="cas", instructions="i", model_id="gpt-5.4")
        error = _error(await studio.aedit_agent("cas", description="x", expected_version=0))
        assert error["code"] == "version_conflict"

    def test_run_agent_version_zero_dispatches_unpinned(self, studio, monkeypatch):
        """The run tools take the same "omit for the latest" argument. 0 must
        reach the ordinary dispatch, not the exact-version preview path that
        answers version_not_found."""
        studio.create_agent(name="member", instructions="m", model_id="gpt-5.4", publish=True)
        seen = []

        def _runner(identifier, message, **kwargs):
            seen.append((identifier, message))
            return json.dumps({"agent_id": identifier, "content": "ok"})

        monkeypatch.setattr(studio._runner_tools, "run_agent", _runner)
        out = _loads(studio.run_agent("member", "hi", version=0))
        assert seen == [("member", "hi")]
        assert out["content"] == "ok"

    @pytest.mark.asyncio
    async def test_arun_agent_version_zero_dispatches_unpinned(self, studio, monkeypatch):
        """The async twin has its own dispatch body, so it needs its own pin."""
        studio.create_agent(name="member", instructions="m", model_id="gpt-5.4", publish=True)
        seen = []

        async def _runner(identifier, message, **kwargs):
            seen.append((identifier, message))
            return json.dumps({"agent_id": identifier, "content": "ok"})

        monkeypatch.setattr(studio._runner_tools, "arun_agent", _runner)
        out = _loads(await studio.arun_agent("member", "hi", version=0))
        assert seen == [("member", "hi")]
        assert out["content"] == "ok"

    def test_run_agent_explicit_version_still_previews(self, studio):
        """Guard against the coercion swallowing a real pin."""
        studio.create_agent(name="member", instructions="m", model_id="gpt-5.4", publish=True)
        assert _error(studio.run_agent("member", "hi", version=9))["code"] == "version_not_found"

    def test_first_publish_guard_zero_still_means_nothing_is_live(self, studio):
        """expected_current_version is NOT a "which version" argument: 0 is
        the documented "I expect no live version" guard and stays a guard."""
        studio.create_agent(name="tutor", instructions="i", model_id="gpt-5.4")
        assert _data(studio.publish_component("tutor", version=1, expected_current_version=0))["version"] == 1

    def test_archive_guard_zero_still_conflicts_against_a_live_pointer(self, studio):
        """The counterpart: 0 against a published component is a real
        conflict, not a skipped check."""
        self._published(studio)
        error = _error(studio.archive_component("tutor", expected_current_version=0))
        assert error["code"] == "version_conflict"
        assert studio.db.get_component("tutor") is not None

    def test_required_version_argument_rejects_zero(self, studio):
        """set_current_version and delete_version name a version to act on and
        have no "latest" default, so 0 stays the error it is."""
        self._published(studio)
        assert _error(studio.set_current_version("tutor", 0))["code"] == "version_not_found"
        assert _error(studio.delete_version("tutor", 0))["code"] == "version_not_found"

    def test_version_zero_coercion_does_not_swallow_false(self, studio):
        """False == 0 in Python but a boolean is not an omitted version; the
        sentinel helper already refuses it and the coercion must too."""
        self._published(studio)
        assert _error(studio.get_component("tutor", version=False))["code"] == "version_not_found"


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
        tool = StudioTools(registry=registry, db=db, include_agents=[live], schedules=True)

        out = self._create_schedule(tool, target_id="Live Agent")
        assert out["status"] == "created"
        assert out["target_id"] == "live-agent"
        assert out["endpoint"] == "/agents/live-agent/runs"

    def test_unknown_target_returns_error(self, studio_schedules):
        out = self._create_schedule(studio_schedules, target_id="ghost")
        assert out["error"]["code"] == "component_not_found"
        assert "Agent not found: ghost" in out["error"]["message"]

    def test_bad_target_type_returns_error(self, studio_schedules):
        # A malformed target_type is a malformed argument, not a missing
        # component: nothing was looked up, so component_not_found said
        # something untrue and disagreed with the message beside it.
        self._create_target_agent(studio_schedules)
        out = self._create_schedule(studio_schedules, target_type="cron-job")
        assert out["error"]["code"] == "invalid_request"
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
        # Create means create: a reused name can
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

    def test_update_schedule_rejects_an_invalid_cron(self, studio_schedules, db):
        # manager.update is a bare passthrough: without validation here a typo'd
        # cron is reported as success, fires once at the stale time, and is then
        # force-disabled by the executor with no disabled_reason.
        self._create_target_agent(studio_schedules)
        created = self._create_schedule(studio_schedules)
        before = db.get_schedule(created["id"])

        out = _loads(studio_schedules.update_schedule(created["id"], cron="not-a-cron"))
        assert out["error"]["code"] == "invalid_request"
        assert "Invalid cron expression" in out["error"]["message"]

        after = db.get_schedule(created["id"])
        assert after["cron_expr"] == before["cron_expr"]
        assert after["next_run_at"] == before["next_run_at"]

    def test_update_schedule_rejects_an_invalid_timezone(self, studio_schedules, db):
        self._create_target_agent(studio_schedules)
        created = self._create_schedule(studio_schedules)
        before = db.get_schedule(created["id"])

        out = _loads(studio_schedules.update_schedule(created["id"], timezone="Mars/Olympus"))
        assert out["error"]["code"] == "invalid_request"
        assert "Invalid timezone" in out["error"]["message"]

        assert db.get_schedule(created["id"])["timezone"] == before["timezone"]

    def test_update_schedule_recomputes_next_run_at(self, studio_schedules, db):
        # Without the recompute the old cadence fires once more before the new
        # one takes effect.
        self._create_target_agent(studio_schedules)
        created = self._create_schedule(studio_schedules, cron="0 9 * * *")

        out = _loads(studio_schedules.update_schedule(created["id"], cron="*/5 * * * *"))
        assert out["ok"], out

        after = db.get_schedule(created["id"])
        assert after["cron_expr"] == "*/5 * * * *"
        # The new cadence has to be what next_run_at reflects, so assert it
        # lands inside that cadence rather than merely differing from the old
        # value. The old daily cron and a five-minute one name the SAME instant
        # for the five minutes before 09:00, so an inequality fails there for a
        # reason that has nothing to do with the recompute.
        assert after["next_run_at"] <= int(time.time()) + 300
        assert out["data"]["next_run_at"] == after["next_run_at"]

    def test_update_schedule_validates_cron_against_the_new_timezone(self, studio_schedules, db):
        # A timezone-only change still recomputes: the same cron in a new zone is
        # a different wall-clock next run.
        self._create_target_agent(studio_schedules)
        created = self._create_schedule(studio_schedules, cron="0 9 * * *", timezone="UTC")
        before = db.get_schedule(created["id"])

        out = _loads(studio_schedules.update_schedule(created["id"], timezone="America/New_York"))
        assert out["ok"], out

        after = db.get_schedule(created["id"])
        assert after["timezone"] == "America/New_York"
        assert after["next_run_at"] != before["next_run_at"]

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

    def test_archive_by_another_owners_draft_display_name_answers_as_if_absent(self, studio):
        from agno.run.base import RunContext

        alice = RunContext(run_id="r1", session_id="s1", user_id="alice")
        bob = RunContext(run_id="r2", session_id="s2", user_id="bob")

        # Bob's answer for a name that exists nowhere is the control.
        absent = studio.archive_component("Quarterly Secrets", _agno_run_context=bob)
        studio.create_agent(
            name="Quarterly Secrets", instructions="i", model_id="gpt-5.4", publish=False, _agno_run_context=alice
        )

        # Alice's draft is hers alone, so the same call must stay byte-identical
        # to the control: a differing refusal would report whose names exist.
        assert studio.archive_component("Quarterly Secrets", _agno_run_context=bob) == absent
        assert _error(absent)["code"] == "component_not_found"

        # Published, the name is on the platform and resolves for Bob too - but
        # the archive itself is still refused, now for the honest reason.
        studio.publish_component("quarterly-secrets", _agno_run_context=alice)
        denied = _error(studio.archive_component("quarterly-secrets", _agno_run_context=bob))
        assert denied["code"] == "not_owner", denied

        # The owner still resolves her own display name.
        owner_error = _error(studio.archive_component("Quarterly Secrets", _agno_run_context=alice))
        assert owner_error["code"] == "invalid_request"
        assert "quarterly-secrets" in owner_error["message"]
        assert _loads(studio.archive_component("quarterly-secrets", _agno_run_context=alice))["status"] == "archived"

    @pytest.mark.asyncio
    async def test_async_archive_by_another_owners_draft_display_name_answers_as_if_absent(self, studio):
        from agno.run.base import RunContext

        alice = RunContext(run_id="r1", session_id="s1", user_id="alice")
        bob = RunContext(run_id="r2", session_id="s2", user_id="bob")

        absent = await studio.aarchive_component("Quarterly Secrets", _agno_run_context=bob)
        studio.create_agent(
            name="Quarterly Secrets", instructions="i", model_id="gpt-5.4", publish=False, _agno_run_context=alice
        )

        assert await studio.aarchive_component("Quarterly Secrets", _agno_run_context=bob) == absent
        assert _error(absent)["code"] == "component_not_found"

        studio.publish_component("quarterly-secrets", _agno_run_context=alice)
        denied = _error(await studio.aarchive_component("quarterly-secrets", _agno_run_context=bob))
        assert denied["code"] == "not_owner", denied

        owner_error = _error(await studio.aarchive_component("Quarterly Secrets", _agno_run_context=alice))
        assert owner_error["code"] == "invalid_request"
        assert "quarterly-secrets" in owner_error["message"]
        archived = await studio.aarchive_component("quarterly-secrets", _agno_run_context=alice)
        assert _loads(archived)["status"] == "archived"

    def test_archive_refuses_while_a_dependent_pins_the_component(self, registry, db):
        tool = StudioTools(registry=registry, db=db)
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

        tool = StudioTools(registry=registry, db=db, include_agents=[ShadowAgent()])

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
        tool = StudioTools(registry=registry, db=db, include_agents=[live])
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
        tool = StudioTools(registry=registry, db=db, include_agents=[live])

        error = _error(tool.edit_agent(agent_id="shared", instructions="updated-live"))

        assert error["code"] == "invalid_request"
        assert "code-defined" in error["message"]
        assert live.instructions == "live"


# ----------------------------------------------------------------------
# Type guards and the exactness of the tools view
# ----------------------------------------------------------------------


class TestTypeGuards:
    def _full(self, registry, db):
        return StudioTools(registry=registry, db=db)

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
    def test_every_component_type_is_buildable_by_default(self, registry, db):
        tool = StudioTools(registry=registry, db=db)
        assert tool.enable_agents is True
        assert tool.enable_teams is True
        assert tool.enable_workflows is True
        names = set(tool.functions.keys())
        assert "create_agent" in names
        assert "create_team" in names
        assert "create_workflow" in names

    def test_a_type_can_be_kept_out_of_the_palette(self, registry, db):
        tool = StudioTools(registry=registry, db=db, create_teams=False)
        assert tool.enable_agents is True
        assert tool.enable_teams is False
        assert tool.enable_workflows is True
        names = set(tool.functions.keys())
        assert "create_team" not in names
        assert "create_agent" in names

    def test_agents_can_be_disabled_while_teams_stay_buildable(self, registry, db):
        tool = StudioTools(registry=registry, db=db, create_agents=False)
        assert tool.enable_agents is False
        assert tool.enable_teams is True
        names = set(tool.functions.keys())
        assert "create_agent" not in names
        assert "create_team" in names

    def test_workflows_only(self, registry, db):
        tool = StudioTools(registry=registry, db=db, create_agents=False, create_teams=False)
        assert tool.enable_workflows is True
        names = set(tool.functions.keys())
        assert "create_workflow" in names
        assert "create_agent" not in names

    def test_the_include_lists_do_not_decide_the_palette(self, registry, db):
        """Passing live components says what EXISTS, not what may be built.

        The two used to be entangled: passing a list auto-enabled the types you
        could build from it. Every type is buildable by default now, so the
        lists carry one meaning only.
        """
        tool = StudioTools(registry=registry, db=db, include_agents=[], create_workflows=False)
        assert tool.enable_agents is True
        assert tool.enable_teams is True
        assert tool.enable_workflows is False

    def test_discovery_tools_always_registered(self, registry, db):
        # Even with everything disabled, discovery tools stay registered.
        tool = StudioTools(registry=registry, db=db, create_agents=False, create_teams=False, create_workflows=False)
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

    def run(self, message, stream=None, user_id=None, session_id=None, metadata=None, run_id=None):
        return _StubRunOutput()

    async def arun(self, message, stream=None, user_id=None, session_id=None, metadata=None, run_id=None):
        return _StubRunOutput()

    def deep_copy(self):
        # A distinct instance that shares state, the shape _fresh_copy accepts.
        clone = object.__new__(type(self))
        clone.__dict__ = self.__dict__
        return clone


class TestRunSerialization:
    def test_run_agent_serializes_non_json_content(self, registry, db):
        tool = StudioTools(registry=registry, db=db, include_agents=[_StubAgent()])
        out = _loads(_tool(tool, "run_agent")("stub", "hi"))
        assert "error" not in out
        assert out["content"].startswith("2026-01-01")

    @pytest.mark.asyncio
    async def test_arun_agent_serializes_non_json_content(self, registry, db):
        tool = StudioTools(registry=registry, db=db, include_agents=[_StubAgent()])
        out = _loads(await tool.async_functions["run_agent"].entrypoint("stub", "hi"))
        assert "error" not in out
        assert out["content"].startswith("2026-01-01")


# ----------------------------------------------------------------------
# Non-cascading persistence: code-defined members should NOT land in DB
# ----------------------------------------------------------------------


class TestNoCascadePersistence:
    def test_create_team_does_not_persist_code_defined_member(self, registry, db):
        greeter = Agent(id="greeter-code", name="Greeter", model=OpenAIResponses(id="gpt-5.4"))
        tool = StudioTools(registry=registry, db=db, include_agents=[greeter])

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
        tool = StudioTools(registry=registry, db=db, include_agents=[greeter])

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

    def test_description_edit_preserves_unresolved_memory_manager(self, tmp_path):
        from agno.memory.manager import MemoryManager

        class FakeKnowledge:
            name = "handbook"

        db = SqliteDb(db_file=str(tmp_path / "preserve_mm.db"))
        Agent(
            id="mm-agent",
            name="M",
            model=OpenAIResponses(id="gpt-5.5"),
            memory_manager=MemoryManager(id="mm-stable"),
            knowledge=FakeKnowledge(),
        ).save(db=db)

        # Empty registry: neither reference resolves, so the lenient load drops both.
        studio = StudioTools(registry=Registry(), db=db)
        out = _loads(studio.edit_agent("mm-agent", description="edited"))
        assert out.get("status") == "edited"

        row = db.get_config(component_id="mm-agent", version=_edit_version(out))
        assert row["config"]["memory_manager"] == {"registry_id": "mm-stable"}
        assert row["config"]["knowledge"] == {"name": "handbook"}

    @pytest.mark.asyncio
    async def test_async_description_edit_preserves_unresolved_memory_manager(self, tmp_path):
        from agno.memory.manager import MemoryManager

        class FakeKnowledge:
            name = "handbook"

        db = SqliteDb(db_file=str(tmp_path / "preserve_mm_async.db"))
        Agent(
            id="mm-agent-async",
            name="M",
            model=OpenAIResponses(id="gpt-5.5"),
            memory_manager=MemoryManager(id="mm-stable"),
            knowledge=FakeKnowledge(),
        ).save(db=db)

        studio = StudioTools(registry=Registry(), db=db)
        out = _loads(await studio.aedit_agent("mm-agent-async", description="edited"))
        assert out.get("status") == "edited"

        row = db.get_config(component_id="mm-agent-async", version=_edit_version(out))
        assert row["config"]["memory_manager"] == {"registry_id": "mm-stable"}
        assert row["config"]["knowledge"] == {"name": "handbook"}

    def test_team_description_edit_preserves_unresolved_memory_manager(self, tmp_path):
        from agno.memory.manager import MemoryManager
        from agno.team.team import Team

        class FakeKnowledge:
            name = "handbook"

        db = SqliteDb(db_file=str(tmp_path / "preserve_mm_team.db"))
        Team(
            id="mm-team",
            name="T",
            members=[Agent(id="mm-team-member", name="Member")],
            memory_manager=MemoryManager(id="mm-stable"),
            knowledge=FakeKnowledge(),
        ).save(db=db)

        studio = StudioTools(registry=Registry(), db=db)
        out = _loads(studio.edit_team("mm-team", description="edited"))
        assert out.get("status") == "edited"

        row = db.get_config(component_id="mm-team", version=_edit_version(out))
        assert row["config"]["memory_manager"] == {"registry_id": "mm-stable"}
        assert row["config"]["knowledge"] == {"name": "handbook"}

    @pytest.mark.asyncio
    async def test_async_team_description_edit_preserves_unresolved_memory_manager(self, tmp_path):
        from agno.memory.manager import MemoryManager
        from agno.team.team import Team

        class FakeKnowledge:
            name = "handbook"

        db = SqliteDb(db_file=str(tmp_path / "preserve_mm_team_async.db"))
        Team(
            id="mm-team-async",
            name="T",
            members=[Agent(id="mm-team-member-async", name="Member")],
            memory_manager=MemoryManager(id="mm-stable"),
            knowledge=FakeKnowledge(),
        ).save(db=db)

        studio = StudioTools(registry=Registry(), db=db)
        out = _loads(await studio.aedit_team("mm-team-async", description="edited"))
        assert out.get("status") == "edited"

        row = db.get_config(component_id="mm-team-async", version=_edit_version(out))
        assert row["config"]["memory_manager"] == {"registry_id": "mm-stable"}
        assert row["config"]["knowledge"] == {"name": "handbook"}

    def test_team_edit_repins_members(self, tmp_path):
        from agno.team.team import Team

        db = SqliteDb(db_file=str(tmp_path / "repin_team.db"))
        member = Agent(id="rp-member", name="Member")
        Team(id="rp-team", name="Team", members=[member]).save(db=db)

        studio = StudioTools(registry=Registry(), db=db)
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

        studio = StudioTools(registry=Registry(), db=db)
        out = _loads(studio.edit_workflow("rw-wf", description="edited"))
        assert out.get("status") == "edited"

        links = db.get_links(component_id="rw-wf", version=_edit_version(out))
        assert "rw-agent" in [link["child_component_id"] for link in links]


class TestSnapshotSafety:
    def test_create_team_pins_members_at_creation(self, tmp_path):
        db = SqliteDb(db_file=str(tmp_path / "create_pin.db"))
        Agent(id="cp-member", name="Member").save(db=db)
        model = OpenAIResponses(id="gpt-5.5")
        studio = StudioTools(registry=Registry(models=[model], dbs=[db]), db=db)

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

        studio = StudioTools(registry=Registry(dbs=[db]), db=db)
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

        studio = StudioTools(registry=Registry(dbs=[db]), db=db)
        out = _loads(studio.edit_workflow("si-wf", description="edited"))
        assert out.get("status") == "edited"

        version = _edit_version(out)
        new_config = db.get_config(component_id="si-wf", version=version)["config"]
        assert [s["step_id"] for s in new_config["steps"]] == base_ids
        link_keys = {link["link_key"] for link in db.get_links(component_id="si-wf", version=version)}
        assert link_keys <= set(base_ids)

    def test_description_edit_keeps_auxiliary_model_keys(self, tmp_path):
        """parser/output models are emitted by to_dict but not yet consumed by
        from_dict; an unrelated edit must not persist their loss. The
        reasoning model reconstructs now, so it survives by round-tripping
        (re-serialized with the full provider/id/name shape)."""
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
        assert {k: config["reasoning_model"][k] for k in aux} == aux
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

        studio = StudioTools(registry=Registry(dbs=[db]), db=db, include_agents=[code_agent])
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

        studio = StudioTools(registry=Registry(dbs=[db]), db=db, include_agents=[lookalike_agent])
        links = studio._links_for_component(parent)

        nested = [link for link in links if link["link_kind"] == "step_workflow"]
        assert nested and nested[0]["child_component_id"] == "sub-flow"


class TestMemberBinding:
    """The single-catalog binder invariants (the multi-db db_id selector is
    gone; everything binds against the one catalog db)."""

    def _studio(self, db, **kwargs):
        model = OpenAIResponses(id="gpt-5.5")
        registry = Registry(models=[model], dbs=[db])
        return StudioTools(registry=registry, db=db, **kwargs)

    def test_create_refuses_an_id_claimed_by_code_and_the_db(self, tmp_path):
        db = SqliteDb(id="cat", db_file=str(tmp_path / "amb.db"))
        Agent(id="both", name="DB Row").save(db=db)
        code_agent = Agent(id="both", name="Live Code")
        studio = self._studio(db, include_agents=[code_agent])

        error = _error(studio.create_team(name="AT", instructions="i", member_ids=["both"], model_id="gpt-5.5"))

        assert error["code"] == "invalid_request"
        assert "claimed by both" in error["message"]

    def test_agents_list_member_survives_a_strict_reload(self, tmp_path):
        """List members mirror into the registry, so a stored reference to
        them rehydrates instead of vanishing."""
        from agno.team.team import get_team_by_id

        db = SqliteDb(id="cat", db_file=str(tmp_path / "list.db"))
        list_agent = Agent(id="listed", name="Listed")
        studio = self._studio(db, include_agents=[list_agent])

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
            StudioTools(registry=Registry(agents=[registry_agent]), include_agents=[list_agent])

        # The same object in both places is consistent and accepted.
        shared = Agent(id="shared", name="Shared")
        StudioTools(registry=Registry(agents=[shared]), include_agents=[shared])

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
        studio = StudioTools(registry=Registry(models=[model], dbs=[db]), db=db, include_agents=[code_agent])

        error = _error(studio.edit_workflow("ew-wf", steps=[{"name": "s1", "agent_id": "amb"}]))

        assert "claimed by both" in error["message"]

    def test_create_pins_the_version_the_binder_selected(self, tmp_path):
        """The binder's verified snapshot decides the pin: a publish between
        its reads refuses, a publish after them stays self-consistent."""
        db = SqliteDb(id="cat", db_file=str(tmp_path / "snap.db"))
        member = Agent(id="sn-member", name="M", description="v1")
        member.save(db=db)
        model = OpenAIResponses(id="gpt-5.5")
        studio = StudioTools(registry=Registry(models=[model], dbs=[db]), db=db)

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
        studio = StudioTools(registry=Registry(models=[model], dbs=[db]), db=db, include_agents=live)
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
        studio = StudioTools(registry=Registry(models=[model], dbs=[db]), db=db, include_agents=live)
        live[0] = Agent(id="swap", name="Replacement")

        error = _error(studio.create_team(name="RL", instructions="i", member_ids=["swap"], model_id="gpt-5.5"))

        assert "not the registry's object" in error["message"]

    def test_publishing_create_refuses_a_draft_only_child(self, tmp_path):
        from agno.db.base import ComponentType

        db = SqliteDb(id="cat", db_file=str(tmp_path / "draft.db"))
        db.upsert_component(component_id="draft-child", component_type=ComponentType.AGENT, name="D")
        db.upsert_config(component_id="draft-child", config={"id": "draft-child", "name": "D"}, stage="draft")
        model = OpenAIResponses(id="gpt-5.5")
        studio = StudioTools(registry=Registry(models=[model], dbs=[db]), db=db)

        error = _error(
            studio.create_team(
                name="DC", instructions="i", member_ids=["draft-child"], model_id="gpt-5.5", publish=True
            )
        )

        assert "Publish the child first" in error["message"]


# ----------------------------------------------------------------------
# Published parents pin published children (enforced at the promote gate)
# ----------------------------------------------------------------------


class TestPublishedParentsPinPublishedChildren:
    """A draft child can change in place under a published parent's pin, so
    every surface that promotes a parent must refuse while a pinned member or
    step child is a draft. The gate lives in the adapters' upsert_config
    promote transition, so Studio publish, edit+publish, and REST PATCH all
    hit it; the create-time binder additionally refuses nested drafts."""

    @pytest.fixture
    def studio3(self, registry, db):
        return StudioTools(registry=registry, db=db)

    def _draft_agent(self, studio, name="pinned-child"):
        return _data(studio.create_agent(name=name, instructions="i", model_id="gpt-5.4"))["id"]

    def test_publish_component_refuses_draft_member(self, studio3):
        child = self._draft_agent(studio3)
        team = _data(studio3.create_team(name="pin-team", instructions="i", member_ids=[child]))
        out = _loads(studio3.publish_component(team["id"]))
        assert out["error"]["code"] == "dependency_conflict", out
        assert child in out["error"]["message"]

    def test_edit_publish_refuses_untouched_draft_member(self, studio3):
        child = self._draft_agent(studio3)
        team = _data(studio3.create_team(name="pin-team-2", instructions="i", member_ids=[child]))
        out = _loads(studio3.edit_team(team["id"], instructions="new", publish=True))
        assert out["error"]["code"] == "dependency_conflict", out

    def test_publish_succeeds_after_child_publishes(self, studio3):
        child = self._draft_agent(studio3)
        team = _data(studio3.create_team(name="pin-team-3", instructions="i", member_ids=[child]))
        assert _loads(studio3.publish_component(child))["ok"]
        assert _loads(studio3.publish_component(team["id"]))["ok"]

    @pytest.mark.parametrize(
        "wrap",
        [
            lambda inner: {"type": "parallel", "name": "p", "steps": [inner]},
            lambda inner: {"type": "loop", "name": "l", "max_iterations": 2, "steps": [inner]},
            lambda inner: {"type": "steps", "name": "g", "steps": [inner]},
            lambda inner: {
                "type": "condition",
                "name": "c",
                "evaluator_function": "1 > 0",
                "steps": [{"name": "main-leaf", "agent_id": "__OK__"}],
                "else_steps": [inner],
            },
            lambda inner: {
                "type": "router",
                "name": "r",
                "selector_function": "'x'",
                "choices": [inner],
            },
        ],
        ids=["parallel", "loop", "steps", "condition-else", "router-choice"],
    )
    def test_nested_draft_child_refused_in_every_compound_type(self, studio3, wrap):
        child = self._draft_agent(studio3)
        ok_child = self._draft_agent(studio3, name="ok-leaf-agent")
        assert _loads(studio3.publish_component(ok_child))["ok"]
        inner = {"name": "leaf", "agent_id": child}
        spec = json.loads(json.dumps(wrap(inner)).replace("__OK__", ok_child))
        out = _loads(studio3.create_workflow(name="nested-wf", steps=[spec], publish=True))
        assert not out["ok"], out
        assert child in out["error"]["message"]

    def test_nested_published_child_passes(self, studio3):
        child = self._draft_agent(studio3, name="published-leaf")
        assert _loads(studio3.publish_component(child))["ok"]
        out = _loads(
            studio3.create_workflow(
                name="nested-ok-wf",
                steps=[{"type": "loop", "name": "l", "max_iterations": 2, "steps": [{"name": "s", "agent_id": child}]}],
                publish=True,
            )
        )
        assert out["ok"], out


# ----------------------------------------------------------------------
# Adapters without the component catalog (Mongo-shaped)
# ----------------------------------------------------------------------


class TestNoCatalogAdapter:
    """Mongo implements schedules but not the component catalog: catalog
    reads raise NotImplementedError. Scheduling a code-defined target must
    keep working (the target check treats no-catalog as live), and catalog
    tools must answer with a capability error, not internal_error."""

    @pytest.fixture
    def no_catalog_db(self, tmp_path):
        class NoCatalogDb(SqliteDb):
            def get_component(self, *args, **kwargs):
                raise NotImplementedError

        return NoCatalogDb(id="no-catalog", db_file=str(tmp_path / "nocat.db"))

    def test_create_schedule_for_code_defined_target_still_works(self, registry, no_catalog_db):
        live = Agent(id="live-agent", name="Live Agent", model=OpenAIResponses(id="gpt-5.4"))
        studio = StudioTools(registry=registry, db=no_catalog_db, include_agents=[live], schedules=True)
        out = _loads(
            studio.create_schedule(
                name="code-target",
                cron="0 9 * * *",
                target_type="agent",
                target_id="live-agent",
                message="m",
            )
        )
        assert out["ok"], out
        assert out["data"]["endpoint"] == "/agents/live-agent/runs"

    def test_archive_answers_capability_error_not_internal(self, registry, no_catalog_db):
        studio = StudioTools(registry=registry, db=no_catalog_db)
        out = _loads(studio.archive_component("anything"))
        assert out["error"]["code"] in ("db_not_configured", "component_not_found"), out
        assert out["error"]["code"] != "internal_error"


class TestStudioGuardedWriteRaces:
    def test_two_guarded_edits_produce_exactly_one_conflict(self, studio):
        # The guard must ride the adapter write: with a Python-side compare
        # both editors read latest=1, both pass, and drafts v2 AND v3 land
        # with zero conflicts.
        import threading

        _data(studio.create_agent(name="race-agent", instructions="v1", model_id="gpt-5.4"))
        barrier = threading.Barrier(2)
        results: list = [None, None]

        def edit(slot, text):
            barrier.wait()
            results[slot] = _loads(studio.edit_agent("race-agent", instructions=text, expected_version=1))

        threads = [threading.Thread(target=edit, args=(i, f"edit-{i}")) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        codes = sorted(("ok" if r.get("ok") else r["error"]["code"]) for r in results)
        assert codes == ["ok", "version_conflict"], results


class TestAsyncRunTwins:
    @pytest.mark.asyncio
    async def test_async_preview_awaits_arun_not_run(self, studio, monkeypatch):
        # The async twins must run the target's arun on the event loop; a
        # thread-wrapped sync run skips async hooks and tools entirely.
        _data(studio.create_agent(name="async-previewed", instructions="v1", model_id="gpt-5.4"))

        class ArunOnly:
            id = "async-previewed"

            def run(self, *a, **k):
                raise AssertionError("sync run must not be called by the async preview")

            async def arun(self, *a, **k):
                class R:
                    run_id = "r1"
                    session_id = "s1"
                    status = "COMPLETED"
                    content = "from-arun"

                return R()

        monkeypatch.setattr(studio._runner_tools, "_load_agent_from_db", lambda *a, **k: ArunOnly())
        out = _loads(await studio.arun_agent("async-previewed", "hi", version=1))
        assert out.get("content") == "from-arun", out


class TestTemplateContract:
    """The agentos-railway template's exact construction and boot calls: a
    signature change that breaks the deployed template must break here first,
    not on Railway."""

    def test_default_confirmation_set_covers_the_deletion_shaped_tools(self, registry, db):
        studio = StudioTools(registry=registry, db=db, versions=True, schedules=True)
        confirm = set(getattr(studio, "requires_confirmation_tools", []) or [])
        assert {"archive_component", "delete_version", "delete_schedule"} <= confirm
        # and NOT the additive, reversible operations
        assert "create_agent" not in confirm
        assert "publish_component" not in confirm

    def test_confirmation_default_only_includes_registered_tools(self, registry, db):
        # Without schedules, delete_schedule is not registered, so it must not
        # appear in the default confirmation set.
        studio = StudioTools(registry=registry, db=db, schedules=False)
        confirm = set(getattr(studio, "requires_confirmation_tools", []) or [])
        assert "delete_schedule" not in confirm

    def test_consumer_can_clear_the_confirmation_set(self, registry, db):
        studio = StudioTools(registry=registry, db=db, requires_confirmation_tools=[])
        assert list(getattr(studio, "requires_confirmation_tools", []) or []) == []

    def test_template_studio_tools_construction(self, registry, db):
        studio = StudioTools(
            registry=registry,
            db=db,
            versions=True,
            schedules=True,
            default_num_history_runs=5,
            requires_confirmation_tools=[
                "archive_component",
                "delete_version",
                "delete_schedule",
            ],
        )
        names = set(studio.functions)
        assert {"create_agent", "create_schedule", "update_schedule", "archive_component"} <= names

    def test_template_boot_schedule_upsert(self, db):
        # app/schedules.py boot path: create(if_exists="update") must keep
        # repointing the template's own deployment-check schedule in place.
        from agno.scheduler.manager import ScheduleManager

        manager = ScheduleManager(db=db)
        first = manager.create(
            name="deployment-check",
            cron="0 8 * * *",
            endpoint="/workflows/deployment-check/runs",
            payload={"message": "Run the deployment check."},
            if_exists="update",
        )
        second = manager.create(
            name="deployment-check",
            cron="0 9 * * *",
            endpoint="/workflows/deployment-check/runs",
            payload={"message": "Run the deployment check."},
            if_exists="update",
        )
        assert second.id == first.id
        assert second.cron_expr == "0 9 * * *"


class TestRoundThreeStudioFixes:
    """Round-three fix brief: mediums that survived the previous rounds."""

    def test_edit_base_ignores_stale_draft_below_newer_published(self, studio):
        # B1: edit -> draft v2, edit(publish) -> v3; a later edit must base on
        # v3, not the stranded v2 draft, or it resurrects rolled-back fields.
        _data(studio.create_agent(name="rb", instructions="v1", model_id="gpt-5.4", publish=True))
        _data(studio.edit_agent("rb", instructions="v2-draft"))
        _data(studio.edit_agent("rb", instructions="v3-pub", publish=True))
        out = _loads(studio.edit_agent("rb", description="d", expected_version=3))
        assert out["ok"], out
        v4 = studio.db.get_config(component_id="rb", version=4)["config"]
        assert v4["instructions"] == "v3-pub"

    def test_function_step_round_trips_through_view(self, db, registry):
        studio_workflows = StudioTools(registry=registry, db=db)

        # B8: a function-executor step serializes under executor_ref; the view
        # must surface it as function_name so read->edit works.
        def check_prime(n: int) -> bool:
            return n > 1

        registry.add_function(check_prime)
        _data(studio_workflows.create_agent(name="a", instructions="i", model_id="gpt-5.4", publish=True))
        _data(
            studio_workflows.create_workflow(
                name="wf",
                steps=[{"name": "s1", "agent_id": "a"}, {"name": "s2", "function_name": "check_prime"}],
                publish=True,
            )
        )
        view = _data(studio_workflows.get_component("wf"))
        fn_step = [s for s in view["steps"] if s.get("function_name")]
        assert fn_step and fn_step[0]["function_name"] == "check_prime"
        assert _loads(studio_workflows.edit_workflow("wf", steps=view["steps"]))["ok"]

    def test_create_over_archived_id_answers_component_archived(self, studio):
        # B10.
        _data(studio.create_agent(name="arch", instructions="i", model_id="gpt-5.4", publish=True))
        _data(studio.archive_component("arch"))
        out = _loads(studio.create_agent(name="arch2", component_id="arch", instructions="i", model_id="gpt-5.4"))
        assert out["error"]["code"] == "component_archived"
        assert "restore" in out["error"]["message"].lower()

    def test_full_toolkit_collapses_partial_stays_exact(self, db, registry):
        # B7: collapse keys on (name, toolkit) attribution.
        studio = StudioTools(registry=registry, db=db)
        _data(
            studio.create_agent(
                name="full", instructions="i", model_id="gpt-5.5", tool_names=["calculator"], publish=True
            )
        )
        assert _data(studio.get_component("full"))["tools"] == ["calculator"]
        _data(
            studio.create_agent(
                name="part", instructions="i", model_id="gpt-5.5", tool_names=["add", "subtract"], publish=True
            )
        )
        assert sorted(_data(studio.get_component("part"))["tools"]) == ["add", "subtract"]

    def test_refused_publish_edit_does_not_clobber_identity(self, studio):
        # B4.
        _data(studio.create_agent(name="Winner", component_id="w", instructions="v1", model_id="gpt-5.4", publish=True))
        out = _loads(studio.edit_agent("w", name="Loser", instructions="v2", publish=True, expected_version=99))
        assert out["error"]["code"] == "version_conflict"
        assert studio.db.get_component("w")["name"] == "Winner"


# ----------------------------------------------------------------------
# Dispatch guard on the StudioTools surface
# ----------------------------------------------------------------------


class _GuardStubTeam:
    id = "stub-team"
    name = "Stub Team"

    def __init__(self):
        self.seen = None
        self.seen_metadata = None

    def run(self, message, stream=None, user_id=None, session_id=None, metadata=None, run_id=None):
        self.seen = {"message": message}
        self.seen_metadata = metadata
        return type("Out", (), {"run_id": "r", "session_id": "s", "status": "COMPLETED", "content": "done"})()

    async def arun(self, message, stream=None, user_id=None, session_id=None, metadata=None, run_id=None):
        return self.run(message, stream=stream, user_id=user_id, session_id=session_id, metadata=metadata)

    def deep_copy(self):
        clone = object.__new__(type(self))
        clone.__dict__ = self.__dict__
        return clone


class TestStudioToolsDispatchGuard:
    """StudioTools is a second dispatch surface: its unversioned tools forward
    to the runner, and its version-pinned branch dispatches directly. Both
    halves must carry the guard, or holders of this toolkit keep the original
    unbounded self-dispatch."""

    def test_studio_run_team_refuses_top_level_self_dispatch(self, registry, db):
        stub = _GuardStubTeam()
        studio = StudioTools(registry=registry, db=db, include_teams=[stub])
        out = _loads(studio.run_team("stub-team", "hi", _agno_team=stub))
        assert "already running" in out["error"]
        assert stub.seen is None

    @pytest.mark.asyncio
    async def test_studio_arun_team_refuses_top_level_self_dispatch(self, registry, db):
        stub = _GuardStubTeam()
        studio = StudioTools(registry=registry, db=db, include_teams=[stub])
        out = _loads(await studio.arun_team("stub-team", "hi", _agno_team=stub))
        assert "already running" in out["error"]
        assert stub.seen is None

    def test_studio_version_pinned_run_is_guarded(self, registry, db):
        # The version-pinned branch never reaches the runner's run tools, so
        # an unguarded preview is the one door left open: version=N would walk
        # straight past a runner-only guard.
        studio = StudioTools(registry=registry, db=db)
        created = _loads(studio.create_agent(name="loop-preview", instructions="i", model_id="gpt-5.4", publish=True))
        assert created["data"]["id"] == "loop-preview"

        caller = type("W", (), {"id": "loop-preview"})()
        out = _loads(studio.run_agent("loop-preview", "hi", version=1, _agno_agent=caller))
        assert out["error"]["code"] == "dispatch_refused"
        assert "already running" in out["error"]["message"]

    @pytest.mark.asyncio
    async def test_studio_async_version_pinned_run_is_guarded(self, registry, db):
        studio = StudioTools(registry=registry, db=db)
        studio.create_agent(name="loop-preview", instructions="i", model_id="gpt-5.4", publish=True)

        caller = type("W", (), {"id": "loop-preview"})()
        out = _loads(await studio.arun_agent("loop-preview", "hi", version=1, _agno_agent=caller))
        assert out["error"]["code"] == "dispatch_refused"

    def test_studio_version_pinned_depth_is_guarded(self, registry, db):
        from agno.db.schemas.scheduler import DISPATCH_CHAIN_METADATA_KEY, DISPATCH_DEPTH_METADATA_KEY
        from agno.run import RunContext

        studio = StudioTools(registry=registry, db=db)
        studio.create_agent(name="deep-preview", instructions="i", model_id="gpt-5.4", publish=True)

        context = RunContext(
            run_id="caller-run",
            session_id="caller-sess",
            metadata={DISPATCH_CHAIN_METADATA_KEY: ["team:o1", "agent:o2"], DISPATCH_DEPTH_METADATA_KEY: 2},
        )
        out = _loads(studio.run_agent("deep-preview", "hi", version=1, _agno_run_context=context))
        assert out["error"]["code"] == "dispatch_refused"

    def test_studio_forwards_the_caller_by_keyword(self, registry, db):
        # The runner's injected parameters are keyword channels; a future
        # positional call site would drop the caller identity without an error.
        from unittest.mock import patch

        stub = _GuardStubTeam()
        studio = StudioTools(registry=registry, db=db, include_teams=[stub])
        with patch.object(studio._runner_tools, "run_team", return_value='{"ok": true}') as spy:
            studio.run_team("stub-team", "hi", _agno_team=stub)
        assert spy.call_count == 1
        args, kwargs = spy.call_args
        assert args == ("stub-team", "hi")
        assert kwargs["_agno_team"] is stub
        assert kwargs["_agno_agent"] is None
        assert "_agno_run_context" in kwargs
