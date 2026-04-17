"""Unit tests for StudioTool toolkit.

Uses a real SqliteDb backed by a pytest tmp_path so the full component +
config persistence path is exercised, not mocked.
"""

import json
from typing import Any, Dict, List

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.registry import Registry
from agno.tools.calculator import CalculatorTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.studio import StudioTool


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
        models=[OpenAIChat(id="gpt-4o-mini"), OpenAIChat(id="gpt-4o")],
        dbs=[db],
    )


@pytest.fixture
def studio(registry, db):
    return StudioTool(registry=registry, db=db)


def _loads(s: str) -> Dict[str, Any]:
    return json.loads(s)


# ----------------------------------------------------------------------
# Initialization
# ----------------------------------------------------------------------


class TestInitialization:
    def test_default_registers_agents_plus_discovery_and_versioning(self, studio):
        expected = {
            # Discovery (always)
            "list_models",
            "list_tools",
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
            # Versioning (available whenever any component type is enabled)
            "list_versions",
            "get_version",
            "publish_component",
            "set_current_version",
            "delete_version",
        }
        assert expected == set(studio.functions.keys())

    def test_default_does_not_register_team_or_workflow_tools(self, studio):
        names = set(studio.functions.keys())
        for absent in ("create_team", "create_workflow", "edit_team", "edit_workflow"):
            assert absent not in names

    def test_registers_async_run_agent_by_default(self, studio):
        assert "run_agent" in studio.async_functions
        assert "run_team" not in studio.async_functions
        assert "run_workflow" not in studio.async_functions

    def test_registers_all_async_run_tools_when_enabled(self, registry, db):
        tool = StudioTool(registry=registry, db=db, teams=True, workflows=True)
        assert {"run_agent", "run_team", "run_workflow"}.issubset(set(tool.async_functions.keys()))

    def test_db_defaults_to_first_registry_db(self, registry):
        tool = StudioTool(registry=registry)
        assert tool.db is registry.dbs[0]

    def test_explicit_db_overrides_registry(self, registry, db):
        other = SqliteDb(id="other", db_file=":memory:")
        tool = StudioTool(registry=registry, db=other)
        assert tool.db is other


# ----------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------


class TestDiscovery:
    def test_list_models(self, studio):
        result = _loads(studio.list_models())
        ids = {m["id"] for m in result["models"]}
        assert ids == {"gpt-4o-mini", "gpt-4o"}

    def test_list_tools(self, studio):
        result = _loads(studio.list_tools())
        names = {t["name"] for t in result["tools"]}
        assert "calculator" in names
        assert "websearch" in names  # DuckDuckGoTools registers as 'websearch'
        for t in result["tools"]:
            if t["name"] == "calculator":
                assert "add" in t["functions"]

    def test_list_dbs(self, studio, db):
        result = _loads(studio.list_dbs())
        assert result["count"] == 1
        assert result["dbs"][0]["id"] == db.id

    def test_list_agents_includes_studio_created_db_components(self, registry, db):
        code_agent = Agent(id="code-only", name="Code Only", model=OpenAIChat(id="gpt-4o-mini"))
        tool = StudioTool(registry=registry, db=db, agents_list=[code_agent])
        tool.create_agent(name="math-king", instructions="i", model_id="gpt-4o-mini")

        result = _loads(tool.list_agents())
        ids = {a["id"]: a.get("source") for a in result["agents"]}
        assert ids.get("code-only") == "code"
        assert ids.get("math-king") == "db"

    def test_list_agents_dedupes_when_code_shadows_db(self, registry, db):
        tool = StudioTool(registry=registry, db=db)
        tool.create_agent(name="shared", instructions="i", model_id="gpt-4o-mini")

        code_agent = Agent(id="shared", name="Shared Code", model=OpenAIChat(id="gpt-4o-mini"))
        tool2 = StudioTool(registry=registry, db=db, agents_list=[code_agent])

        result = _loads(tool2.list_agents())
        shared_entries = [a for a in result["agents"] if a["id"] == "shared"]
        assert len(shared_entries) == 1
        assert shared_entries[0]["source"] == "code"

    def test_list_teams_includes_db_components(self, registry, db):
        tool = StudioTool(registry=registry, db=db, teams=True)
        tool.create_agent(name="a1", instructions="i", model_id="gpt-4o-mini")
        tool.create_team(name="squad", instructions="i", member_ids=["a1"], model_id="gpt-4o-mini")

        result = _loads(tool.list_teams())
        ids = {t["id"]: t.get("source") for t in result["teams"]}
        assert ids.get("squad") == "db"

    def test_list_workflows_includes_db_components(self, registry, db):
        tool = StudioTool(registry=registry, db=db, workflows=True)
        tool.create_agent(name="a1", instructions="i", model_id="gpt-4o-mini")
        tool.create_workflow(
            name="pipeline", description="d", step_specs=[{"name": "s1", "agent_id": "a1"}]
        )

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
                model_id="gpt-4o-mini",
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
        out = _loads(
            studio.create_agent(name="x", instructions="i", model_id="gpt-4o-mini", tool_names=["nonexistent"])
        )
        assert "error" in out
        assert "Tools not found" in out["error"]

    def test_create_without_tools(self, studio):
        out = _loads(studio.create_agent(name="plain", instructions="i", model_id="gpt-4o-mini"))
        assert out["status"] == "created"
        assert out["tools"] == []


