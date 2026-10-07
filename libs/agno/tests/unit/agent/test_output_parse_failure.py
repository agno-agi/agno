"""Offline public-run coverage for opt-in structured-output failure reporting."""

import json
from typing import Any, AsyncIterator, Iterator

import pytest
from pydantic import BaseModel

from agno.agent import Agent
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent, ToolExecution
from agno.run.agent import RunCompletedEvent, RunContentCompletedEvent, RunErrorEvent, RunOutput
from agno.run.base import RunStatus
from agno.run.requirement import RunRequirement


class Output(BaseModel):
    answer: int


class StaticModel(Model):
    """Supply provider-independent responses, including empty and non-string content."""

    def __init__(self, content: Any) -> None:
        super().__init__(id="static", name="static", provider="test")
        self.content = content

    def response(self, messages: list[Message], **kwargs: Any) -> ModelResponse:
        messages.append(Message(role="assistant", content=self._message_content()))
        return ModelResponse(content=self.content)

    async def aresponse(self, messages: list[Message], **kwargs: Any) -> ModelResponse:
        return self.response(messages, **kwargs)

    def response_stream(self, messages: list[Message], **kwargs: Any) -> Iterator[ModelResponse]:
        messages.append(Message(role="assistant", content=self._message_content()))
        yield ModelResponse(content=self.content)

    async def aresponse_stream(self, messages: list[Message], **kwargs: Any) -> AsyncIterator[ModelResponse]:
        for response in self.response_stream(messages, **kwargs):
            yield response

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return ModelResponse(content=self.content)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self.invoke(*args, **kwargs)

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response

    def _message_content(self) -> Any:
        if isinstance(self.content, BaseModel):
            return self.content.model_dump_json()
        return json.dumps(self.content) if isinstance(self.content, dict) else self.content


class PausingModel(StaticModel):
    """Pause once for external execution, then return the configured final content."""

    def __init__(self, content: Any, requires_confirmation: bool = False) -> None:
        super().__init__(content)
        self.pause_emitted = False
        self.requires_confirmation = requires_confirmation

    def response(self, messages: list[Message], **kwargs: Any) -> ModelResponse:
        if self.pause_emitted:
            return super().response(messages, **kwargs)
        self.pause_emitted = True
        tool = ToolExecution(
            tool_call_id="external-call",
            tool_name="external_action",
            tool_args={},
            external_execution_required=not self.requires_confirmation,
            requires_confirmation=self.requires_confirmation,
        )
        kwargs["run_response"].requirements = [RunRequirement(tool_execution=tool)]
        messages.append(
            Message(
                role="assistant",
                tool_calls=[
                    {
                        "id": tool.tool_call_id,
                        "type": "function",
                        "function": {"name": tool.tool_name, "arguments": "{}"},
                    }
                ],
            )
        )
        return ModelResponse(tool_executions=[tool])

    def response_stream(self, messages: list[Message], **kwargs: Any) -> Iterator[ModelResponse]:
        response = self.response(messages, **kwargs)
        if response.tool_executions:
            response.event = ModelResponseEvent.tool_call_paused.value
            # The stream handler builds the requirement from the pause event.
            kwargs["run_response"].requirements = []
            yield response
            yield ModelResponse(content="Waiting for approval")
        else:
            yield response


class NoContentModel(StaticModel):
    def response_stream(self, messages: list[Message], **kwargs: Any) -> Iterator[ModelResponse]:
        yield from ()


class MissingFinalResponseModel(StaticModel):
    def response_stream(self, messages: list[Message], **kwargs: Any) -> Iterator[ModelResponse]:
        messages.append(Message(role="assistant", content=None))
        yield ModelResponse(content='{"answer": 42}')
        yield ModelResponse(content=None)


INVALID_OUTPUTS = [
    pytest.param("not JSON", id="prose"),
    pytest.param("", id="empty"),
    pytest.param('{"answer":', id="truncated"),
    pytest.param('{"answer": nope}', id="malformed"),
    pytest.param('{"answer": "invalid"}', id="schema-validation"),
]


def _agent(content: Any, **kwargs: Any) -> Agent:
    return Agent(
        model=StaticModel(content),
        output_schema=Output,
        telemetry=False,
        store_events=True,
        cache_session=True,
        **kwargs,
    )


