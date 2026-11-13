"""Unit tests for the RampRouter model class.

Router is an OpenAI Responses API gateway, so the class is a thin OpenResponses subclass. These
tests pin the defaults, the Router-only request fields, and the behaviors the class deliberately
does not inherit, without any network access. (The to_dict/from_dict round-trip is covered
generically by ``test_provider_resolution.py`` via the provider registry.)
"""

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.message import Message
from agno.models.openai.open_responses import OpenResponses
from agno.models.ramp import RampRouter
from agno.tools.function import Function


def test_defaults():
    """Defaults match the Router Responses endpoint."""
    model = RampRouter(api_key="test-key")
    assert isinstance(model, OpenResponses)
    assert model.id == "gpt-5.6-luna"
    assert model.name == "RampRouter"
    assert model.provider == "RampRouter"
    assert model.base_url == "https://api.router.com/v1"
    assert model.store is None
    assert model.supports_native_structured_outputs is True


def test_api_key_from_env(monkeypatch):
    """The API key is read from RAMP_ROUTER_API_KEY when not passed explicitly."""
    monkeypatch.setenv("RAMP_ROUTER_API_KEY", "env-key")
    assert RampRouter()._get_client_params()["api_key"] == "env-key"


def test_missing_api_key_raises(monkeypatch):
    """A missing API key raises ModelAuthenticationError rather than a client error."""
    monkeypatch.delenv("RAMP_ROUTER_API_KEY", raising=False)
    with pytest.raises(ModelAuthenticationError, match="RAMP_ROUTER_API_KEY not set"):
        RampRouter(api_key=None)._get_client_params()


def test_client_params_include_base_url():
    """Client params carry the configured key and base URL through to the SDK."""
    params = RampRouter(api_key="test-key")._get_client_params()
    assert params["api_key"] == "test-key"
    assert params["base_url"] == "https://api.router.com/v1"


def test_get_provider():
    """The display provider carries the Responses suffix the base class appends."""
    assert RampRouter(api_key="test-key").get_provider() == "RampRouter Responses"


def test_not_using_reasoning_model():
    """Reasoning-model detection stays off, whatever the id looks like.

    OpenAIResponses classifies any `gpt-5*` id as a reasoning model and starts chaining turns with
    previous_response_id, which silently loses history on Router's non-OpenAI backings.
    """
    assert RampRouter(api_key="test-key", id="gpt-5.6-luna")._using_reasoning_model() is False


def test_reasoning_omitted_when_unset():
    """No reasoning block is sent unless the caller asked for one."""
    params = RampRouter(api_key="test-key").get_request_params()
    assert "reasoning" not in params


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"reasoning_effort": "low"}, {"effort": "low"}),
        ({"reasoning_summary": "auto"}, {"summary": "auto"}),
        ({"reasoning": {"effort": "xhigh"}}, {"effort": "xhigh"}),
    ],
)
def test_reasoning_forwarded(kwargs, expected):
    """Reasoning settings reach the request, including efforts outside OpenAI's vocabulary."""
    params = RampRouter(api_key="test-key", **kwargs).get_request_params()
    assert params["reasoning"] == expected


def test_reasoning_dict_not_mutated():
    """Building a request leaves the caller's reasoning dict alone."""
    reasoning = {"effort": "high"}
    model = RampRouter(api_key="test-key", reasoning=reasoning, reasoning_summary="auto")
    model.get_request_params()
    assert reasoning == {"effort": "high"}


def test_router_fields_land_in_extra_body():
    """The Router-only fields are sent in the request body, not as SDK kwargs."""
    model = RampRouter(
        api_key="test-key",
        models=["openai:gpt-5-nano", "anthropic:claude-haiku-4-5"],
        allow_flex_tier=True,
        provider_timeout=30,
        timeout_before_headers=10,
    )
    extra_body = model.get_request_params()["extra_body"]
    assert extra_body["models"] == ["openai:gpt-5-nano", "anthropic:claude-haiku-4-5"]
    assert extra_body["allow_flex_tier"] is True
    assert extra_body["provider_timeout"] == 30
    assert extra_body["timeout_before_headers"] == 10


def test_router_fields_omitted_when_unset():
    """An unconfigured model sends no extra_body at all: Router rejects fields it does not know."""
    assert "extra_body" not in RampRouter(api_key="test-key").get_request_params()


