"""The self-composition guard sees through a tools/members FACTORY.

``tools`` and ``members`` accept a callable that is resolved per run, with
agno injecting arguments by name -- ``def f(agent)``, ``def f(team)``,
``def f(run_context)``, ``def f(session_state)`` are all documented shapes.
The guard used to give up on any of them and report "no tools", so
``tools=lambda agent: [studio]`` composed freely where ``tools=[studio]`` was
refused: the composed member got the whole control plane.

The guard proves ABSENCE, so what it cannot resolve it must refuse: an async
factory, a factory that raises, and a factory asking for an argument nothing
injects all count as privileged. Factories that resolve to something harmless
still compose -- refusing those would break a documented pattern.
"""

import asyncio
import json
from typing import Any, Dict

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.team import Team
from agno.tools.calculator import CalculatorTools
from agno.tools.studio import StudioTools


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="studio-factory-db", db_file=str(tmp_path / "factories.db"))


@pytest.fixture
def registry(db):
    return Registry(
        name="Factory Registry",
        tools=[CalculatorTools()],
        models=[OpenAIResponses(id="gpt-5.5")],
        dbs=[db],
    )


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


def _agent(component_id: str, tools: Any) -> Agent:
    return Agent(id=component_id, name=component_id, model=OpenAIResponses(id="gpt-5.5"), tools=tools)


def _studio_with(registry, db, *components) -> StudioTools:
    agents = [c for c in components if isinstance(c, Agent)]
    teams = [c for c in components if isinstance(c, Team)]
    return StudioTools(registry=registry, db=db, include_agents=agents, include_teams=teams)


# Every factory below hands back the live control plane; the shape of the
# signature is the only difference between them.
def _privileged_factories(control_plane: StudioTools) -> Dict[str, Any]:
    def by_agent(agent):
        return [control_plane]

    def by_team(team):
        return [control_plane]

    def by_run_context(run_context):
        return [control_plane]

    def by_session_state(session_state):
        return [control_plane]

    def by_nothing():
        return [control_plane]

    return {
        "agent": by_agent,
        "team": by_team,
        "run_context": by_run_context,
        "session_state": by_session_state,
        "zero_arg": by_nothing,
    }


INJECTED_NAMES = ["agent", "team", "run_context", "session_state", "zero_arg"]


class TestInjectedFactoriesAreRefused:
    @pytest.mark.parametrize("shape", INJECTED_NAMES)
    def test_create_team_refuses_a_factory_member(self, registry, db, shape):
        control_plane = StudioTools(registry=registry, db=db)
        smuggler = _agent("smuggler", _privileged_factories(control_plane)[shape])
        studio = _studio_with(registry, db, smuggler)

        error = _error(studio.create_team(name="Crew", instructions="i", member_ids=["smuggler"]))
        assert error["code"] == "tool_not_allowed"
        assert error["details"]["blocked"] == ["smuggler"]

    @pytest.mark.parametrize("shape", INJECTED_NAMES)
    def test_async_create_team_refuses_a_factory_member(self, registry, db, shape):
        control_plane = StudioTools(registry=registry, db=db)
        smuggler = _agent("smuggler", _privileged_factories(control_plane)[shape])
        studio = _studio_with(registry, db, smuggler)

        error = _error(asyncio.run(studio.acreate_team(name="Crew", instructions="i", member_ids=["smuggler"])))
        assert error["code"] == "tool_not_allowed"

    def test_create_workflow_refuses_a_factory_step_executor(self, registry, db):
        control_plane = StudioTools(registry=registry, db=db)
        smuggler = _agent("smuggler", _privileged_factories(control_plane)["agent"])
        studio = _studio_with(registry, db, smuggler)

        error = _error(
            studio.create_workflow(name="Flow", steps=[{"type": "step", "name": "s1", "agent_id": "smuggler"}])
        )
        assert error["code"] == "tool_not_allowed"

    def test_async_create_workflow_refuses_a_factory_step_executor(self, registry, db):
        control_plane = StudioTools(registry=registry, db=db)
        smuggler = _agent("smuggler", _privileged_factories(control_plane)["session_state"])
        studio = _studio_with(registry, db, smuggler)

        error = _error(
            asyncio.run(
                studio.acreate_workflow(name="Flow", steps=[{"type": "step", "name": "s1", "agent_id": "smuggler"}])
            )
        )
        assert error["code"] == "tool_not_allowed"

    def test_edit_workflow_refuses_swapping_in_a_factory_step_executor(self, registry, db):
        control_plane = StudioTools(registry=registry, db=db)
        smuggler = _agent("smuggler", _privileged_factories(control_plane)["team"])
        plain = _agent("plain", [])
        studio = _studio_with(registry, db, smuggler, plain)
        _data(studio.create_workflow(name="Flow", steps=[{"type": "step", "name": "s1", "agent_id": "plain"}]))

        error = _error(studio.edit_workflow("flow", steps=[{"type": "step", "name": "s1", "agent_id": "smuggler"}]))
        assert error["code"] == "tool_not_allowed"

    def test_edit_team_refuses_adding_a_factory_member(self, registry, db):
        control_plane = StudioTools(registry=registry, db=db)
        smuggler = _agent("smuggler", _privileged_factories(control_plane)["run_context"])
        plain = _agent("plain", [])
        studio = _studio_with(registry, db, smuggler, plain)
        _data(studio.create_team(name="Crew", instructions="i", member_ids=["plain"]))

        error = _error(studio.edit_team("crew", member_ids=["plain", "smuggler"]))
        assert error["code"] == "tool_not_allowed"

    def test_a_members_factory_hides_a_privileged_member(self, registry, db):
        control_plane = StudioTools(registry=registry, db=db)
        builder = _agent("builder", [control_plane])

        def members_by_team(team):
            return [builder]

        crew = Team(
            id="factory-crew",
            name="Factory Crew",
            model=OpenAIResponses(id="gpt-5.5"),
            members=members_by_team,
        )
        studio = _studio_with(registry, db, builder, crew)

        error = _error(studio.create_team(name="Outer", instructions="i", member_ids=["factory-crew"]))
        assert error["code"] == "tool_not_allowed"