def _assert_error(response: RunOutput, content: Any, events: list[Any]) -> None:
    assert response.status == RunStatus.error
    if isinstance(content, str):
        assert response.content_type == "str"
    assert response.content == content
    errors = [event for event in events if isinstance(event, RunErrorEvent)]
    assert len(errors) == 1
    assert errors[0].error_type == "output_parse_error"
    assert errors[0].content is not None
    assert "Output" in errors[0].content
    assert not any(isinstance(event, (RunCompletedEvent, RunContentCompletedEvent)) for event in events)


@pytest.mark.parametrize("content", INVALID_OUTPUTS)
@pytest.mark.parametrize("stream", [False, True])
def test_failed_output_is_explicit_sync(content: str, stream: bool) -> None:
    agent = _agent(content, fail_on_output_parse_error=True)
    if stream:
        events = list(agent.run("test", stream=True, stream_events=True))
        response = agent.get_last_run_output()
        assert response is not None
    else:
        response = agent.run("test")
        events = response.events or []
    _assert_error(response, content, events)


@pytest.mark.parametrize("content", INVALID_OUTPUTS)
@pytest.mark.parametrize("stream", [False, True])
async def test_failed_output_is_explicit_async(content: str, stream: bool) -> None:
    agent = _agent(content, fail_on_output_parse_error=True)
    if stream:
        events = [event async for event in agent.arun("test", stream=True, stream_events=True)]
        response = agent.get_last_run_output()
        assert response is not None
    else:
        response = await agent.arun("test")
        events = response.events or []
    _assert_error(response, content, events)


@pytest.mark.parametrize("content", ['{"answer": 42}', Output(answer=42)])
@pytest.mark.parametrize("stream", [False, True])
def test_valid_output_still_completes_sync(content: Any, stream: bool) -> None:
    agent = _agent(content, fail_on_output_parse_error=True)
    if stream:
        events = list(agent.run("test", stream=True, stream_events=True))
        assert any(isinstance(event, RunCompletedEvent) for event in events)
        response = agent.get_last_run_output()
    else:
        response = agent.run("test")
    assert response is not None
    assert response.status == RunStatus.completed
    assert response.content == Output(answer=42)


@pytest.mark.parametrize("content", ['{"answer": 42}', Output(answer=42)])
@pytest.mark.parametrize("stream", [False, True])
async def test_valid_output_still_completes_async(content: Any, stream: bool) -> None:
    agent = _agent(content, fail_on_output_parse_error=True)
    if stream:
        events = [event async for event in agent.arun("test", stream=True, stream_events=True)]
        assert any(isinstance(event, RunCompletedEvent) for event in events)
        response = agent.get_last_run_output()
    else:
        response = await agent.arun("test")
    assert response is not None
    assert response.status == RunStatus.completed
    assert response.content == Output(answer=42)


@pytest.mark.parametrize("stream", [False, True])
def test_default_remains_permissive_sync(stream: bool) -> None:
    agent = _agent("not JSON")
    assert agent.fail_on_output_parse_error is False
    if stream:
        list(agent.run("test", stream=True, stream_events=True))
        response = agent.get_last_run_output()
    else:
        response = agent.run("test")
    assert response is not None
    assert response.status == RunStatus.completed
    assert response.content == "not JSON"


@pytest.mark.parametrize("stream", [False, True])
async def test_default_remains_permissive_async(stream: bool) -> None:
    agent = _agent("not JSON")
    if stream:
        _ = [event async for event in agent.arun("test", stream=True, stream_events=True)]
        response = agent.get_last_run_output()
    else:
        response = await agent.arun("test")
    assert response is not None
    assert response.status == RunStatus.completed
    assert response.content == "not JSON"


@pytest.mark.parametrize("stream", [False, True])
def test_explicitly_unparsed_output_does_not_fail(stream: bool) -> None:
    agent = _agent("not JSON", parse_response=False, fail_on_output_parse_error=True)
    if stream:
        list(agent.run("test", stream=True, stream_events=True))
        response = agent.get_last_run_output()
    else:
        response = agent.run("test")
    assert response is not None
    assert response.status == RunStatus.completed
    assert response.content == "not JSON"