def test_extra_body_not_mutated():
    """A caller-supplied extra_body is merged into, never mutated.

    The base class puts self.extra_body into the request params by reference, so merging in place
    would accumulate the Router fields across every call.
    """
    model = RampRouter(api_key="test-key", extra_body={"custom": 1}, provider_timeout=30)
    first = model.get_request_params()["extra_body"]
    model.get_request_params()
    assert model.extra_body == {"custom": 1}
    assert first == {"custom": 1, "provider_timeout": 30}


def test_model_request_kwargs_select_one_model():
    """Without a candidate list, the configured id is the selector."""
    assert RampRouter(api_key="test-key", id="gpt-5.5")._get_model_request_kwargs() == {"model": "gpt-5.5"}


def test_model_request_kwargs_omit_model_when_routing():
    """With a candidate list, `model` is dropped: Router rejects both selectors together."""
    model = RampRouter(api_key="test-key", models=["openai:gpt-5-nano"])
    assert model._get_model_request_kwargs() == {}


def test_empty_models_list_routes_on_the_id():
    """An empty candidate list means the same thing to both selectors: route on `id`.

    Router rejects a request carrying `model` and `models` together, so the two must not disagree
    about whether `models=[]` counts as a candidate list.
    """
    model = RampRouter(api_key="test-key", models=[])

    assert model._get_model_request_kwargs() == {"model": "gpt-5.6-luna"}
    assert "extra_body" not in model.get_request_params()


def test_background_mode_is_rejected():
    """Router queues a background generation and then serves no endpoint to collect it."""
    with pytest.raises(ValueError, match="does not support background mode"):
        RampRouter(api_key="test-key", background=True)


def test_internal_tool_keys_stripped():
    """Agno bookkeeping is stripped from the tool object before it reaches a provider."""

    def get_weather(city: str) -> str:
        """Get the weather.

        Args:
            city: the city to look up
        """
        return "sunny"

    function = Function.from_callable(get_weather)
    function.requires_confirmation = True
    function.external_execution = True

    tools = RampRouter(api_key="test-key")._format_tool_params(messages=[], tools=[function])

    assert tools[0]["name"] == "get_weather"
    assert "requires_confirmation" not in tools[0]
    assert "external_execution" not in tools[0]


def test_replayed_function_call_drops_its_id():
    """A replayed function call keeps call_id but loses the id that binds it to a reasoning item.

    Reasoning models emit a reasoning item ahead of the call they decided on and pair the two by
    item id, then reject the call being replayed without it.
    """
    messages = [
        Message(role="user", content="What is the weather in Paris?"),
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "fc_123",
                    "call_id": "call_abc",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
                }
            ],
        ),
        Message(role="tool", tool_call_id="fc_123", content="21 degrees and sunny"),
    ]

    formatted = RampRouter(api_key="test-key")._format_messages(messages)

    calls = [m for m in formatted if isinstance(m, dict) and m.get("type") == "function_call"]
    assert len(calls) == 1
    assert "id" not in calls[0]
    assert calls[0]["call_id"] == "call_abc"
    assert calls[0]["name"] == "get_weather"

    outputs = [m for m in formatted if isinstance(m, dict) and m.get("type") == "function_call_output"]
    assert len(outputs) == 1
    assert outputs[0]["call_id"] == "call_abc"


def _usage(**overrides):
    """A ResponseUsage built the way the SDK builds one, so missing fields stay missing."""
    from openai.types.responses import ResponseUsage

    payload = {
        "input_tokens": 11,
        "output_tokens": 5,
        "total_tokens": 16,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 0},
    }
    payload.update(overrides)
    return ResponseUsage.construct(**payload)


def test_truncated_stream_reports_usage():
    """A generation cut short by max_output_tokens ends on response.incomplete, which carries usage.

    The base class reads usage only from response.completed, so without this the metrics of every
    truncated generation are lost.
    """
    from types import SimpleNamespace

    event = SimpleNamespace(type="response.incomplete", response=SimpleNamespace(usage=_usage()))
    model_response, tool_use = RampRouter(api_key="test-key")._parse_provider_response_delta(
        event, Message(role="assistant"), {}
    )

    assert tool_use == {}
    assert model_response.response_usage is not None
    assert model_response.response_usage.input_tokens == 11
    assert model_response.response_usage.total_tokens == 16


def test_truncated_stream_without_usage():
    """response.incomplete does not always carry usage; that must not raise."""
    from types import SimpleNamespace

    event = SimpleNamespace(type="response.incomplete", response=SimpleNamespace(usage=None))
    model_response, _ = RampRouter(api_key="test-key")._parse_provider_response_delta(
        event, Message(role="assistant"), {}
    )

    assert model_response.response_usage is None


