from agno.models.base import MessageData, Model
from agno.models.response import ModelResponse, ModelResponseEvent


class DummyModel(Model):
    def invoke(self, *args, **kwargs) -> ModelResponse:  # pragma: no cover - not needed for tests
        raise NotImplementedError

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:  # pragma: no cover - not needed for tests
        raise NotImplementedError

    def invoke_stream(self, *args, **kwargs):  # pragma: no cover - not needed for tests
        raise NotImplementedError

    async def ainvoke_stream(self, *args, **kwargs):  # pragma: no cover - not needed for tests
        raise NotImplementedError

    def _parse_provider_response(self, response, **kwargs) -> ModelResponse:  # pragma: no cover - not needed for tests
        raise NotImplementedError

    def _parse_provider_response_delta(self, response) -> ModelResponse:  # pragma: no cover - not needed for tests
        raise NotImplementedError


def test_stream_tool_call_args_delta_emitted_when_args_ready():
    model = DummyModel(id="dummy-model")
    stream_data = MessageData()

    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "do_thing", "arguments": '{"value": 1}'},
    }
    response_delta = ModelResponse(tool_calls=[tool_call])

    events = list(model._populate_stream_data(stream_data, response_delta))
    tool_call_events = [ev for ev in events if ev.event == ModelResponseEvent.tool_call_started.value]
    args_delta_events = [ev for ev in events if ev.event == ModelResponseEvent.tool_call_args_delta.value]

    # Streaming tool call deltas should not emit ToolCallStarted; that event is reserved for actual tool execution.
    assert len(tool_call_events) == 0
    assert len(args_delta_events) == 1
    assert args_delta_events[0].tool_call_id == "call_1"
    assert args_delta_events[0].tool_name == "do_thing"
    assert args_delta_events[0].tool_args_delta == '{"value": 1}'


def test_stream_tool_call_args_delta_emitted_with_partial_args():
    model = DummyModel(id="dummy-model")
    stream_data = MessageData()

    tool_call = {
        "id": "call_2",
        "type": "function",
        "function": {"name": "do_thing", "arguments": '{"value":'},
    }
    response_delta = ModelResponse(tool_calls=[tool_call])

    events = list(model._populate_stream_data(stream_data, response_delta))
    tool_call_events = [ev for ev in events if ev.event == ModelResponseEvent.tool_call_started.value]
    args_delta_events = [ev for ev in events if ev.event == ModelResponseEvent.tool_call_args_delta.value]

    assert len(tool_call_events) == 0
    assert len(args_delta_events) == 1
    assert args_delta_events[0].tool_call_id == "call_2"
    assert args_delta_events[0].tool_name == "do_thing"
    assert args_delta_events[0].tool_args_delta == '{"value":'


def test_stream_tool_call_args_delta_resolves_tool_call_id_by_index():
    model = DummyModel(id="dummy-model")
    stream_data = MessageData()

    # First chunk includes id/name and establishes index -> id mapping.
    response_delta_1 = ModelResponse(
        tool_calls=[
            {
                "id": "call_3",
                "index": 0,
                "type": "function",
                "function": {"name": "do_thing", "arguments": "{"},
            }
        ]
    )
    events_1 = list(model._populate_stream_data(stream_data, response_delta_1))
    args_events_1 = [ev for ev in events_1 if ev.event == ModelResponseEvent.tool_call_args_delta.value]
    assert len(args_events_1) == 1
    assert args_events_1[0].tool_call_id == "call_3"
    assert args_events_1[0].tool_name == "do_thing"
    assert args_events_1[0].tool_args_delta == "{"

    # Second chunk omits id/name but includes the same index; id/name should be resolved from prior chunk.
    response_delta_2 = ModelResponse(
        tool_calls=[
            {
                "index": 0,
                "type": "function",
                "function": {"arguments": '"value": 1}'},
            }
        ]
    )
    events_2 = list(model._populate_stream_data(stream_data, response_delta_2))
    args_events_2 = [ev for ev in events_2 if ev.event == ModelResponseEvent.tool_call_args_delta.value]
    assert len(args_events_2) == 1
    assert args_events_2[0].tool_call_id == "call_3"
    assert args_events_2[0].tool_name == "do_thing"
    assert args_events_2[0].tool_args_delta == '"value": 1}'
