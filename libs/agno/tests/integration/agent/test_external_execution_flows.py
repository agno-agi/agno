import pytest

from agno.agent import Agent, RunOutput  # noqa
from agno.models.openai import OpenAIChat
from agno.tools.decorator import tool


def test_tool_call_requires_external_execution(shared_db):
    @tool(external_execution=True)
    def send_email(to: str, subject: str, body: str):
        pass

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[send_email],
        db=shared_db,
        markdown=True,
        telemetry=False,
    )

    response = agent.run("Send an email to john@doe.com with the subject 'Test' and the body 'Hello, how are you?'")

    assert response.is_paused and response.tools is not None
    assert response.tools[0].external_execution_required
    assert response.tools[0].tool_name == "send_email"
    assert response.tools[0].tool_args == {"to": "john@doe.com", "subject": "Test", "body": "Hello, how are you?"}

    # Mark the tool as confirmed
    response.tools[0].result = "Email sent to john@doe.com with subject Test and body Hello, how are you?"

    response = agent.continue_run(response)
    assert response.is_paused is False


def test_tool_call_requires_external_execution_stream(shared_db):
    @tool(external_execution=True)
    def send_email(to: str, subject: str, body: str):
        pass

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        db=shared_db,
        tools=[send_email],
        markdown=True,
        telemetry=False,
    )

    found_external_execution = False
    for response in agent.run(
        "Send an email to john@doe.com with the subject 'Test' and the body 'Hello, how are you?'", stream=True
    ):
        if response.is_paused:
            assert response.tools[0].external_execution_required  # type: ignore
            assert response.tools[0].tool_name == "send_email"  # type: ignore
            assert response.tools[0].tool_args == {  # type: ignore
                "to": "john@doe.com",
                "subject": "Test",
                "body": "Hello, how are you?",
            }

            # Mark the tool as confirmed
            response.tools[0].result = "Email sent to john@doe.com with subject Test and body Hello, how are you?"  # type: ignore
            found_external_execution = True
    assert found_external_execution, "No tools were found to require external execution"

    found_external_execution = False
    for response in agent.continue_run(run_id=response.run_id, updated_tools=response.tools, stream=True):
        if response.is_paused:
            found_external_execution = True
    assert found_external_execution is False, "Some tools still require external execution"


@pytest.mark.asyncio
async def test_tool_call_requires_external_execution_async(shared_db):
    @tool(external_execution=True)
    async def send_email(to: str, subject: str, body: str):
        pass

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[send_email],
        db=shared_db,
        markdown=True,
        telemetry=False,
    )

    response = await agent.arun(
        "Send an email to john@doe.com with the subject 'Test' and the body 'Hello, how are you?'"
    )

    assert response.is_paused and response.tools is not None
    assert response.tools[0].external_execution_required  # type: ignore
    assert response.tools[0].tool_name == "send_email"  # type: ignore
    assert response.tools[0].tool_args == {  # type: ignore
        "to": "john@doe.com",
        "subject": "Test",
        "body": "Hello, how are you?",
    }

    # Mark the tool as confirmed
    response.tools[0].result = "Email sent to john@doe.com with subject Test and body Hello, how are you?"  # type: ignore

    response = await agent.acontinue_run(run_id=response.run_id, updated_tools=response.tools)
    assert response.is_paused is False


def test_tool_call_requires_external_execution_error(shared_db):
    @tool(external_execution=True)
    def send_email(to: str, subject: str, body: str):
        pass

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[send_email],
        db=shared_db,
        markdown=True,
        telemetry=False,
    )

    response = agent.run("Send an email to john@doe.com with the subject 'Test' and the body 'Hello, how are you?'")

    # Check that we cannot continue without confirmation
    with pytest.raises(ValueError):
        response = agent.continue_run(response)


@pytest.mark.asyncio
async def test_tool_call_requires_external_execution_stream_async(shared_db):
    @tool(external_execution=True)
    async def send_email(to: str, subject: str, body: str):
        pass

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[send_email],
        db=shared_db,
        markdown=True,
        telemetry=False,
    )

    found_external_execution = False
    async for response in agent.arun(
        "Send an email to john@doe.com with the subject 'Test' and the body 'Hello, how are you?'", stream=True
    ):
        if response.is_paused:
            assert response.tools[0].external_execution_required  # type: ignore
            assert response.tools[0].tool_name == "send_email"  # type: ignore
            assert response.tools[0].tool_args == {  # type: ignore
                "to": "john@doe.com",
                "subject": "Test",
                "body": "Hello, how are you?",
            }

            # Mark the tool as confirmed
            response.tools[0].result = "Email sent to john@doe.com with subject Test and body Hello, how are you?"  # type: ignore
            found_external_execution = True
    assert found_external_execution, "No tools were found to require external execution"

    found_external_execution = False
    async for response in agent.acontinue_run(run_id=response.run_id, updated_tools=response.tools, stream=True):
        if response.is_paused:
            found_external_execution = True
    assert found_external_execution is False, "Some tools still require external execution"


def test_tool_call_multiple_requires_external_execution(shared_db):
    @tool(external_execution=True)
    def get_the_weather(city: str):
        pass

    def get_activities(city: str):
        pass

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_the_weather, get_activities],
        db=shared_db,
        markdown=True,
        telemetry=False,
    )

    response = agent.run("What is the weather in Tokyo and what are the activities?")

    assert response.is_paused and response.tools is not None
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