@pytest.mark.parametrize("stream", [False, True])
async def test_explicitly_unparsed_output_does_not_fail_async(stream: bool) -> None:
    agent = _agent("not JSON", parse_response=False, fail_on_output_parse_error=True)
    if stream:
        _ = [event async for event in agent.arun("test", stream=True, stream_events=True)]
        response = agent.get_last_run_output()
    else:
        response = await agent.arun("test")
    assert response is not None
    assert response.status == RunStatus.completed
    assert response.content == "not JSON"


@pytest.mark.parametrize("stream", [False, True])
def test_no_output_schema_does_not_fail_sync(stream: bool) -> None:
    agent = Agent(model=StaticModel("not JSON"), fail_on_output_parse_error=True, telemetry=False, cache_session=True)
    if stream:
        list(agent.run("test", stream=True, stream_events=True))
        response = agent.get_last_run_output()
    else:
        response = agent.run("test")
    assert response is not None
    assert response.status == RunStatus.completed
    assert response.content == "not JSON"


@pytest.mark.parametrize("stream", [False, True])
async def test_no_output_schema_does_not_fail_async(stream: bool) -> None:
    agent = Agent(model=StaticModel("not JSON"), fail_on_output_parse_error=True, telemetry=False, cache_session=True)
    if stream:
        _ = [event async for event in agent.arun("test", stream=True, stream_events=True)]
        response = agent.get_last_run_output()
    else:
        response = await agent.arun("test")
    assert response is not None
    assert response.status == RunStatus.completed
    assert response.content == "not JSON"


@pytest.mark.parametrize("content", [None, {"answer": 42}])
def test_non_string_unparsed_output_fails(content: Any) -> None:
    response = _agent(content, fail_on_output_parse_error=True).run("test")
    _assert_error(response, content, response.events or [])


@pytest.mark.parametrize("content", [None, {"answer": 42}])
async def test_non_string_unparsed_output_fails_async(content: Any) -> None:
    response = await _agent(content, fail_on_output_parse_error=True).arun("test")
    _assert_error(response, content, response.events or [])


def test_per_run_output_schema_is_used() -> None:
    agent = Agent(model=StaticModel("not JSON"), fail_on_output_parse_error=True, telemetry=False, store_events=True)
    response = agent.run("test", output_schema=Output)
    _assert_error(response, "not JSON", response.events or [])


@pytest.mark.parametrize("stream", [False, True])
def test_failed_parser_model_output_fails(stream: bool) -> None:
    agent = _agent("raw answer", parser_model=StaticModel("not JSON"), fail_on_output_parse_error=True)
    if stream:
        events = list(agent.run("test", stream=True, stream_events=True))
        response = agent.get_last_run_output()
        assert response is not None
    else:
        response = agent.run("test")
        events = response.events or []
    _assert_error(response, "not JSON", events)


@pytest.mark.parametrize("stream", [False, True])
async def test_failed_parser_model_output_fails_async(stream: bool) -> None:
    agent = _agent("raw answer", parser_model=StaticModel("not JSON"), fail_on_output_parse_error=True)
    if stream:
        events = [event async for event in agent.arun("test", stream=True, stream_events=True)]
        response = agent.get_last_run_output()
        assert response is not None
    else:
        response = await agent.arun("test")
        events = response.events or []
    _assert_error(response, "not JSON", events)


def test_validation_error_identifies_the_invalid_field() -> None:
    response = _agent('{"answer": "invalid"}', fail_on_output_parse_error=True).run("test")
    error = next(event for event in response.events or [] if isinstance(event, RunErrorEvent))
    assert error.content is not None
    assert "answer" in error.content
    assert "integer" in error.content


@pytest.mark.parametrize("content", ["not JSON", None])
def test_failure_signal_is_retained_without_event_storage(content: Any) -> None:
    agent = Agent(model=StaticModel(content), output_schema=Output, fail_on_output_parse_error=True, telemetry=False)
    assert agent.store_events is False
    response = agent.run("test")
    _assert_error(response, content, response.events or [])


@pytest.mark.parametrize("content", ["not JSON", None])
async def test_failure_signal_is_retained_without_event_storage_async(content: Any) -> None:
    agent = Agent(model=StaticModel(content), output_schema=Output, fail_on_output_parse_error=True, telemetry=False)
    response = await agent.arun("test")
    _assert_error(response, content, response.events or [])


