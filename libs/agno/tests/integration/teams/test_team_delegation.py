from typing import List

from pydantic import BaseModel

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team


def test_team_delegation():
    """Test basic functionality of a coordinator team."""

    def get_climate_change_info() -> str:
        return "Climate change is a global issue that requires urgent action."

    researcher = Agent(
        name="Researcher",
        model=OpenAIChat("gpt-4o"),
        role="Research information",
        tools=[get_climate_change_info],
    )

    writer = Agent(name="Writer", model=OpenAIChat("gpt-4o"), role="Write content based on research")

    team = Team(
        name="Content Team",
        model=OpenAIChat("gpt-4o"),
        members=[researcher, writer],
        instructions=[
            "First, have the Researcher gather information on the topic.",
            "Then, have the Writer create content based on the research.",
        ],
    )

    response = team.run("Write a short article about climate change solutions")

    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0


def test_respond_directly():
    """Test basic functionality of a coordinator team."""

    english_agent = Agent(name="English Agent", model=OpenAIChat("gpt-5-mini"), role="Answer in English")
    spanish_agent = Agent(name="Spanish Agent", model=OpenAIChat("gpt-5-mini"), role="Answer in Spanish")

    team = Team(
        name="Translation Team",
        model=OpenAIChat("gpt-5-mini"),
        determine_input_for_members=False,
        respond_directly=True,
        members=[english_agent, spanish_agent],
        instructions=[
            "If the user asks in English, respond in English. If the user asks in Spanish, respond in Spanish.",
            "Never answer directly, you must delegate the task to the appropriate agent.",
        ],
    )

    response = team.run("¿Cuéntame algo interesante sobre Madrid?")

    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    assert response.member_responses[0].content == response.content
    # Check the user message is the same as the input
    assert response.member_responses[0].messages[1].role == "user"
    assert response.member_responses[0].messages[1].content == "¿Cuéntame algo interesante sobre Madrid?"


def test_use_input_directly_structured_input():
    """Test basic functionality of a coordinator team."""

    class ResearchRequest(BaseModel):
        topic: str
        focus_areas: List[str]
        target_audience: str
        sources_required: int

    researcher = Agent(name="Researcher", model=OpenAIChat("gpt-4o"), role="Research information")

    team = Team(
        name="Content Team",
        model=OpenAIChat("gpt-4o"),
        determine_input_for_members=False,
        members=[researcher],
        instructions=[
            "Have the Researcher gather information on the topic.",
        ],
    )

    research_request = ResearchRequest(
        topic="AI Agent Frameworks",
        focus_areas=["AI Agents", "Framework Design", "Developer Tools", "Open Source"],
        target_audience="Software Developers and AI Engineers",
        sources_required=7,
    )

    response = team.run(
        input=research_request,
    )

    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    # Check the user message is the same as the input
    assert response.member_responses[0].messages[1].role == "user"
    assert response.member_responses[0].messages[1].content == research_request.model_dump_json(
        indent=2, exclude_none=True
    )


def test_delegate_to_all_members():
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
        delegate_to_all_members=True,
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
    assert tools is not None
    assert len(tools) == 1
