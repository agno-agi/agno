from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.run.team import IntermediateRunContentEvent, RunContentEvent
from agno.team import Team

agent = Agent(
    model=Claude(id="claude-sonnet-4-20250514"),
    description="You are an expert on national parks and provide concise guides.",
    output_model=OpenAIChat(id="gpt-4o"),
    telemetry=False,
)

team = Team(
    name="National Park Expert",
    members=[agent],
    output_model=OpenAIChat(id="gpt-4o"),
    instructions="You have no members, answer directly",
    description="You are an expert on national parks and provide concise guides.",
    stream_events=True,
    telemetry=False,
)


def test_team_with_output_model():
    response = team.run("Tell me about Yosemite National Park.")

    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    assert response.messages is not None
    assert len(response.messages) > 0
    # Note: With output_model, content may be reformatted, so we just check it exists
    # and contains relevant information about Yosemite
    assert "Yosemite" in response.content


async def test_team_with_output_model_async():
    response = await team.arun("Tell me about Yosemite National Park.")
    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    assert response.messages is not None
    assert len(response.messages) > 0
    # Note: With output_model, content may be reformatted, so we just check it exists
    # and contains relevant information about Yosemite
    assert "Yosemite" in response.content


def test_team_with_output_model_stream():
    response = team.run("Tell me about Yosemite National Park.", stream=True)
    run_response_content_event: bool = False
    intermediate_run_response_content_event: bool = False
    final_response = None

    for event in response:
        print(event)
        print(type(event))
        if isinstance(event, RunContentEvent):
            run_response_content_event = True
            assert isinstance(event.content, str)
            final_response = event  # Capture the final content event
        if isinstance(event, IntermediateRunContentEvent):
            intermediate_run_response_content_event = True
            assert isinstance(event.content, str)

    assert run_response_content_event
    assert intermediate_run_response_content_event

    # Validate the final response content from the last event
    if final_response:
        assert final_response.content is not None
        assert isinstance(final_response.content, str)
        assert len(final_response.content) > 0


async def test_team_with_output_model_stream_async():
    run_response_content_event: bool = False
    intermediate_run_response_content_event: bool = False
    final_response = None

    async for event in team.arun("Tell me about Yosemite National Park.", stream=True):
        if isinstance(event, RunContentEvent):
            run_response_content_event = True
            assert isinstance(event.content, str)
            final_response = event  # Capture the final content event
        if isinstance(event, IntermediateRunContentEvent):
            intermediate_run_response_content_event = True
            assert isinstance(event.content, str)

    assert run_response_content_event
    assert intermediate_run_response_content_event

    # Validate the final response content from the last event
    if final_response:
        assert final_response.content is not None
        assert isinstance(final_response.content, str)
        assert len(final_response.content) > 0
