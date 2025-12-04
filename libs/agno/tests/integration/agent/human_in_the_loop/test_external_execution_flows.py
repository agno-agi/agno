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


def test_run_requirement_external_execution(shared_db):
    """Test a HITL external execution flow using RunRequirements"""

    @tool(external_execution=True)
    def send_email(to: str, subject: str, body: str):
        pass

    session_id = "test_session_external_execution"
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[send_email],
        db=shared_db,
        telemetry=False,
    )

    # Initial run that requires external execution
    response = agent.run(
        "Send an email to john@doe.com with the subject 'Test' and the body 'Hello, how are you?'",
        session_id=session_id,
    )

    # Verify the run is paused and has active requirements
    assert response.is_paused
    assert len(response.active_requirements) == 1

    # Get the requirement and verify it needs external execution
    requirement = response.active_requirements[0]
    assert requirement.needs_external_execution
    assert requirement.tool_execution and requirement.tool_execution.tool_name == "send_email"
    assert requirement.tool_execution and requirement.tool_execution.tool_args == {
        "to": "john@doe.com",
        "subject": "Test",
        "body": "Hello, how are you?",
    }

    # Use the new DX to set external execution result
    tool_args = requirement.tool_execution and requirement.tool_execution.tool_args
    assert tool_args is not None
    result = f"Email sent to {tool_args['to']} with subject {tool_args['subject']}"
    requirement.set_external_execution_result(result)

    # Verify the result was set
    assert requirement.tool_execution and requirement.tool_execution.result == result

    # Continue the run with run_id and requirements
    response = agent.continue_run(run_id=response.run_id, requirements=response.requirements, session_id=session_id)

    # Verify the run completed successfully
    assert response.is_paused is False
    assert response.tools is not None
    assert response.tools[0].result == result


def test_run_requirement_external_execution_with_entrypoint(shared_db):
    """Test a HITL external execution flow by calling the tool entrypoint directly"""

    @tool(external_execution=True)
    def execute_shell_command(command: str) -> str:
        """Execute a shell command (only ls is supported for testing)"""
        if command.startswith("echo"):
            return command.replace("echo ", "")
        else:
            return f"Executed: {command}"

    session_id = "test_session_external_entrypoint"
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[execute_shell_command],
        db=shared_db,
        telemetry=False,
    )

    # Initial run that requires external execution
    response = agent.run("Run the command 'echo Hello World'", session_id=session_id)

    # Verify the run is paused
    assert response.is_paused
    assert len(response.active_requirements) == 1

    # Get the requirement
    requirement = response.active_requirements[0]
    assert requirement.needs_external_execution
    assert requirement.tool_execution and requirement.tool_execution.tool_name == "execute_shell_command"

    # Execute the tool externally using the entrypoint
    tool_args = requirement.tool_execution and requirement.tool_execution.tool_args
    assert tool_args is not None
    assert execute_shell_command.entrypoint is not None
    result = execute_shell_command.entrypoint(**tool_args)  # type: ignore
    requirement.set_external_execution_result(result)

    # Continue the run
    response = agent.continue_run(run_id=response.run_id, requirements=response.requirements, session_id=session_id)

    # Verify completion
    assert response.is_paused is False
    assert response.tools is not None
    assert response.tools[0].result is not None
    assert "Hello World" in response.tools[0].result


@pytest.mark.asyncio
async def test_async_external_execution(shared_db):
    """Test a HITL async external execution flow using RunRequirements"""

    @tool(external_execution=True)
    def send_email(to: str, subject: str, body: str):
        pass

    session_id = "test_session_async_external"
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[send_email],
        db=shared_db,
        telemetry=False,
    )

    # Initial async run that requires external execution
    response = await agent.arun(
        "Send an email to john@doe.com with the subject 'Test' and the body 'Hello'", session_id=session_id
    )

    # Verify the run is paused and has active requirements
    assert response.is_paused
    assert len(response.active_requirements) == 1

    # Get the requirement and set result
    requirement = response.active_requirements[0]
    assert requirement.needs_external_execution

    # Use the new DX to set external execution result
    tool_args = requirement.tool_execution and requirement.tool_execution.tool_args
    assert tool_args is not None
    result = f"Email sent to {tool_args['to']}"
    requirement.set_external_execution_result(result)

    # Continue the run with run_id and requirements
    response = await agent.acontinue_run(
        run_id=response.run_id, requirements=response.requirements, session_id=session_id
    )

    # Verify completion
    assert response.is_paused is False
    assert response.tools is not None
    assert response.tools[0].result == result


def test_streaming_external_execution(shared_db):
    """Test a HITL streaming external execution flow using RunRequirements"""

    @tool(external_execution=True)
    def send_email(to: str, subject: str, body: str):
        pass

    session_id = "test_session_streaming_external"
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[send_email],
        db=shared_db,
        telemetry=False,
    )

    # Stream the initial run
    paused_run_output = None
    for run_output in agent.run(
        "Send an email to john@doe.com with the subject 'Test' and the body 'Hello'",
        session_id=session_id,
        stream=True,
    ):
        if run_output.is_paused:  # type: ignore
            paused_run_output = run_output
            break

    # Verify we got a paused run with requirements
    assert paused_run_output is not None
    assert paused_run_output.is_paused

    # Get the requirement using new DX
    requirements = paused_run_output.requirements  # type: ignore
    assert requirements is not None
    assert len(requirements) == 1

    requirement = requirements[0]
    assert requirement.needs_external_execution

    # Set external execution result
    tool_args = requirement.tool_execution and requirement.tool_execution.tool_args
    assert tool_args is not None
    result = f"Email sent to {tool_args['to']}"
    requirement.set_external_execution_result(result)

    # Continue the run with streaming
    final_output = None
    for run_output in agent.continue_run(
        run_id=paused_run_output.run_id,
        updated_tools=paused_run_output.tools,  # type: ignore
        session_id=session_id,
        stream=True,
        yield_run_output=True,
    ):
        final_output = run_output

    # Verify completion
    assert final_output is not None
    assert final_output.is_paused is False  # type: ignore
    assert final_output.tools is not None  # type: ignore
    assert final_output.tools[0].result == result  # type: ignore