def test_metrics_read_a_full_usage_envelope():
    """Every field the OpenAI backing reports is carried through, not zeroed."""
    metrics = RampRouter(api_key="test-key")._get_metrics(
        _usage(
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            input_tokens_details={"cached_tokens": 30, "cache_write_tokens": 20},
            output_tokens_details={"reasoning_tokens": 40},
        )
    )

    assert metrics.input_tokens == 100
    assert metrics.output_tokens == 50
    assert metrics.total_tokens == 150
    assert metrics.cache_read_tokens == 30
    assert metrics.cache_write_tokens == 20
    assert metrics.reasoning_tokens == 40


@pytest.mark.parametrize(
    "overrides",
    [
        {"input_tokens_details": {}, "output_tokens_details": {}},
        {"input_tokens_details": None, "output_tokens_details": None},
        {"input_tokens": None, "output_tokens": None, "total_tokens": None},
    ],
)
def test_metrics_tolerate_a_partial_usage_envelope(overrides):
    """The usage envelope differs by backing provider, and MessageMetrics adds these as ints.

    The Anthropic and Fireworks backings omit fields the OpenAI one sends.
    """
    metrics = RampRouter(api_key="test-key")._get_metrics(_usage(**overrides))

    for value in (
        metrics.input_tokens,
        metrics.output_tokens,
        metrics.total_tokens,
        metrics.cache_read_tokens,
        metrics.cache_write_tokens,
        metrics.reasoning_tokens,
    ):
        assert isinstance(value, int)


def _response(*, output=None):
    """A Response built the way the SDK builds one from a Router payload."""
    from openai.types.responses import Response

    return Response.construct(
        id="resp_test",
        object="response",
        created_at=0,
        status="completed",
        model="gpt-5.6-luna",
        output=output if output is not None else [],
        parallel_tool_calls=True,
        tool_choice="auto",
        tools=[],
    )


def _message_item(text):
    from openai.types.responses import ResponseOutputMessage

    return ResponseOutputMessage.construct(
        id="msg_test",
        type="message",
        status="completed",
        role="assistant",
        content=[{"type": "output_text", "text": text, "annotations": []}],
    )


def test_response_does_not_mirror_the_answer_as_reasoning():
    """Setting `reasoning` must not make the answer show up a second time as reasoning.

    The base class copies output_text into reasoning_content whenever `reasoning` is set and no
    summary came back, and setting `reasoning` is how Router's wider effort values are reached.
    """
    model = RampRouter(api_key="test-key", reasoning={"effort": "xhigh"})
    response = _response(output=[_message_item("The answer is 4.")])

    parsed = model._parse_provider_response(response)

    assert parsed.content == "The answer is 4."
    assert parsed.reasoning_content is None


def test_response_keeps_a_real_reasoning_summary():
    """A summary the provider actually sent is still reported."""
    from openai.types.responses import ResponseReasoningItem

    reasoning_item = ResponseReasoningItem.construct(
        id="rs_test",
        type="reasoning",
        summary=[{"type": "summary_text", "text": "Adding two and two."}],
    )
    model = RampRouter(api_key="test-key", reasoning={"effort": "xhigh"})

    parsed = model._parse_provider_response(_response(output=[reasoning_item, _message_item("4")]))

    assert parsed.content == "4"
    assert parsed.reasoning_content == "Adding two and two."


def test_stream_does_not_mirror_text_deltas_as_reasoning():
    """The streaming half of the same heuristic."""
    from types import SimpleNamespace

    model = RampRouter(api_key="test-key", reasoning={"effort": "xhigh"})
    event = SimpleNamespace(type="response.output_text.delta", delta="4", item_id="msg_test")

    model_response, _ = model._parse_provider_response_delta(event, Message(role="assistant"), {})

    assert model_response.content == "4"
    assert model_response.reasoning_content is None


def test_stream_keeps_reasoning_summary_deltas():
    """A summary delta is reasoning content and must survive."""
    from types import SimpleNamespace

    model = RampRouter(api_key="test-key", reasoning={"effort": "xhigh"})
    event = SimpleNamespace(type="response.reasoning_summary_text.delta", delta="Adding two and two.")

    model_response, _ = model._parse_provider_response_delta(event, Message(role="assistant"), {})

    assert model_response.reasoning_content == "Adding two and two."


