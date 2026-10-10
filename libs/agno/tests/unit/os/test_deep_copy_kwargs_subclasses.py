"""deep_copy of Agent, Team and Workflow subclasses whose __init__ forwards **kwargs.

Such a subclass declares none of the fields it accepts, so a copy rebuilt through
its own signature came out blank (Agent, Workflow) or raised (Team, which requires
members). The copy is now rebuilt through the base initializer, so these tests pin
that it keeps its configuration, isolates mutable state and still runs.
"""

import json
from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.os.utils import get_agent_by_id, get_team_by_id, get_workflow_by_id
from agno.team import Team
from agno.workflow import Workflow
from agno.workflow.step import Step


class _ScriptedModel(Model):
    """Replays scripted turns offline: ('tool', name, args, id) or ('content', text)."""

    def __init__(self, script: List[tuple]):
        super().__init__(id="scripted", name="scripted", provider="test")
        self._script = list(script)
        self._i = 0

    def _next(self) -> ModelResponse:
        turn = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        if turn[0] == "tool":
            _, name, args, tool_call_id = turn
            response = ModelResponse(role="assistant")
            response.tool_calls = [
                {"id": tool_call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
            ]
            return response
        response = ModelResponse(content=turn[1], role="assistant")
        response.event = ModelResponseEvent.assistant_response.value
        return response

    def invoke(self, *args, **kwargs):
        return self._next()

    async def ainvoke(self, *args, **kwargs):
        return self._next()

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


def add(a: int, b: int) -> str:
    """Add two numbers."""
    return str(a + b)


class Helper(Agent):
    """Hardcodes its identity and forwards everything else."""

    def __init__(self, **kwargs):
        super().__init__(name="helper", **kwargs)


class PolicyHelper(Agent):
    """Keeps an attribute of its own next to the forwarded fields."""

    def __init__(self, policy=None, **kwargs):
        self.policy = policy if policy is not None else {"mode": "strict"}
        super().__init__(name="policy-helper", **kwargs)


class Crew(Team):
    def __init__(self, **kwargs):
        super().__init__(name="crew", **kwargs)


class Flow(Workflow):
    def __init__(self, **kwargs):
        super().__init__(name="flow", **kwargs)


class TestAgentSubclass:
    def test_copy_keeps_configuration_and_identity(self):
        original = Helper(
            id="helper-id",
            instructions=["be brief"],
            session_state={"count": 1},
            metadata={"owner": "ops"},
            tools=[add],
        )

        copied = original.deep_copy()

        assert type(copied) is Helper
        assert copied is not original
        assert copied.name == "helper"
        assert copied.id == "helper-id"
        assert copied.instructions == ["be brief"]
        assert copied.session_state == {"count": 1}
        assert copied.metadata == {"owner": "ops"}
        assert copied.tools == [add]
        assert copied.to_dict() == original.to_dict()

    def test_copies_do_not_share_mutable_state(self):
        original = Helper(id="helper-id", instructions=["be brief"], session_state={"count": 1})

        first = original.deep_copy()
        second = original.deep_copy()
        first.session_state["count"] = 99
        first.instructions.append("leaked")

        assert original.session_state == {"count": 1}
        assert second.session_state == {"count": 1}
        assert original.instructions == ["be brief"]
        assert second.instructions == ["be brief"]

    def test_copy_carries_the_subclass_attributes_without_sharing_them(self):
        original = PolicyHelper(policy={"mode": "lenient"}, id="policy-id")

        copied = original.deep_copy()
        copied.policy["mode"] = "changed"

        assert copied.name == "policy-helper"
        assert copied.id == "policy-id"
        assert original.policy == {"mode": "lenient"}

    def test_update_can_override_a_hardcoded_field(self):
        original = Helper(id="helper-id", instructions="be brief")

        copied = original.deep_copy(update={"name": "renamed", "instructions": "be thorough"})

        assert copied.name == "renamed"
        assert copied.instructions == "be thorough"
        assert copied.id == "helper-id"
        assert original.name == "helper"
        assert original.instructions == "be brief"

    def test_update_can_replace_a_subclass_attribute(self):
        original = PolicyHelper(policy={"mode": "lenient"}, id="policy-id")

        copied = original.deep_copy(update={"policy": {"mode": "audit"}})

        assert copied.policy == {"mode": "audit"}
        assert original.policy == {"mode": "lenient"}

    def test_update_with_an_unknown_field_raises(self):
        original = Helper(id="helper-id")

        with pytest.raises(TypeError, match="unexpected field 'not_a_field'"):
            original.deep_copy(update={"not_a_field": 1})

    def test_copy_runs_offline(self):
        original = Helper(
            id="helper-id",
            model=_ScriptedModel([("tool", "add", {"a": 2, "b": 3}, "call-1"), ("content", "5")]),
            tools=[add],
        )

        response = original.deep_copy().run("add 2 and 3")

        assert response.content == "5"
        assert response.agent_id == "helper-id"
        assert response.agent_name == "helper"
        assert [t.result for t in response.tools or []] == ["5"]

    @pytest.mark.asyncio
    async def test_copy_runs_offline_async(self):
        original = Helper(id="helper-id", model=_ScriptedModel([("content", "async answer")]))

        response = await original.deep_copy().arun("hi")

        assert response.content == "async answer"
        assert response.agent_id == "helper-id"

    def test_agentos_fresh_copy_keeps_identity(self):
        original = Helper(id="helper-id", instructions="be brief")

        fresh = get_agent_by_id("helper-id", [original], create_fresh=True)

        assert fresh is not None
        assert fresh is not original
        assert fresh.id == "helper-id"
        assert fresh.instructions == "be brief"


class TestTeamSubclass:
    def test_copy_keeps_members_and_configuration(self):
        original = Crew(id="crew-id", members=[Agent(id="m1", name="M1")], instructions="lead")

        copied = original.deep_copy()

        assert type(copied) is Crew
        assert copied.name == "crew"
        assert copied.id == "crew-id"
        assert copied.instructions == "lead"
        assert [m.id for m in copied.members] == ["m1"]
        assert copied.to_dict() == original.to_dict()

    def test_hardcoded_members_are_not_shared_between_copies(self):
        shared = Agent(id="shared", name="Shared", session_state={"seen": []})

        class PinnedCrew(Team):
            def __init__(self, **kwargs):
                super().__init__(name="pinned", members=[shared], **kwargs)

        original = PinnedCrew(id="pinned-id")

        first = original.deep_copy()
        second = original.deep_copy()
        first.members[0].session_state["seen"].append("first")

        assert first.members[0] is not shared
        assert second.members[0] is not first.members[0]
        assert second.members[0].session_state == {"seen": []}
        assert shared.session_state == {"seen": []}

    def test_copy_of_a_team_holding_a_kwargs_member(self):
        member = Helper(id="helper-id", instructions="be brief", session_state={"n": 0})
        original = Team(id="team-id", name="Team", members=[member])

        first = original.deep_copy()
        second = original.deep_copy()
        first.members[0].session_state["n"] = 1

        assert type(first.members[0]) is Helper
        assert first.members[0] is not member
        assert first.members[0].id == "helper-id"
        assert first.members[0].instructions == "be brief"
        assert second.members[0].session_state == {"n": 0}
        assert member.session_state == {"n": 0}

    def test_copy_runs_offline(self):
        original = Crew(
            id="crew-id",
            model=_ScriptedModel([("content", "team answer")]),
            members=[Helper(id="helper-id", model=_ScriptedModel([("content", "member answer")]))],
        )

        response = original.deep_copy().run("hi")

        assert response.content == "team answer"
        assert response.team_id == "crew-id"
        assert response.team_name == "crew"

    def test_agentos_fresh_copy_keeps_identity(self):
        original = Crew(id="crew-id", members=[Agent(id="m1", name="M1")])

        fresh = get_team_by_id("crew-id", [original], create_fresh=True)

        assert fresh is not None
        assert fresh is not original
        assert fresh.id == "crew-id"
        assert [m.id for m in fresh.members] == ["m1"]
        assert fresh.members[0] is not original.members[0]


class TestWorkflowSubclass:
    def test_copy_keeps_steps_and_configuration(self):
        step_agent = Agent(id="step-agent", name="StepAgent")
        original = Flow(id="flow-id", description="does work", steps=[Step(name="s1", agent=step_agent)])

        copied = original.deep_copy()

        assert type(copied) is Flow
        assert copied.name == "flow"
        assert copied.id == "flow-id"
        assert copied.description == "does work"
        assert [s.name for s in copied.steps] == ["s1"]
        assert copied.steps[0].agent.id == "step-agent"
        assert copied.steps[0].agent is not step_agent

    def test_copies_do_not_share_session_state(self):
        original = Flow(id="flow-id", session_state={"items": []}, steps=[])

        first = original.deep_copy()
        first.session_state["items"].append("first")

        assert original.session_state == {"items": []}
        assert original.deep_copy().session_state == {"items": []}

    def test_update_overrides_a_hardcoded_field(self):
        original = Flow(id="flow-id", steps=[])

        copied = original.deep_copy(update={"name": "renamed"})

        assert copied.name == "renamed"
        assert original.name == "flow"

    def test_copy_runs_offline(self):
        step_agent = Agent(id="step-agent", name="StepAgent", model=_ScriptedModel([("content", "step answer")]))
        original = Flow(id="flow-id", steps=[Step(name="s1", agent=step_agent)])

        response = original.deep_copy().run("hi")

        assert response.content == "step answer"
        assert response.workflow_id == "flow-id"
        assert response.workflow_name == "flow"

    def test_agentos_fresh_copy_keeps_identity(self):
        original = Flow(id="flow-id", steps=[Step(name="s1", agent=Agent(id="step-agent", name="StepAgent"))])

        fresh = get_workflow_by_id("flow-id", [original], create_fresh=True)

        assert fresh is not None
        assert fresh is not original
        assert fresh.id == "flow-id"
        assert [s.name for s in fresh.steps] == ["s1"]


def test_studio_runner_dispatch_copy_passes_its_fidelity_checks():
    from agno.tools.studio_runner import StudioRunnerTools

    agent = Helper(id="helper-id", instructions="be brief")
    team = Crew(id="crew-id", members=[Helper(id="member-id")])

    fresh_agent = StudioRunnerTools._fresh_copy(agent)
    fresh_team = StudioRunnerTools._fresh_copy(team)

    assert fresh_agent is not agent
    assert (fresh_agent.id, fresh_agent.name, fresh_agent.instructions) == ("helper-id", "helper", "be brief")
    assert fresh_team is not team
    assert fresh_team.members[0] is not team.members[0]
    assert fresh_team.members[0].id == "member-id"


def test_a_subclass_with_declared_parameters_is_still_rebuilt_through_its_own_init():
    calls = []

    class Declared(Agent):
        def __init__(self, name=None, id=None):
            calls.append(name)
            super().__init__(name=name, id=id)

    original = Declared(name="declared", id="declared-id")

    copied = original.deep_copy()

    assert calls == ["declared", "declared"]
    assert copied.name == "declared"
    assert copied.id == "declared-id"
