from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.run.response import RunResponseContentEvent


def test_claude_with_openai_output_model():
    park_agent = Agent(
        model=Claude(id="claude-sonnet-4-20250514"),  # Main model to generate the content
        description="You are an expert on national parks and provide concise guides.",
        output_model=OpenAIChat(id="gpt-4o"),  # Model to parse the output
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


def test_claude_with_openai_output_model_stream():
    agent = Agent(
        model=Claude(id="claude-sonnet-4-20250514"),  # Main model to generate the content
        description="You are an expert on national parks and provide concise guides.",
        output_model=OpenAIChat(id="gpt-4o"),  # Model to parse the output
    )

    response = agent.run("Tell me about Yosemite National Park.", stream=True)

    for event in response:
        if isinstance(event, RunResponseContentEvent):
            assert isinstance(event.content, str)

    assert agent.run_response.content is not None
    assert isinstance(agent.run_response.content, str)
    assert len(agent.run_response.content) > 0
    assert agent.run_response.messages is not None
    assert len(agent.run_response.messages) > 0
    assistant_message_count = sum(1 for message in agent.run_response.messages if message.role == "assistant")
    assert assistant_message_count == 1

    assert agent.run_response.content == agent.run_response.messages[-1].content
