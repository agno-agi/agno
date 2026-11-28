"""Unit tests for DashScope request params: extra_body merging and built-in web search."""

import json

import httpx
import pytest

from agno.models.dashscope import DashScope
from agno.models.message import Message

CHAT_COMPLETION = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "created": 0,
    "model": "qwen-plus",
    "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


@pytest.mark.parametrize("route", ["extra_body", "request_params"])
def test_user_extra_body_is_merged_not_replaced(route):
    """User extra_body keys survive alongside the thinking flag, and the user's dict is not mutated."""
    user_extra_body = {"enable_search": True}
    source = (
        {"extra_body": user_extra_body}
        if route == "extra_body"
        else {"request_params": {"extra_body": user_extra_body}}
    )
    model = DashScope(api_key="test", **source)

    params = model.get_request_params()

    assert params["extra_body"] == {"enable_search": True, "enable_thinking": False}
    assert user_extra_body == {"enable_search": True}


@pytest.mark.parametrize(
    "model_kwargs, expected",
    [
        ({}, {"enable_thinking": False}),
        ({"enable_search": True}, {"enable_thinking": False, "enable_search": True}),
        ({"enable_search": False}, {"enable_thinking": False, "enable_search": False}),
        (
            {"enable_search": True, "search_options": {"forced_search": True}},
            {"enable_thinking": False, "enable_search": True, "search_options": {"forced_search": True}},
        ),
    ],
    ids=["unset", "search_on", "search_off", "search_options"],
)
def test_search_params_are_only_sent_when_set(model_kwargs, expected):
    """enable_search and search_options are written into extra_body only when they are set."""
    params = DashScope(api_key="test", **model_kwargs).get_request_params()

    assert params["extra_body"] == expected


@pytest.mark.parametrize("route", ["extra_body", "request_params"])
def test_raw_extra_body_keys_take_precedence_over_fields(route):
    """A key set in a raw extra_body is not overwritten by the matching DashScope field."""
    raw = {"enable_thinking": True, "enable_search": False}
    source = {"extra_body": raw} if route == "extra_body" else {"request_params": {"extra_body": raw}}
    model = DashScope(api_key="test", enable_thinking=False, enable_search=True, **source)

    assert model.get_request_params()["extra_body"] == {"enable_thinking": True, "enable_search": False}


def test_request_params_extra_body_replaces_model_extra_body():
    """request_params keeps the last word over the extra_body field, as for other OpenAI-compatible models."""
    model = DashScope(
        api_key="test",
        extra_body={"from_field": 1},
        request_params={"extra_body": {"from_request_params": 1}},
    )

    assert model.get_request_params()["extra_body"] == {"from_request_params": 1, "enable_thinking": False}


@pytest.mark.parametrize(
    "thinking", [{"enable_thinking": True}, {"include_thoughts": True}], ids=lambda k: next(iter(k))
)
def test_thinking_and_search_together(thinking):
    """Thinking and web search flags are sent together in one extra_body."""
    model = DashScope(
        api_key="test",
        thinking_budget=1024,
        enable_search=True,
        search_options={"search_strategy": "max"},
        **thinking,
    )

    assert model.get_request_params()["extra_body"] == {
        "enable_thinking": True,
        "thinking_budget": 1024,
        "enable_search": True,
        "search_options": {"search_strategy": "max"},
    }


def _model_capturing_requests(http_client_cls, sent):
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=CHAT_COMPLETION)

    return DashScope(
        api_key="test",
        enable_search=True,
        search_options={"forced_search": True},
        extra_body={"custom_key": "custom_value"},
        http_client=http_client_cls(transport=httpx.MockTransport(handler)),
    )


def _assert_search_body(sent):
    assert len(sent) == 1
    assert sent[0]["enable_search"] is True
    assert sent[0]["search_options"] == {"forced_search": True}
    assert sent[0]["enable_thinking"] is False
    assert sent[0]["custom_key"] == "custom_value"


def test_search_params_reach_request_body_sync():
    sent: list = []
    model = _model_capturing_requests(httpx.Client, sent)

    model.response(messages=[Message(role="user", content="hi")])

    _assert_search_body(sent)


async def test_search_params_reach_request_body_async():
    sent: list = []
    model = _model_capturing_requests(httpx.AsyncClient, sent)

    await model.aresponse(messages=[Message(role="user", content="hi")])

    _assert_search_body(sent)