class TestCreateTeam:
    def _make_members(self, studio):
        studio.create_agent(name="a1", instructions="i", model_id="gpt-4o-mini")
        studio.create_agent(name="a2", instructions="i", model_id="gpt-4o-mini")

    def test_happy_path(self, studio, db):
        self._make_members(studio)
        out = _loads(
            studio.create_team(
                name="squad",
                instructions="coordinate",
                member_ids=["a1", "a2"],
                model_id="gpt-4o-mini",
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
                model_id="gpt-4o-mini",
            )
        )
        assert "error" in out
        assert "Members not found" in out["error"]

    def test_empty_members_returns_error(self, studio):
        out = _loads(studio.create_team(name="squad", instructions="i", member_ids=[], model_id="gpt-4o-mini"))
        assert "error" in out


class TestCreateWorkflow:
    def _make_agents(self, studio):
        studio.create_agent(name="a1", instructions="i", model_id="gpt-4o-mini")
        studio.create_agent(name="a2", instructions="i", model_id="gpt-4o-mini")

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
# Edit (draft lifecycle)
# ----------------------------------------------------------------------


class TestEditAgent:
    def _create(self, studio):
        return _loads(
            studio.create_agent(name="tutor", instructions="orig", model_id="gpt-4o-mini", tool_names=["calculator"])
        )

    def test_edit_produces_draft_v2(self, studio):
        self._create(studio)
        out = _loads(studio.edit_agent(agent_id="tutor", instructions="updated"))
        assert out["status"] == "edited"
        assert out["stage"] == "draft"
        assert out["draft_version"] == 2

    def test_second_edit_updates_same_draft_in_place(self, studio):
        self._create(studio)
        studio.edit_agent(agent_id="tutor", instructions="updated once")
        out = _loads(studio.edit_agent(agent_id="tutor", instructions="updated twice"))
        assert out["draft_version"] == 2  # same draft, no new version

        versions = _loads(studio.list_versions("tutor"))
        stages = [v["stage"] for v in versions["versions"]]
        assert stages.count("draft") == 1
        assert stages.count("published") == 1

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


class TestEditTeam:
    def _setup(self, studio):
        studio.create_agent(name="a1", instructions="i", model_id="gpt-4o-mini")
        studio.create_agent(name="a2", instructions="i", model_id="gpt-4o-mini")
        studio.create_team(name="squad", instructions="orig", member_ids=["a1"], model_id="gpt-4o-mini")

    def test_edit_team_members(self, studio):
        self._setup(studio)
        out = _loads(studio.edit_team(team_id="squad", member_ids=["a1", "a2"]))
        assert out["status"] == "edited"
        assert out["stage"] == "draft"

    def test_edit_team_missing_member_returns_error(self, studio):
        self._setup(studio)
        out = _loads(studio.edit_team(team_id="squad", member_ids=["ghost"]))
        assert "error" in out


class TestEditWorkflow:
    def _setup(self, studio):
        studio.create_agent(name="a1", instructions="i", model_id="gpt-4o-mini")
        studio.create_workflow(name="pipeline", description="orig", step_specs=[{"name": "s1", "agent_id": "a1"}])

    def test_edit_workflow_description(self, studio):
        self._setup(studio)
        out = _loads(studio.edit_workflow(workflow_id="pipeline", description="updated"))
        assert out["status"] == "edited"

    def test_edit_workflow_bad_step(self, studio):
        self._setup(studio)
        out = _loads(studio.edit_workflow(workflow_id="pipeline", step_specs=[{"name": "s1", "agent_id": "ghost"}]))
        assert "error" in out


