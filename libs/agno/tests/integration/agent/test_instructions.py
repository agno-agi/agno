import pytest

from agno.agent import Agent
from agno.team import Team


def test_callable_instructions():
    def instructions(agent: Agent, team: Team) -> str:
        return "You are a helpful assistant."

    agent = Agent(instructions=instructions)
    team = Team(instructions=instructions, members=[])

    agent.run("Hello")
    team.run("Hello")

    assert True, "No Errors"


@pytest.mark.asyncio
async def test_async_callable_instructions():
    async def instructions(agent: Agent, team: Team) -> str:
        return "You are a helpful assistant."

    agent = Agent(instructions=instructions)
    team = Team(instructions=instructions, members=[])

    await agent.arun("Hello")
    await team.arun("Hello")


def test_callable_system_message():
    def instructions(agent: Agent, team: Team) -> str:
        return "You are a helpful assistant."

    agent = Agent(system_message=instructions)
    team = Team(system_message=instructions, members=[])

    agent.run("Hello")
    team.run("Hello")

    assert True, "No Errors"


@pytest.mark.asyncio
async def test_async_callable_system_message():
    async def instructions(agent: Agent, team: Team) -> str:
        return "You are a helpful assistant."

    agent = Agent(system_message=instructions)
    team = Team(system_message=instructions, members=[])

    await agent.arun("Hello")
    await team.arun("Hello")