@pytest.mark.parametrize("content", ["not JSON", None])
@pytest.mark.parametrize("stream", [False, True])
def test_continuation_reports_final_output_failure_sync(content: Any, stream: bool) -> None:
    agent = Agent(
        model=PausingModel(content),
        output_schema=Output,
        fail_on_output_parse_error=True,
        telemetry=False,
        cache_session=True,
    )
    if stream:
        pause_events = list(agent.run("test", stream=True, stream_events=True))
        assert not any(isinstance(event, RunErrorEvent) for event in pause_events)
        paused = agent.get_last_run_output()
    else:
        paused = agent.run("test")
    assert paused is not None
    assert paused.status == RunStatus.paused
    assert len(paused.active_requirements) == 1
    requirement = paused.active_requirements[0]
    requirement.set_external_execution_result("done")
    if stream:
        events = list(agent.continue_run(paused, requirements=[requirement], stream=True, stream_events=True))
        response = agent.get_last_run_output()
        assert response is not None
    else:
        response = agent.continue_run(paused, requirements=[requirement])
        events = response.events or []
    _assert_error(response, content, events)


@pytest.mark.parametrize("content", ["not JSON", None])
@pytest.mark.parametrize("stream", [False, True])
async def test_continuation_reports_final_output_failure_async(content: Any, stream: bool) -> None:
    agent = Agent(
        model=PausingModel(content),
        output_schema=Output,
        fail_on_output_parse_error=True,
        telemetry=False,
        cache_session=True,
    )
    if stream:
        pause_events = [event async for event in agent.arun("test", stream=True, stream_events=True)]
        assert not any(isinstance(event, RunErrorEvent) for event in pause_events)
        paused = agent.get_last_run_output()
    else:
        paused = await agent.arun("test")
    assert paused is not None
    assert paused.status == RunStatus.paused
    assert len(paused.active_requirements) == 1
    requirement = paused.active_requirements[0]
    requirement.set_external_execution_result("done")
    if stream:
        events = [
            event
            async for event in agent.acontinue_run(paused, requirements=[requirement], stream=True, stream_events=True)
        ]
        response = agent.get_last_run_output()
        assert response is not None
    else:
        response = await agent.acontinue_run(paused, requirements=[requirement])
        events = response.events or []
    _assert_error(response, content, events)


@pytest.mark.parametrize("stream", [False, True])
def test_pending_confirmation_remains_paused_sync(stream: bool) -> None:
    agent = Agent(
        model=PausingModel(None, requires_confirmation=True),
        output_schema=Output,
        fail_on_output_parse_error=True,
        telemetry=False,
        cache_session=True,
    )
    if stream:
        events = list(agent.run("test", stream=True, stream_events=True))
        response = agent.get_last_run_output()
        assert not any(isinstance(event, RunErrorEvent) for event in events)
    else:
        response = agent.run("test")
    assert response is not None
    assert response.status == RunStatus.paused
    assert response.active_requirements[0].needs_confirmation


@pytest.mark.parametrize("stream", [False, True])
async def test_pending_confirmation_remains_paused_async(stream: bool) -> None:
    agent = Agent(
        model=PausingModel(None, requires_confirmation=True),
        output_schema=Output,
        fail_on_output_parse_error=True,
        telemetry=False,
        cache_session=True,
    )
    if stream:
        events = [event async for event in agent.arun("test", stream=True, stream_events=True)]
        response = agent.get_last_run_output()
        assert not any(isinstance(event, RunErrorEvent) for event in events)
    else:
        response = await agent.arun("test")
    assert response is not None
    assert response.status == RunStatus.paused
    assert response.active_requirements[0].needs_confirmation


@pytest.mark.parametrize("secondary", ["parser_model", "output_model"])
@pytest.mark.parametrize("stream", [False, True])
def test_empty_secondary_output_does_not_reuse_valid_primary_sync(secondary: str, stream: bool) -> None:
    agent = _agent('{"answer": 42}', fail_on_output_parse_error=True, **{secondary: StaticModel(None)})
    if stream:
        events = list(agent.run("test", stream=True, stream_events=True))
        response = agent.get_last_run_output()
        assert response is not None
    else:
        response = agent.run("test")
        events = response.events or []
    assert response.content in (None, "")
    _assert_error(response, response.content, events)


