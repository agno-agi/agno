from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.models.response import ModelResponse, ModelResponseEvent, ToolExecution
from agno.run.agent import RunEvent, RunOutput, ToolCallErrorEvent
from agno.run.messages import RunMessages
from agno.run.team import TeamRunEvent, TeamRunOutput
from agno.run.team import ToolCallErrorEvent as TeamToolCallErrorEvent
from agno.session import TeamSession
from agno.team import Team


def test_agent_yields_tool_call_error_event(mocker):
    # Mock the model to return a tool call and then a tool result with error
    mock_model = mocker.Mock(spec=OpenAIChat)

    # Create an agent with the mock model
    agent = Agent(model=mock_model)

    # Mock model.get_function_call_to_run_from_tool_execution
    mock_function_call = mocker.Mock()
    mock_function_call.get_call_str.return_value = "test_tool()"
    mock_function_call.call_id = "call_1"
    mock_function_call.function.name = "test_tool"
    mock_function_call.arguments = {}
    mock_model.get_function_call_to_run_from_tool_execution.return_value = mock_function_call

    # Mock model.run_function_call to yield ToolCallStarted and then ToolCallCompleted with error
    tool_execution = ToolExecution(
        tool_call_id="call_1", tool_name="test_tool", tool_args={}, tool_call_error=True, result="Tool failed"
    )

    mock_model.run_function_call.return_value = [
        ModelResponse(event=ModelResponseEvent.tool_call_started.value),
        ModelResponse(event=ModelResponseEvent.tool_call_completed.value, tool_executions=[tool_execution]),
    ]

    # Run _run_tool and collect events
    run_response = RunOutput(run_id="run_1", agent_id="agent_1", agent_name="Agent")
    run_messages = RunMessages()

    events = list(
        agent._run_tool(run_response=run_response, run_messages=run_messages, tool=tool_execution, stream_events=True)
    )

    # Verify events
    event_types = [e.event for e in events]
    assert RunEvent.tool_call_started.value in event_types
    assert RunEvent.tool_call_completed.value in event_types
    assert RunEvent.tool_call_error.value in event_types

    # Verify the ToolCallErrorEvent details
    error_event = next(e for e in events if e.event == RunEvent.tool_call_error.value)
    assert isinstance(error_event, ToolCallErrorEvent)
    assert error_event.tool.tool_call_id == "call_1"  # type: ignore
    assert error_event.error == "Tool failed"


def test_team_yields_tool_call_error_event(mocker):
    # Mock model
    mock_model = mocker.Mock(spec=OpenAIChat)

    # Create a team
    agent1 = Agent(name="Agent1", model=mock_model)
    team = Team(members=[agent1], model=mock_model)

    # Setup session and run_response
    session = TeamSession(session_id="session_1")
    run_response = TeamRunOutput(run_id="run_1", team_id="team_1", team_name="Team")

    # Tool execution with error
    tool_execution = ToolExecution(
        tool_call_id="call_1", tool_name="test_tool", tool_args={}, tool_call_error=True, result="Tool failed"
    )

    # ModelResponse event for tool completion
    model_response_event = ModelResponse(
        event=ModelResponseEvent.tool_call_completed.value, tool_executions=[tool_execution], content="Tool result"
    )

    full_model_response = ModelResponse()

    # Run _handle_model_response_chunk
    events = list(
        team._handle_model_response_chunk(
            session=session,
            run_response=run_response,
            full_model_response=full_model_response,
            model_response_event=model_response_event,
            stream_events=True,
        )
    )

    # Verify events
    event_types = [e.event for e in events]
    assert TeamRunEvent.tool_call_completed.value in event_types
    assert TeamRunEvent.tool_call_error.value in event_types

    # Verify the ToolCallErrorEvent details
    error_event = next(e for e in events if e.event == TeamRunEvent.tool_call_error.value)
    assert isinstance(error_event, TeamToolCallErrorEvent)
    assert error_event.tool.tool_call_id == "call_1"  # type: ignore
    assert error_event.error == "Tool failed"