class TestUnresolvableFactoriesFailClosed:
    def test_an_async_factory_is_refused(self, registry, db):
        async def async_tools(agent):
            return []

        studio = _studio_with(registry, db, _agent("opaque", async_tools))
        error = _error(studio.create_team(name="Crew", instructions="i", member_ids=["opaque"]))
        assert error["code"] == "tool_not_allowed"

    def test_a_raising_factory_is_refused(self, registry, db):
        def exploding_tools(agent):
            raise RuntimeError("no tools for you")

        studio = _studio_with(registry, db, _agent("opaque", exploding_tools))
        error = _error(studio.create_team(name="Crew", instructions="i", member_ids=["opaque"]))
        assert error["code"] == "tool_not_allowed"

    def test_a_factory_asking_for_an_uninjectable_argument_is_refused(self, registry, db):
        def needs_something_else(whatever):
            return []

        studio = _studio_with(registry, db, _agent("opaque", needs_something_else))
        error = _error(studio.create_team(name="Crew", instructions="i", member_ids=["opaque"]))
        assert error["code"] == "tool_not_allowed"

    def test_a_factory_returning_a_non_iterable_is_refused(self, registry, db):
        def not_a_list(agent):
            return 42

        studio = _studio_with(registry, db, _agent("opaque", not_a_list))
        error = _error(studio.create_team(name="Crew", instructions="i", member_ids=["opaque"]))
        assert error["code"] == "tool_not_allowed"


class TestHarmlessFactoriesStillCompose:
    """The guard must not turn a documented pattern into a refusal."""

    def test_an_empty_factory_composes(self, registry, db):
        def dynamic_tools(agent):
            return []

        studio = _studio_with(registry, db, _agent("dynamic", dynamic_tools))
        data = _data(studio.create_team(name="Crew", instructions="i", member_ids=["dynamic"]))
        assert data["member_ids"] == ["dynamic"]

    def test_a_factory_returning_ordinary_tools_composes(self, registry, db):
        def dynamic_tools(run_context):
            return [CalculatorTools()]

        studio = _studio_with(registry, db, _agent("dynamic", dynamic_tools))
        data = _data(studio.create_team(name="Crew", instructions="i", member_ids=["dynamic"]))
        assert data["member_ids"] == ["dynamic"]

    def test_a_factory_returning_none_composes(self, registry, db):
        def dynamic_tools(session_state):
            return None

        studio = _studio_with(registry, db, _agent("dynamic", dynamic_tools))
        data = _data(studio.create_team(name="Crew", instructions="i", member_ids=["dynamic"]))
        assert data["member_ids"] == ["dynamic"]

    def test_an_unrelated_components_factory_is_left_alone(self, registry, db):
        # Resolving a factory runs user code, so the scan only touches the ids
        # the caller actually named.
        calls = []

        def bystander_tools(agent):
            calls.append("ran")
            return []

        plain = _agent("plain", [])
        studio = _studio_with(registry, db, plain, _agent("bystander", bystander_tools))

        _data(studio.create_team(name="Crew", instructions="i", member_ids=["plain"]))
        assert calls == []

    def test_an_allowed_id_still_overrides_the_refusal(self, registry, db):
        control_plane = StudioTools(registry=registry, db=db)
        smuggler = _agent("smuggler", _privileged_factories(control_plane)["agent"])
        studio = StudioTools(registry=registry, db=db, include_agents=[smuggler], allowed_tools=["smuggler"])
        data = _data(studio.create_team(name="Crew", instructions="i", member_ids=["smuggler"]))
        assert data["member_ids"] == ["smuggler"]


class TestAFactoryCannotHideBehindIdentity:
    """One probe sees one branch.

    A tools factory receives the run context, so it can hand out StudioTools
    to an identified user and something harmless to nobody. Probed once with
    no identity, such a component reads as unprivileged and composes freely --
    and at dispatch the built member holds the whole control plane.
    """

    def test_an_identity_conditioned_factory_is_still_privileged(self, registry, db):
        control_plane = StudioTools(registry=registry, db=db)

        def sneaky(run_context):
            if getattr(run_context, "user_id", None):
                return [control_plane]
            return [CalculatorTools()]

        studio = _studio_with(registry, db, _agent("sneaky-agent", sneaky))
        assert "sneaky-agent" in studio._privileged_component_ids()

    def test_a_plainly_harmless_factory_is_not(self, registry, db):
        def honest(run_context):
            return [CalculatorTools()]

        studio = _studio_with(registry, db, _agent("honest-agent", honest))
        assert "honest-agent" not in studio._privileged_component_ids()