@pytest.mark.parametrize("secondary", ["parser_model", "output_model"])
@pytest.mark.parametrize("stream", [False, True])
async def test_empty_secondary_output_does_not_reuse_valid_primary_async(secondary: str, stream: bool) -> None:
    agent = _agent('{"answer": 42}', fail_on_output_parse_error=True, **{secondary: StaticModel(None)})
    if stream:
        events = [event async for event in agent.arun("test", stream=True, stream_events=True)]
        response = agent.get_last_run_output()
        assert response is not None
    else:
        response = await agent.arun("test")
        events = response.events or []
    assert response.content in (None, "")
    _assert_error(response, response.content, events)


@pytest.mark.parametrize("secondary", ["parser_model", "output_model"])
def test_secondary_stream_without_content_does_not_reuse_valid_primary_sync(secondary: str) -> None:
    agent = _agent('{"answer": 42}', fail_on_output_parse_error=True, **{secondary: NoContentModel(None)})
    events = list(agent.run("test", stream=True, stream_events=True))
    response = agent.get_last_run_output()
    assert response is not None
    assert response.content in (None, "")
    _assert_error(response, response.content, events)


@pytest.mark.parametrize("secondary", ["parser_model", "output_model"])
async def test_secondary_stream_without_content_does_not_reuse_valid_primary_async(secondary: str) -> None:
    agent = _agent('{"answer": 42}', fail_on_output_parse_error=True, **{secondary: NoContentModel(None)})
    events = [event async for event in agent.arun("test", stream=True, stream_events=True)]
    response = agent.get_last_run_output()
    assert response is not None
    assert response.content in (None, "")
    _assert_error(response, response.content, events)


def test_dict_schema_with_parsing_disabled_keeps_streamed_json_sync() -> None:
    raw_content = '{"answer": 42}'
    agent = Agent(
        model=StaticModel(raw_content),
        output_schema={"type": "object", "properties": {"answer": {"type": "integer"}}},
        parse_response=False,
        fail_on_output_parse_error=True,
        telemetry=False,
        cache_session=True,
    )
    events = list(agent.run("test", stream=True, stream_events=True))
    response = agent.get_last_run_output()
    assert response is not None
    assert response.status == RunStatus.completed
    assert response.content == raw_content
    assert not any(isinstance(event, RunErrorEvent) for event in events)


async def test_dict_schema_with_parsing_disabled_keeps_streamed_json_async() -> None:
    raw_content = '{"answer": 42}'
    agent = Agent(
        model=StaticModel(raw_content),
        output_schema={"type": "object", "properties": {"answer": {"type": "integer"}}},
        parse_response=False,
        fail_on_output_parse_error=True,
        telemetry=False,
        cache_session=True,
    )
    events = [event async for event in agent.arun("test", stream=True, stream_events=True)]
    response = agent.get_last_run_output()
    assert response is not None
    assert response.status == RunStatus.completed
    assert response.content == raw_content
    assert not any(isinstance(event, RunErrorEvent) for event in events)


def test_empty_final_stream_response_does_not_reuse_prior_structured_output_sync() -> None:
    agent = Agent(
        model=MissingFinalResponseModel(None),
        output_schema=Output,
        fail_on_output_parse_error=True,
        telemetry=False,
        cache_session=True,
    )
    events = list(agent.run("test", stream=True, stream_events=True))
    response = agent.get_last_run_output()
    assert response is not None
    _assert_error(response, None, events)


async def test_empty_final_stream_response_does_not_reuse_prior_structured_output_async() -> None:
    agent = Agent(
        model=MissingFinalResponseModel(None),
        output_schema=Output,
        fail_on_output_parse_error=True,
        telemetry=False,
        cache_session=True,
    )
    events = [event async for event in agent.arun("test", stream=True, stream_events=True)]
    response = agent.get_last_run_output()
    assert response is not None
    _assert_error(response, None, events)


@pytest.mark.parametrize("enabled", [False, True])
def test_failure_policy_survives_config_round_trip(enabled: bool) -> None:
    agent = Agent(fail_on_output_parse_error=enabled)
    restored = Agent.from_dict(agent.to_dict())
    assert restored.fail_on_output_parse_error is enabled