# ----------------------------------------------------------------------
# Versioning
# ----------------------------------------------------------------------


class TestVersioning:
    def _create_and_edit(self, studio):
        studio.create_agent(name="tutor", instructions="orig", model_id="gpt-4o-mini", tool_names=["calculator"])
        studio.edit_agent(agent_id="tutor", instructions="updated")

    def test_list_versions_returns_both(self, studio):
        self._create_and_edit(studio)
        result = _loads(studio.list_versions("tutor"))
        assert result["count"] == 2
        stages = sorted(v["stage"] for v in result["versions"])
        assert stages == ["draft", "published"]

    def test_get_version_returns_config(self, studio):
        self._create_and_edit(studio)
        result = _loads(studio.get_version("tutor", version=1))
        assert result.get("version") == 1
        assert result.get("stage") == "published"

    def test_get_current_version_omits_version(self, studio):
        self._create_and_edit(studio)
        result = _loads(studio.get_version("tutor"))
        assert result.get("version") is not None

    def test_publish_promotes_draft_to_current(self, studio):
        self._create_and_edit(studio)
        out = _loads(studio.publish_component("tutor"))
        assert out["status"] == "published"
        assert out["version"] == 2

        versions = _loads(studio.list_versions("tutor"))
        stages = [v["stage"] for v in versions["versions"]]
        assert stages.count("published") == 2
        assert stages.count("draft") == 0

    def test_publish_without_draft_returns_error(self, studio):
        studio.create_agent(name="tutor", instructions="i", model_id="gpt-4o-mini")
        out = _loads(studio.publish_component("tutor"))
        assert "error" in out

    def test_set_current_version_rollback(self, studio):
        self._create_and_edit(studio)
        studio.publish_component("tutor")  # v2 published & current
        out = _loads(studio.set_current_version("tutor", 1))
        assert out["status"] == "set_current"
        assert out["version"] == 1

    def test_delete_draft_version(self, studio):
        self._create_and_edit(studio)
        out = _loads(studio.delete_version("tutor", 2))
        assert out["status"] == "deleted"

        versions = _loads(studio.list_versions("tutor"))
        assert versions["count"] == 1
        assert versions["versions"][0]["version"] == 1

    def test_delete_published_version_returns_error(self, studio):
        self._create_and_edit(studio)
        # v1 is published+current — DB should refuse to delete it
        out = _loads(studio.delete_version("tutor", 1))
        assert "error" in out


# ----------------------------------------------------------------------
# Delete
# ----------------------------------------------------------------------


class TestDelete:
    def test_delete_agent_removes_from_db(self, studio, db):
        studio.create_agent(name="temp", instructions="i", model_id="gpt-4o-mini")
        out = _loads(studio.delete_agent("temp"))
        assert out["status"] == "deleted"
        assert db.get_component("temp") is None

    def test_delete_unknown_agent_returns_error(self, studio):
        out = _loads(studio.delete_agent("ghost"))
        assert "error" in out


# ----------------------------------------------------------------------
# Lookup priority
# ----------------------------------------------------------------------


class TestLookup:
    def test_find_agent_finds_just_created_via_db(self, studio):
        studio.create_agent(name="cached", instructions="i", model_id="gpt-4o-mini")
        agent = studio._find_agent("cached")
        assert agent is not None
        assert agent.id == "cached"

    def test_find_agent_falls_back_to_live_list(self, registry, db):
        live = Agent(id="live-one", name="Live", model=OpenAIChat(id="gpt-4o-mini"), db=db)
        tool = StudioTool(registry=registry, db=db, agents_list=[live])
        found = tool._find_agent("live-one")
        assert found is live

    def test_find_agent_falls_back_to_db(self, studio, registry, db):
        studio.create_agent(name="persisted", instructions="i", model_id="gpt-4o-mini")
        fresh = StudioTool(registry=registry, db=db)
        found = fresh._find_agent("persisted")
        assert found is not None
        assert found.id == "persisted"


# ----------------------------------------------------------------------
# Enable flags
# ----------------------------------------------------------------------


