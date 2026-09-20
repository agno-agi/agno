"""Live tests for Jev leading a team. Need TYPESAFE_API_KEY and OPENAI_API_KEY (the members answer with OpenAI)."""

from typing import Literal

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.models.typesafe import Jev
from agno.run.base import RunStatus
from agno.team import Team, TeamMode


def _team(mode: TeamMode = TeamMode.route, **leader_kwargs) -> Team:
    billing = Agent(
        name="Billing",
        id="billing",
        role="Charges, refunds and invoices",
        model=OpenAIResponses(id="gpt-5.6-luna"),
        instructions="Answer in one short sentence that starts with [BILLING].",
    )
    tech = Agent(
        name="Tech",
        id="tech",
        role="Bugs, outages and integrations",
        model=OpenAIResponses(id="gpt-5.6-luna"),
        instructions="Answer in one short sentence that starts with [TECH].",
    )
    return Team(
        name="Support",
        mode=mode,
        model=Jev(**leader_kwargs),
        members=[billing, tech],
        instructions=["Anything about money goes to billing."],
        telemetry=False,
    )


@pytest.mark.parametrize(
    "request_text, tag",
    [
        ("I was charged twice for order A-104.", "[BILLING]"),
        ("The API returns a 500 error on every request since this morning.", "[TECH]"),
    ],
)
def test_route(request_text, tag):
    response = _team().run(request_text)
    assert response.status == RunStatus.completed
    # The member's reply is returned as written, with nothing from the leader in front of it
    assert str(response.content).startswith(tag)
    assert [t.tool_name for t in response.tools or []] == ["delegate_task_to_member"]


@pytest.mark.asyncio
async def test_route_async():
    response = await _team().arun("Please send me last month's invoice.")
    assert str(response.content).startswith("[BILLING]")


def test_route_stream():
    team = _team()
    events = list(team.run("Your webhook integration stopped firing.", stream=True))
    assert "[TECH]" in "".join(str(getattr(e, "content", "") or "") for e in events)


def test_broadcast_reaches_every_member():
    response = _team(mode=TeamMode.broadcast).run("A customer cannot pay: checkout fails with an error.")
    assert response.status == RunStatus.completed
    assert "[BILLING]" in str(response.content) and "[TECH]" in str(response.content)


def test_coordinate_mode_is_refused():
    response = _team(mode=TeamMode.coordinate).run("I was charged twice.")
    assert response.status == RunStatus.error
    assert "Jev can only lead route or broadcast teams" in str(response.content)


def test_closed_set_tool_call():
    def set_thermostat(mode: Literal["heat", "cool", "off"]) -> str:
        """Set the thermostat of the house.

        Args:
            mode: heat warms the house, cool lowers the temperature, off turns the system off
        """
        return f"thermostat set to {mode}"

    def lock_doors() -> str:
        """Lock every door of the house."""
        return "doors locked"

    agent = Agent(model=Jev(), tools=[set_thermostat, lock_doors], telemetry=False)
    assert agent.run("It is boiling in here, make it colder.").content == "thermostat set to cool"
    assert agent.run("I am leaving, secure the house.").content == "doors locked"
