from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.run.agent import IntermediateRunContentEvent, RunContentEvent


def test_claude_with_openai_output_model():
    park_agent = Agent(
        model=Claude(id="claude-sonnet-4-20250514"),  # Main model to generate the content
        description="You are an expert on national parks and provide concise guides.",
        output_model=OpenAIChat(id="gpt-4o"),  # Model to parse the output
        telemetry=False,
    )

    response = park_agent.run("Tell me about Yosemite National Park.")

    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    assert response.messages is not None
    assert len(response.messages) > 0
    assistant_message_count = sum(1 for message in response.messages if message.role == "assistant")
    assert assistant_message_count == 1

    assert response.content == response.messages[-1].content


def test_openai_with_claude_output_model():
    park_agent = Agent(
        model=OpenAIChat(id="gpt-4o"),  # Main model to generate the content
        description="You are an expert on national parks and provide concise guides.",
        output_model=Claude(id="claude-sonnet-4-20250514"),  # Model to parse the output
        telemetry=False,
    )

    response = park_agent.run("Tell me about Yosemite National Park.")

    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    assert response.messages is not None
    assert len(response.messages) > 0
    assistant_message_count = sum(1 for message in response.messages if message.role == "assistant")
    assert assistant_message_count == 1

    assert response.content == response.messages[-1].content


async def test_openai_with_claude_output_model_async():
    park_agent = Agent(
        model=OpenAIChat(id="gpt-4o"),  # Main model to generate the content
        description="You are an expert on national parks and provide concise guides.",
        output_model=Claude(id="claude-sonnet-4-20250514"),  # Model to parse the output
        telemetry=False,
    )

    response = await park_agent.arun("Tell me about Yosemite National Park.")

    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    assert response.messages is not None
    assert len(response.messages) > 0
    assistant_message_count = sum(1 for message in response.messages if message.role == "assistant")
    assert assistant_message_count == 1

    assert response.content == response.messages[-1].content


def test_claude_with_openai_output_model_stream(shared_db):
    agent = Agent(
        model=Claude(id="claude-sonnet-4-20250514"),  # Main model to generate the content
        db=shared_db,
        description="You are an expert on national parks and provide concise guides.",
        output_model=OpenAIChat(id="gpt-4o"),  # Model to parse the output
        stream_events=True,
        telemetry=False,
    )

    response = agent.run("Tell me about Yosemite National Park.", session_id="test_session_id", stream=True)
    intermediate_run_response: bool = False
    run_response: bool = False
    run_id = None

    for event in response:
        if not run_id:
            run_id = event.run_id

        if isinstance(event, IntermediateRunContentEvent):
            assert isinstance(event.content, str)
            intermediate_run_response = True
        elif isinstance(event, RunContentEvent):
            assert isinstance(event.content, str)
            run_response = True

    # Assert the expected events were emitted
    assert intermediate_run_response
    assert run_response
    assert run_id is not None

    run_output = agent.get_run_output(session_id="test_session_id", run_id=run_id)

    # Assert the run output is populated correctly
    assert run_output is not None
    assert run_output.content is not None
    assert isinstance(run_output.content, str)
    assert len(run_output.content) > 0
    assert run_output.messages is not None
    assert len(run_output.messages) > 0

    # Assert the assistant message, in the run output, is populated correctly
    assistant_message_count = sum(1 for message in run_output.messages if message.role == "assistant")
    assert assistant_message_count == 1
    assert run_output.content == run_output.messages[-1].content


async def test_openai_with_claude_output_model_stream_async(shared_db):
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),  # Main model to generate the content
        db=shared_db,
        description="You are an expert on national parks and provide concise guides.",
        output_model=Claude(id="claude-sonnet-4-20250514"),  # Model to parse the output
        stream_events=True,
        telemetry=False,
    )

    intermediate_run_response: bool = False
    run_response: bool = False
    run_id = None

    async for event in agent.arun("Tell me about Yosemite National Park.", stream=True, session_id="test_session_id"):
        if not run_id:
            run_id = event.run_id

        if isinstance(event, IntermediateRunContentEvent):
            assert isinstance(event.content, str)
            intermediate_run_response = True
        elif isinstance(event, RunContentEvent):
            assert isinstance(event.content, str)
            run_response = True

    # Assert the expected events were emitted
    assert intermediate_run_response
    assert run_response
    assert run_id is not None

    run_output = agent.get_run_output(session_id="test_session_id", run_id=run_id)

    # Assert the run output is populated correctly
    assert run_output is not None
    assert run_output.content is not None
    assert isinstance(run_output.content, str)
    assert len(run_output.content) > 0
    assert run_output.messages is not None
    assert len(run_output.messages) > 0

    # Assert the assistant message, in the run output, is populated correctly
    assistant_message_count = sum(1 for message in run_output.messages if message.role == "assistant")
    assert assistant_message_count == 1
    assert run_output.content == run_output.messages[-1].content
