"""Palette policy for StudioTools (studio-3.0 spec section 3.4, G6).

The build palette is declared tools + buildable_tools - denied_tools. Tools
that arrived via the registry fold (Registry.add_tool(tool, source="folded"),
the way AgentOS folds every registered agent's own tools in) are resolvable
for rehydration but not buildable; wiring one returns tool_not_allowed with
details.blocked. Denials always win. Composing a component that itself
carries StudioTools into a team or workflow is refused the same way unless
its id is explicitly allowed.
"""

import json
from typing import Any, Dict

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.tools.calculator import CalculatorTools
from agno.tools.function import Function
from agno.tools.studio import StudioTools
from agno.tools.toolkit import Toolkit


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="studio-palette-db", db_file=str(tmp_path / "studio_palette.db"))


def _folded_lookup(query: str) -> str:
    """A tool that reached the registry through the fold."""
    return query


@pytest.fixture
def registry(db):
    registry = Registry(
        name="Palette Registry",
        tools=[CalculatorTools()],
        models=[OpenAIResponses(id="gpt-5.5")],
        dbs=[db],
    )
    registry.add_tool(Toolkit(name="agent_private", tools=[_folded_lookup]), source="folded")
    return registry


def _loads(s: str) -> Dict[str, Any]:
    return json.loads(s)


def _data(s: str) -> Dict[str, Any]:
    out = json.loads(s)
    assert out.get("ok") is True, out
    return out["data"]


def _error(s: str) -> Dict[str, Any]:
    out = json.loads(s)
    assert out.get("ok") is False, out
    return out["error"]


def _tool_rows(studio: StudioTools) -> Dict[str, Dict[str, Any]]:
    return {row["name"]: row for row in _data(studio.list_tools())["tools"]}


class TestFoldedTools:
    def test_folded_toolkit_is_listed_but_not_buildable(self, registry, db):
        rows = _tool_rows(StudioTools(registry=registry, db=db))
        assert rows["calculator"]["buildable"] is True
        assert rows["calculator"]["source"] == "declared"
        assert rows["agent_private"]["buildable"] is False
        assert rows["agent_private"]["source"] == "folded"

    def test_wiring_a_folded_toolkit_returns_tool_not_allowed(self, registry, db):
        studio = StudioTools(registry=registry, db=db)
        error = _error(studio.create_agent(name="x", instructions="i", tool_names=["agent_private"]))
        assert error["code"] == "tool_not_allowed"
        assert error["details"]["blocked"] == ["agent_private"]

    def test_a_folded_toolkits_member_function_is_not_a_side_door(self, registry, db):
        # The fold covers the whole toolkit: requesting a member by its bare
        # function name resolves the same folded tool and is refused the same way.
        studio = StudioTools(registry=registry, db=db)
        error = _error(studio.create_agent(name="x", instructions="i", tool_names=["_folded_lookup"]))
        assert error["code"] == "tool_not_allowed"
        assert error["details"]["blocked"] == ["_folded_lookup"]

    def test_edit_is_refused_the_same_way(self, registry, db):
        studio = StudioTools(registry=registry, db=db)
        studio.create_agent(name="editable", instructions="i")
        error = _error(studio.edit_agent("editable", tool_names=["agent_private"]))
        assert error["code"] == "tool_not_allowed"

    def test_buildable_tools_allows_a_folded_toolkit(self, registry, db):
        studio = StudioTools(registry=registry, db=db, buildable_tools=["agent_private"])
        assert _tool_rows(studio)["agent_private"]["buildable"] is True
        data = _data(studio.create_agent(name="allowed", instructions="i", tool_names=["agent_private"]))
        assert data["id"] == "allowed"

    def test_buildable_tools_allows_a_single_folded_function(self, registry, db):
        studio = StudioTools(registry=registry, db=db, buildable_tools=["_folded_lookup"])
        data = _data(studio.create_agent(name="allowed-fn", instructions="i", tool_names=["_folded_lookup"]))
        assert data["id"] == "allowed-fn"


