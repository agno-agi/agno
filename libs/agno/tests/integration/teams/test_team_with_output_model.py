from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.run.team import IntermediateRunResponseContentEvent, RunResponseContentEvent
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
    stream_intermediate_steps=True,
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


async def test_team_with_output_model_async():
    response = await team.arun("Tell me about Yosemite National Park.")
    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    assert response.messages is not None
    assert len(response.messages) > 0
    assert response.content == response.messages[-1].content


def test_team_with_output_model_stream():
    response = team.run("Tell me about Yosemite National Park.", stream=True)
    run_response_content_event: bool = False
    intermediate_run_response_content_event: bool = False
    for event in response:
        print(event)
        print(type(event))
        if isinstance(event, RunResponseContentEvent):
            run_response_content_event = True
            assert isinstance(event.content, str)
        if isinstance(event, IntermediateRunResponseContentEvent):
            intermediate_run_response_content_event = True
            assert isinstance(event.content, str)

    assert run_response_content_event
    assert intermediate_run_response_content_event

    assert team.run_response.content is not None
    assert isinstance(team.run_response.content, str)
    assert len(team.run_response.content) > 0
    assert team.run_response.messages is not None
    assert len(team.run_response.messages) > 0

    assert team.run_response.content == team.run_response.messages[-1].content


async def test_team_with_output_model_stream_async():
    response = await team.arun("Tell me about Yosemite National Park.", stream=True)
    run_response_content_event: bool = False
    intermediate_run_response_content_event: bool = False
    async for event in response:
        if isinstance(event, RunResponseContentEvent):
            run_response_content_event = True
            assert isinstance(event.content, str)
        if isinstance(event, IntermediateRunResponseContentEvent):
            intermediate_run_response_content_event = True
            assert isinstance(event.content, str)

    assert run_response_content_event
    assert intermediate_run_response_content_event

    assert team.run_response.content is not None
    assert isinstance(team.run_response.content, str)
    assert len(team.run_response.content) > 0
    assert team.run_response.messages is not None
    assert len(team.run_response.messages) > 0

    assert team.run_response.content == team.run_response.messages[-1].content
