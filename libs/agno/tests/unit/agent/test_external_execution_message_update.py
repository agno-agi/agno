from typing import Any, AsyncIterator, Iterator

from agno.agent import Agent
from agno.agent._tools import handle_external_execution_update
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.message import Message, MessageMetrics
from agno.models.response import ModelResponse, ToolExecution
from agno.run.messages import RunMessages
from agno.tools.decorator import tool


class SequenceModel(Model):
    def __init__(self, responses: list[ModelResponse]):
        super().__init__(id="sequence", name="sequence", provider="test")
        self.responses = responses
        self.requests: list[list[Message]] = []

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def invoke(self, messages: list[Message], *args, **kwargs) -> ModelResponse:
        self.requests.append(list(messages))
        return self.responses.pop(0)

    async def ainvoke(self, messages: list[Message], *args, **kwargs) -> ModelResponse:
        return self.invoke(messages, *args, **kwargs)

    def invoke_stream(self, messages: list[Message], *args, **kwargs) -> Iterator[ModelResponse]:
        yield self.invoke(messages, *args, **kwargs)

    async def ainvoke_stream(self, messages: list[Message], *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self.invoke(messages, *args, **kwargs)

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _response(content=None, tool_calls=None):
    return ModelResponse(
        content=content,
        role="assistant",
        tool_calls=tool_calls or [],
        response_usage=MessageMetrics(),
    )


def _tool_call(call_id: str, name: str):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": "{}"},
    }


def test_native_continue_scopes_tool_result_to_latest_matching_call():
    @tool
    def backend_tool() -> str:
        return "historical result"

    @tool(external_execution=True)
    def client_tool() -> str:
        raise AssertionError("external tool must not execute in the agent")

    model = SequenceModel(
        [
            _response(tool_calls=[_tool_call("reused-id", "backend_tool")]),
            _response(content="first run complete"),
            _response(tool_calls=[_tool_call("reused-id", "client_tool")]),
            _response(content="second run complete"),
        ]
    )
    agent = Agent(
        id="external-message-repro",
        model=model,
        tools=[backend_tool, client_tool],
        db=InMemoryDb(),
        add_history_to_context=True,
        num_history_runs=5,
        telemetry=False,
    )
    session_id = "external-message-repro-session"

    first = agent.run("run the backend tool", session_id=session_id)
    assert first.content == "first run complete"

    paused = agent.run("run the client tool", session_id=session_id)
    assert paused.is_paused
    paused.active_requirements[0].set_external_execution_result("current result")

    completed = agent.continue_run(
        run_id=paused.run_id,
        session_id=session_id,
        requirements=paused.requirements,
    )
    assert not completed.is_paused

    continuation_request = model.requests[-1]
    current_assistant_index = max(
        i
        for i, message in enumerate(continuation_request)
        if any(call.get("id") == "reused-id" for call in (message.tool_calls or []))
    )
    current_results = [
        message
        for message in continuation_request[current_assistant_index + 1 :]
        if message.role == "tool" and message.tool_call_id == "reused-id"
    ]
    assert [message.content for message in current_results] == ["current result"]


def test_existing_result_for_current_call_is_updated_without_duplication():
    model = SequenceModel([])
    agent = Agent(model=model, telemetry=False)
    run_messages = RunMessages(
        messages=[
            Message(
                role="assistant",
                tool_calls=[_tool_call("call-1", "client_tool")],
            ),
            Message(
                role="tool",
                content="stale result",
                tool_call_id="call-1",
                tool_name="client_tool",
                tool_args={"value": "old"},
                tool_call_error=True,
            ),
        ]
    )
    updated_tool = ToolExecution(
        tool_call_id="call-1",
        tool_name="client_tool",
        tool_args={"value": "new"},
        result="fresh result",
        tool_call_error=False,
        external_execution_required=True,
        stop_after_tool_call=True,
    )

    handle_external_execution_update(agent, run_messages, updated_tool)

    result_messages = [message for message in run_messages.messages if message.role == "tool"]
    assert len(result_messages) == 1
    assert result_messages[0].content == "fresh result"
    assert result_messages[0].tool_args == {"value": "new"}
    assert result_messages[0].tool_call_error is False
    assert result_messages[0].stop_after_tool_call is True
    assert updated_tool.external_execution_required is False