def test_count_tokens_does_not_call_the_api():
    """Token counting stays local: Router serves no token-counting endpoint.

    The base class wraps its API call in a bare `except Exception` and falls back to the local
    tokenizer, so a raising stub would be swallowed. Record the call instead.
    """
    model = RampRouter(api_key="test-key")
    calls = []

    model.get_client = lambda: calls.append("sync")  # type: ignore[method-assign, return-value]

    assert model.count_tokens([Message(role="user", content="hello there")]) > 0
    assert calls == []


async def test_acount_tokens_does_not_call_the_api():
    """The async variant counts locally too, and agrees with the sync one."""
    model = RampRouter(api_key="test-key")
    calls = []

    model.get_client = lambda: calls.append("sync")  # type: ignore[method-assign, return-value]
    model.get_async_client = lambda: calls.append("async")  # type: ignore[method-assign, return-value]

    messages = [Message(role="user", content="hello there")]

    assert await model.acount_tokens(messages) == model.count_tokens(messages)
    assert calls == []


# --- Request body, captured at the transport ---------------------------------------------------
#
# The model selector is applied at the four invoke call sites rather than in get_request_params,
# so asserting on get_request_params alone cannot see it. These drive a real invoke through a stub
# transport and read the body the SDK actually serialized. No network.


COMPLETED_RESPONSE = {
    "id": "resp_test",
    "object": "response",
    "created_at": 0,
    "status": "completed",
    "model": "gpt-5.6-luna",
    "output": [
        {
            "id": "msg_test",
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "OK", "annotations": []}],
        }
    ],
    "parallel_tool_calls": True,
    "tool_choice": "auto",
    "tools": [],
    "usage": {
        "input_tokens": 8,
        "output_tokens": 2,
        "total_tokens": 10,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 0},
    },
}


def _captured_body(model, stream=False):
    """Run one invoke against a stub transport and return the request body the SDK sent."""
    import json

    import httpx

    bodies = []

    def handler(request: "httpx.Request") -> "httpx.Response":
        bodies.append(json.loads(request.content))
        if stream:
            event = {"type": "response.completed", "sequence_number": 0, "response": COMPLETED_RESPONSE}
            body = f"event: response.completed\ndata: {json.dumps(event)}\n\n"
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=COMPLETED_RESPONSE)

    model.http_client = httpx.Client(transport=httpx.MockTransport(handler))
    messages = [Message(role="user", content="hi")]

    if stream:
        list(model.invoke_stream(messages=messages, assistant_message=Message(role="assistant")))
    else:
        model.invoke(messages=messages, assistant_message=Message(role="assistant"))

    assert len(bodies) == 1
    return bodies[0]


@pytest.mark.parametrize("stream", [False, True])
def test_request_sends_model_by_default(stream):
    """Without a candidate list the request carries `model`."""
    body = _captured_body(RampRouter(api_key="test-key", id="gpt-5.5"), stream=stream)

    assert body["model"] == "gpt-5.5"
    assert "models" not in body


@pytest.mark.parametrize("stream", [False, True])
def test_request_sends_models_instead_of_model(stream):
    """With a candidate list the request carries `models` and drops `model` entirely.

    Router rejects a request carrying both, which is the whole point of the selector seam.
    """
    model = RampRouter(api_key="test-key", models=["openai:gpt-5-nano", "anthropic:claude-haiku-4-5"])
    body = _captured_body(model, stream=stream)

    assert body["models"] == ["openai:gpt-5-nano", "anthropic:claude-haiku-4-5"]
    assert "model" not in body


def test_request_omits_the_fields_router_rejects_by_default():
    """A default RampRouter sends no reasoning block, no temperature and no store."""
    body = _captured_body(RampRouter(api_key="test-key"))

    for field in ("reasoning", "temperature", "top_p", "store", "models", "allow_flex_tier"):
        assert field not in body, f"{field} should not be sent by default"


def test_request_carries_the_router_only_fields():
    """The Router-only fields reach the top level of the body, not a nested object."""
    model = RampRouter(
        api_key="test-key",
        allow_flex_tier=False,
        provider_timeout=30,
        timeout_before_headers=10,
        metadata={"team": "platform"},
    )
    body = _captured_body(model)

    assert body["allow_flex_tier"] is False
    assert body["provider_timeout"] == 30
    assert body["timeout_before_headers"] == 10
    assert body["metadata"] == {"team": "platform"}
