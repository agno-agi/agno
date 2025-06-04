from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team


def test_collaborate_team_basic():
    """Test basic functionality of a collaborate team."""
    agent1 = Agent(
        name="Agent 1",
        model=OpenAIChat("gpt-4o"),
        role="First perspective provider",
        instructions="Provide a perspective on the given topic.",
    )

    agent2 = Agent(
        name="Agent 2",
        model=OpenAIChat("gpt-4o"),
        role="Second perspective provider",
        instructions="Provide a different perspective on the given topic.",
    )

    team = Team(
        name="Collaborative Team",
        mode="collaborate",
        model=OpenAIChat("gpt-4o"),
        members=[agent1, agent2],
        instructions=[
            "Synthesize the perspectives from both team members.",
            "Provide a balanced view that incorporates insights from both perspectives.",
            "Only ask the members once for their perspectives.",
        ],
    )

    response = team.run("What are the pros and cons of remote work?")
    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    tools = response.tools
    assert len(tools) == 1
    member_responses = response.member_responses
    assert len(member_responses) == 2


def test_collaborate_team_with_structured_output():
    """Test collaborate team with structured output."""
    from pydantic import BaseModel

    class DebateResult(BaseModel):
        topic: str
        perspective_one: str
        perspective_two: str
        conclusion: str

    agent1 = Agent(name="Perspective One", model=OpenAIChat("gpt-4o"), role="First perspective provider")

    agent2 = Agent(name="Perspective Two", model=OpenAIChat("gpt-4o"), role="Second perspective provider")

    team = Team(
        name="Debate Team",
        mode="collaborate",
        model=OpenAIChat("gpt-4o"),
        members=[agent1, agent2],
        instructions=[
            "Have both agents provide their perspectives on the topic.",
            "Synthesize their views into a balanced conclusion.",
            "Only ask the members once for their perspectives.",
        ],
        response_model=DebateResult,
    )

    response = team.run("Is artificial general intelligence possible in the next decade?")

    assert response.content is not None
    assert isinstance(response.content, DebateResult)
    assert response.content.topic is not None
    assert response.content.perspective_one is not None
    assert response.content.perspective_two is not None
    assert response.content.conclusion is not None
