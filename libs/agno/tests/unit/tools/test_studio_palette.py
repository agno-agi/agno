"""Palette policy for StudioTools.

The build palette is declared tools + allowed_tools - denied_tools. Tools
that arrived via the discovery walk (Registry.add_tool(tool, source="discovered"),
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
from agno.team import Team
from agno.tools.calculator import CalculatorTools
from agno.tools.function import Function
from agno.tools.studio import StudioTools
from agno.tools.toolkit import Toolkit


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="studio-palette-db", db_file=str(tmp_path / "studio_palette.db"))


def _discovered_lookup(query: str) -> str:
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
    registry.add_tool(Toolkit(name="agent_private", tools=[_discovered_lookup]), source="discovered")
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


class TestDiscoveredTools:
    def test_a_discovered_toolkit_is_listed_but_not_buildable(self, registry, db):
        rows = _tool_rows(StudioTools(registry=registry, db=db))
        assert rows["calculator"]["buildable"] is True
        assert rows["calculator"]["source"] == "declared"
        assert rows["agent_private"]["buildable"] is False
        assert rows["agent_private"]["source"] == "discovered"

    def test_wiring_a_folded_toolkit_returns_tool_not_allowed(self, registry, db):
        studio = StudioTools(registry=registry, db=db)
        error = _error(studio.create_agent(name="x", instructions="i", tool_names=["agent_private"]))
        assert error["code"] == "tool_not_allowed"
        assert error["details"]["blocked"] == ["agent_private"]

    def test_a_folded_toolkits_member_function_is_not_a_side_door(self, registry, db):
        # The fold covers the whole toolkit: requesting a member by its bare
        # function name resolves the same folded tool and is refused the same way.
        studio = StudioTools(registry=registry, db=db)
        error = _error(studio.create_agent(name="x", instructions="i", tool_names=["_discovered_lookup"]))
        assert error["code"] == "tool_not_allowed"
        assert error["details"]["blocked"] == ["_discovered_lookup"]

    def test_edit_is_refused_the_same_way(self, registry, db):
        studio = StudioTools(registry=registry, db=db)
        studio.create_agent(name="editable", instructions="i")
        error = _error(studio.edit_agent("editable", tool_names=["agent_private"]))
        assert error["code"] == "tool_not_allowed"

    def test_allowed_tools_allows_a_folded_toolkit(self, registry, db):
        studio = StudioTools(registry=registry, db=db, allowed_tools=["agent_private"])
        assert _tool_rows(studio)["agent_private"]["buildable"] is True
        data = _data(studio.create_agent(name="allowed", instructions="i", tool_names=["agent_private"]))
        assert data["id"] == "allowed"

    def test_allowed_tools_allows_a_single_folded_function(self, registry, db):
        studio = StudioTools(registry=registry, db=db, allowed_tools=["_discovered_lookup"])
        data = _data(studio.create_agent(name="allowed-fn", instructions="i", tool_names=["_discovered_lookup"]))
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
        studio = StudioTools(registry=registry, db=db, allowed_tools=["agent_private"], denied_tools=["agent_private"])
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
        studio = StudioTools(registry=registry, db=db, include_agents=[builder_agent])
        error = _error(studio.create_team(name="Meta", instructions="i", member_ids=["builder"]))
        assert error["code"] == "tool_not_allowed"
        assert error["details"]["blocked"] == ["builder"]

    def test_workflow_step_carrying_studio_tools_is_refused(self, registry, db, builder_agent):
        studio = StudioTools(registry=registry, db=db, include_agents=[builder_agent])
        error = _error(studio.create_workflow(name="Meta Flow", steps=[{"name": "s1", "agent_id": "builder"}]))
        assert error["code"] == "tool_not_allowed"
        assert error["details"]["blocked"] == ["builder"]

    def test_allowed_tools_overrides_the_guard(self, registry, db, builder_agent):
        studio = StudioTools(registry=registry, db=db, include_agents=[builder_agent], allowed_tools=["builder"])
        data = _data(studio.create_team(name="Meta", instructions="i", member_ids=["builder"]))
        assert data["member_ids"] == ["builder"]

    def test_edit_team_is_guarded_too(self, registry, db, builder_agent):
        studio = StudioTools(registry=registry, db=db, include_agents=[builder_agent])
        studio.create_agent(name="plain-member", instructions="i", publish=True)
        studio.create_team(name="Crew", instructions="i", member_ids=["plain-member"])

        error = _error(studio.edit_team("crew", member_ids=["builder"]))
        assert error["code"] == "tool_not_allowed"

    def test_display_name_reference_is_refused(self, registry, db, builder_agent):
        # The guard runs after resolution, so the builder's display name is as
        # blocked as its id.
        studio = StudioTools(registry=registry, db=db, include_agents=[builder_agent])
        error = _error(studio.create_team(name="Meta", instructions="i", member_ids=["Builder"]))
        assert error["code"] == "tool_not_allowed"

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
                "steps": [inner],
                "else_steps": [inner],
            },
            lambda inner: {"type": "router", "name": "r", "selector_function": "'x'", "choices": [inner]},
        ],
        ids=["parallel", "loop", "steps", "condition", "router"],
    )
    def test_builder_nested_in_compound_steps_is_refused(self, registry, db, builder_agent, wrap):
        studio = StudioTools(registry=registry, db=db, include_agents=[builder_agent])
        inner = {"name": "leaf", "agent_id": "builder"}
        error = _error(studio.create_workflow(name="Nested Meta", steps=[wrap(inner)]))
        assert error["code"] == "tool_not_allowed"

    def test_team_containing_the_builder_is_refused(self, registry, db, builder_agent):
        # Privilege is recursive: a team is privileged when any member is.
        crew = Team(
            id="builder-crew", name="Builder Crew", members=[builder_agent], model=OpenAIResponses(id="gpt-5.5")
        )
        studio = StudioTools(registry=registry, db=db, include_agents=[builder_agent], include_teams=[crew])
        error = _error(studio.create_team(name="Meta", instructions="i", member_ids=["builder-crew"]))
        assert error["code"] == "tool_not_allowed"

    def test_stored_component_with_rehydrated_studio_tools_is_refused(self, registry, db):
        # A DB-stored agent whose config carries the studio toolkit rehydrates
        # to member Functions bound to a StudioTools instance; the guard reads
        # the bound entrypoint, not just isinstance on the toolkit object.
        studio_toolkit = StudioTools(registry=registry, db=db)
        registry.add_tool(studio_toolkit, source="discovered")
        stored_builder = Agent(
            id="stored-builder",
            name="Stored Builder",
            model=OpenAIResponses(id="gpt-5.5"),
            tools=[studio_toolkit],
        )
        stored_builder.save(db=db)
        studio = StudioTools(registry=registry, db=db)
        error = _error(studio.create_team(name="Meta", instructions="i", member_ids=["stored-builder"]))
        assert error["code"] == "tool_not_allowed"

    def test_members_without_studio_tools_are_untouched(self, registry, db):
        plain = Agent(id="plain", name="Plain", model=OpenAIResponses(id="gpt-5.5"), tools=[CalculatorTools()])
        studio = StudioTools(registry=registry, db=db, include_agents=[plain])
        data = _data(studio.create_team(name="Crew", instructions="i", member_ids=["plain"]))
        assert data["member_ids"] == ["plain"]


class TestSideEffectsFlag:
    def test_list_tools_surfaces_an_explicit_side_effects_flag(self, db):
        side_effectful_fn = Function(
            name="delete_everything",
            description="Deletes everything.",
            has_side_effects=True,
            parameters={"type": "object", "properties": {}},
            skip_entrypoint_processing=True,
        )
        registry = Registry(
            name="Side Effects Registry",
            tools=[side_effectful_fn],
            models=[OpenAIResponses(id="gpt-5.5")],
            dbs=[db],
        )
        studio = StudioTools(registry=registry, db=db)

        row = _tool_rows(studio)["delete_everything"]
        assert row["kind"] == "function"
        assert row["functions"] == [
            {"name": "delete_everything", "description": "Deletes everything.", "has_side_effects": True}
        ]


class TestSelfCompositionGuardRobustness:
    """A callable tools/members attribute (per-run factory - a documented
    pattern) is not statically inspectable; the guard must skip it, not turn
    every compose call into internal_error."""

    def test_registry_agent_with_tools_factory_does_not_break_compose(self, registry, db):
        from agno.agent import Agent

        def dynamic_tools(agent):
            return []

        factory_agent = Agent(
            id="factory-agent", name="Factory", model=OpenAIResponses(id="gpt-5.5"), tools=dynamic_tools
        )
        studio = StudioTools(registry=registry, db=db, include_agents=[factory_agent])
        studio.create_agent(name="plain-member", instructions="i", publish=True)
        data = _data(studio.create_team(name="Crew", instructions="i", member_ids=["plain-member"]))
        assert data["member_ids"] == ["plain-member"]

    def test_team_with_members_factory_composes_as_member(self, registry, db):
        from agno.team import Team

        def member_factory(team):
            return []

        crew = Team(id="factory-crew", name="Factory Crew", model=OpenAIResponses(id="gpt-5.5"), members=member_factory)
        studio = StudioTools(registry=registry, db=db, include_teams=[crew])
        data = _data(studio.create_team(name="Outer", instructions="i", member_ids=["factory-crew"]))
        assert data["member_ids"] == ["factory-crew"]

    def test_builder_with_real_studio_tools_still_refused_despite_factory_neighbor(self, registry, db):
        # The factory neighbor must not mask a genuine privileged component.
        from agno.agent import Agent

        def dynamic_tools(agent):
            return []

        builder_agent = Agent(
            id="builder",
            name="Builder",
            model=OpenAIResponses(id="gpt-5.5"),
            tools=[StudioTools(registry=registry, db=db)],
        )
        factory_agent = Agent(
            id="factory-agent", name="Factory", model=OpenAIResponses(id="gpt-5.5"), tools=dynamic_tools
        )
        studio = StudioTools(registry=registry, db=db, include_agents=[builder_agent, factory_agent])
        error = _error(studio.create_team(name="Meta", instructions="i", member_ids=["builder"]))
        assert error["code"] == "tool_not_allowed"