class TestEnableFlags:
    def test_default_enables_agents_only(self, registry, db):
        tool = StudioTool(registry=registry, db=db)
        assert tool.enable_agents is True
        assert tool.enable_teams is False
        assert tool.enable_workflows is False
        names = set(tool.functions.keys())
        assert "create_agent" in names
        assert "create_team" not in names
        assert "create_workflow" not in names

    def test_opt_in_teams(self, registry, db):
        tool = StudioTool(registry=registry, db=db, teams=True)
        assert tool.enable_agents is True  # agents stays on by default
        assert tool.enable_teams is True
        assert tool.enable_workflows is False
        names = set(tool.functions.keys())
        assert "create_team" in names

    def test_agents_disabled_explicitly(self, registry, db):
        tool = StudioTool(registry=registry, db=db, agents=False, teams=True)
        assert tool.enable_agents is False
        assert tool.enable_teams is True
        names = set(tool.functions.keys())
        assert "create_agent" not in names
        assert "create_team" in names

    def test_workflows_only(self, registry, db):
        tool = StudioTool(registry=registry, db=db, agents=False, workflows=True)
        assert tool.enable_agents is False
        assert tool.enable_teams is False
        assert tool.enable_workflows is True
        names = set(tool.functions.keys())
        assert "create_workflow" in names
        assert "create_agent" not in names

    def test_agents_list_auto_enables_teams_and_workflows(self, registry, db):
        tool = StudioTool(registry=registry, db=db, agents_list=[])
        assert tool.enable_agents is True
        assert tool.enable_teams is True
        assert tool.enable_workflows is True

    def test_teams_list_auto_enables_workflows(self, registry, db):
        tool = StudioTool(registry=registry, db=db, teams_list=[])
        assert tool.enable_workflows is True

    def test_explicit_flag_overrides_auto_enable(self, registry, db):
        # User passes agents_list but explicitly disables workflows.
        tool = StudioTool(registry=registry, db=db, agents_list=[], workflows=False)
        assert tool.enable_workflows is False

    def test_discovery_tools_always_registered(self, registry, db):
        # Even with everything disabled, discovery tools stay registered.
        tool = StudioTool(registry=registry, db=db, agents=False)
        names = set(tool.functions.keys())
        assert {
            "list_models",
            "list_tools",
            "list_dbs",
            "list_agents",
            "list_teams",
            "list_workflows",
        }.issubset(names)


# ----------------------------------------------------------------------
# Non-cascading persistence: code-defined members should NOT land in DB
# ----------------------------------------------------------------------


class TestNoCascadePersistence:
    def test_create_team_does_not_persist_code_defined_member(self, registry, db):
        greeter = Agent(id="greeter-code", name="Greeter", model=OpenAIChat(id="gpt-4o-mini"))
        tool = StudioTool(registry=registry, db=db, agents_list=[greeter])

        tool.create_agent(name="studio-agent", instructions="i", model_id="gpt-4o-mini")
        tool.create_team(
            name="mixed-team",
            instructions="i",
            member_ids=["greeter-code", "studio-agent"],
            model_id="gpt-4o-mini",
        )

        # Team row exists
        assert db.get_component("mixed-team") is not None
        # Studio-created agent row exists
        assert db.get_component("studio-agent") is not None
        # Code-defined agent MUST NOT be in DB
        assert db.get_component("greeter-code") is None

    def test_create_workflow_does_not_persist_code_defined_agent(self, registry, db):
        greeter = Agent(id="greeter-code", name="Greeter", model=OpenAIChat(id="gpt-4o-mini"))
        tool = StudioTool(registry=registry, db=db, agents_list=[greeter])

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
    def test_full_lifecycle(self, studio, db):
        # Create
        out = _loads(
            studio.create_agent(name="lc", instructions="orig", model_id="gpt-4o-mini", tool_names=["calculator"])
        )
        assert out["db_version"] == 1

        # Edit twice — should collapse into one draft
        studio.edit_agent(agent_id="lc", instructions="edit1")
        studio.edit_agent(agent_id="lc", instructions="edit2")

        versions: List[Dict[str, Any]] = _loads(studio.list_versions("lc"))["versions"]
        assert len(versions) == 2

        # Publish draft
        pub = _loads(studio.publish_component("lc"))
        assert pub["version"] == 2

        # Rollback
        rb = _loads(studio.set_current_version("lc", 1))
        assert rb["status"] == "set_current"

        # Delete
        _loads(studio.delete_agent("lc"))
        assert db.get_component("lc") is None
