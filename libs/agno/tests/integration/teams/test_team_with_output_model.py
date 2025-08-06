from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.run.team import RunResponseContentEvent
from agno.team import Team

agent = Agent(
    model=Claude(id="claude-sonnet-4-20250514"),
    description="You are an expert on national parks and provide concise guides.",
    output_model=OpenAIChat(id="gpt-4o"),
    telemetry=False,
    monitoring=False,
)

team = Team(
    name="National Park Expert",
    members=[agent],
    output_model=OpenAIChat(id="gpt-4o"),
    instructions="You have no members, answer directly",
    description="You are an expert on national parks and provide concise guides.",
    telemetry=False,
    monitoring=False,
)


def test_team_with_output_model():
    response = team.run("Tell me about Yosemite National Park.")

    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    assert response.messages is not None
    assert len(response.messages) > 0

    assert response.content == response.messages[-1].content


def test_team_with_output_model_stream():
    response = team.run("Tell me about Yosemite National Park.", stream=True)
    for event in response:
        if isinstance(event, RunResponseContentEvent):
            assert isinstance(event.content, str)

    assert team.run_response.content is not None
    assert isinstance(team.run_response.content, str)
    assert len(team.run_response.content) > 0
    assert team.run_response.messages is not None
    assert len(team.run_response.messages) > 0

    assert team.run_response.content == team.run_response.messages[-1].content
