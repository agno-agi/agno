import pytest

from agno.agent import Agent, RunResponse  # noqa
from agno.models.openai import OpenAIChat
from agno.tools.decorator import tool


def test_tool_call_requires_external_execution():
    @tool(external_execution=True)
    def send_email(to: str, subject: str, body: str):
        pass

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[send_email],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("Send an email to john@doe.com with the subject 'Test' and the body 'Hello, how are you?'")

    assert response.is_paused
    assert response.tools[0].external_execution_required
    assert response.tools[0].tool_name == "send_email"
    assert response.tools[0].tool_args == {"to": "john@doe.com", "subject": "Test", "body": "Hello, how are you?"}

    # Mark the tool as confirmed
    response.tools[0].result = "Email sent to john@doe.com with subject Test and body Hello, how are you?"

    response = agent.continue_run(response)
    assert response.is_paused is False


def test_tool_call_requires_external_execution_stream():
    @tool(external_execution=True)
    def send_email(to: str, subject: str, body: str):
        pass

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[send_email],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    found_external_execution = False
    for response in agent.run(
        "Send an email to john@doe.com with the subject 'Test' and the body 'Hello, how are you?'", stream=True
    ):
        if response.is_paused:
            assert response.tools[0].external_execution_required
            assert response.tools[0].tool_name == "send_email"
            assert response.tools[0].tool_args == {
                "to": "john@doe.com",
                "subject": "Test",
                "body": "Hello, how are you?",
            }

            # Mark the tool as confirmed
            response.tools[0].result = "Email sent to john@doe.com with subject Test and body Hello, how are you?"
            found_external_execution = True
    assert found_external_execution, "No tools were found to require external execution"

    found_external_execution = False
    for response in agent.continue_run(response, stream=True):
        if response.is_paused:
            found_external_execution = True
    assert found_external_execution is False, "Some tools still require external execution"


@pytest.mark.asyncio
async def test_tool_call_requires_external_execution_async():
    @tool(external_execution=True)
    async def send_email(to: str, subject: str, body: str):
        pass

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[send_email],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = await agent.arun("What is the weather in Tokyo?")

    assert response.is_paused
    assert response.tools[0].external_execution_required
    assert response.tools[0].tool_name == "send_email"
    assert response.tools[0].tool_args == {"to": "john@doe.com", "subject": "Test", "body": "Hello, how are you?"}

    # Mark the tool as confirmed
    response.tools[0].result = "Email sent to john@doe.com with subject Test and body Hello, how are you?"

    response = await agent.acontinue_run(response)
    assert response.is_paused is False


def test_tool_call_requires_external_execution_error():
    @tool(external_execution=True)
    def send_email(to: str, subject: str, body: str):
        pass

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[send_email],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("Send an email to john@doe.com with the subject 'Test' and the body 'Hello, how are you?'")

    # Check that we cannot continue without confirmation
    with pytest.raises(ValueError):
        response = agent.continue_run(response)


@pytest.mark.asyncio
async def test_tool_call_requires_external_execution_stream_async():
    @tool(external_execution=True)
    async def send_email(to: str, subject: str, body: str):
        pass

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[send_email],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    found_external_execution = False
    async for response in await agent.arun(
        "Send an email to john@doe.com with the subject 'Test' and the body 'Hello, how are you?'", stream=True
    ):
        if response.is_paused:
            assert response.tools[0].external_execution_required
            assert response.tools[0].tool_name == "send_email"
            assert response.tools[0].tool_args == {
                "to": "john@doe.com",
                "subject": "Test",
                "body": "Hello, how are you?",
            }

            # Mark the tool as confirmed
            response.tools[0].result = "Email sent to john@doe.com with subject Test and body Hello, how are you?"
            found_external_execution = True
    assert found_external_execution, "No tools were found to require external execution"

    found_external_execution = False
    async for response in await agent.acontinue_run(response, stream=True):
        if response.is_paused:
            found_external_execution = True
    assert found_external_execution is False, "Some tools still require external execution"


def test_tool_call_multiple_requires_external_execution():
    @tool(external_execution=True)
    def get_the_weather(city: str):
        pass

    def get_activities(city: str):
        pass

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather, get_activities],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run("What is the weather in Tokyo and what are the activities?")

    assert response.is_paused
    tool_found = False
    for _t in response.tools:
        if _t.external_execution_required:
            tool_found = True
            assert _t.tool_name == "get_the_weather"
            assert _t.tool_args == {"city": "Tokyo"}
            _t.result = "It is currently 70 degrees and cloudy in Tokyo"

    assert tool_found, "No tool was found to require external execution"

    response = agent.continue_run(response)
    assert response.is_paused is False
    assert response.content