class TestDeniedTools:
    def test_denied_declared_tool_is_refused_and_listed_unbuildable(self, registry, db):
        studio = StudioTools(registry=registry, db=db, denied_tools=["calculator"])
        assert _tool_rows(studio)["calculator"]["buildable"] is False
        error = _error(studio.create_agent(name="x", instructions="i", tool_names=["calculator"]))
        assert error["code"] == "tool_not_allowed"
        assert error["details"]["blocked"] == ["calculator"]

    def test_denying_a_toolkit_covers_its_member_functions(self, registry, db):
        studio = StudioTools(registry=registry, db=db, denied_tools=["calculator"])
        error = _error(studio.create_agent(name="x", instructions="i", tool_names=["add"]))
        assert error["code"] == "tool_not_allowed"

    def test_denied_always_wins_over_buildable(self, registry, db):
        studio = StudioTools(
            registry=registry, db=db, buildable_tools=["agent_private"], denied_tools=["agent_private"]
        )
        error = _error(studio.create_agent(name="x", instructions="i", tool_names=["agent_private"]))
        assert error["code"] == "tool_not_allowed"

    def test_undenied_tools_stay_buildable(self, registry, db):
        studio = StudioTools(registry=registry, db=db, denied_tools=["calculator"])
        data = _data(studio.create_agent(name="searcher", instructions="i", tool_names=[]))
        assert data["id"] == "searcher"


class TestSelfCompositionGuard:
    @pytest.fixture
    def builder_agent(self, registry, db):
        return Agent(
            id="builder",
            name="Builder",
            model=OpenAIResponses(id="gpt-5.5"),
            tools=[StudioTools(registry=registry, db=db)],
        )

    def test_team_member_carrying_studio_tools_is_refused(self, registry, db, builder_agent):
        studio = StudioTools(registry=registry, db=db, teams=True, agents_list=[builder_agent])
        error = _error(studio.create_team(name="Meta", instructions="i", member_ids=["builder"]))
        assert error["code"] == "tool_not_allowed"
        assert error["details"]["blocked"] == ["builder"]

    def test_workflow_step_carrying_studio_tools_is_refused(self, registry, db, builder_agent):
        studio = StudioTools(registry=registry, db=db, workflows=True, agents_list=[builder_agent])
        error = _error(studio.create_workflow(name="Meta Flow", steps=[{"name": "s1", "agent_id": "builder"}]))
        assert error["code"] == "tool_not_allowed"
        assert error["details"]["blocked"] == ["builder"]

    def test_buildable_tools_overrides_the_guard(self, registry, db, builder_agent):
        studio = StudioTools(
            registry=registry, db=db, teams=True, agents_list=[builder_agent], buildable_tools=["builder"]
        )
        data = _data(studio.create_team(name="Meta", instructions="i", member_ids=["builder"]))
        assert data["member_ids"] == ["builder"]

    def test_edit_team_is_guarded_too(self, registry, db, builder_agent):
        studio = StudioTools(registry=registry, db=db, teams=True, agents_list=[builder_agent])
        studio.create_agent(name="plain-member", instructions="i", publish=True)
        studio.create_team(name="Crew", instructions="i", member_ids=["plain-member"])

        error = _error(studio.edit_team("crew", member_ids=["builder"]))
        assert error["code"] == "tool_not_allowed"

    def test_members_without_studio_tools_are_untouched(self, registry, db):
        plain = Agent(id="plain", name="Plain", model=OpenAIResponses(id="gpt-5.5"), tools=[CalculatorTools()])
        studio = StudioTools(registry=registry, db=db, teams=True, agents_list=[plain])
        data = _data(studio.create_team(name="Crew", instructions="i", member_ids=["plain"]))
        assert data["member_ids"] == ["plain"]


class TestMutatingFlag:
    def test_list_tools_surfaces_an_explicit_mutating_flag(self, db):
        mutating_fn = Function(
            name="delete_everything",
            description="Deletes everything.",
            mutating=True,
            parameters={"type": "object", "properties": {}},
            skip_entrypoint_processing=True,
        )
        registry = Registry(
            name="Mutating Registry",
            tools=[mutating_fn],
            models=[OpenAIResponses(id="gpt-5.5")],
            dbs=[db],
        )
        studio = StudioTools(registry=registry, db=db)

        row = _tool_rows(studio)["delete_everything"]
        assert row["kind"] == "function"
        assert row["functions"] == [
            {"name": "delete_everything", "description": "Deletes everything.", "mutating": True}
        ]
