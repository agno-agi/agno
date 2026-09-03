"""_populate_stream_data must not yield chunks that carry no payload.

Regression test for #9490. ``ModelResponse.tool_calls`` is
``field(default_factory=list)``, so the gate ``if delta.tool_calls is not
None`` was true for *every* delta, including the metadata-only chunks
providers emit (Anthropic's ``content_block_start``, for example). Each one
was yielded and then dropped further downstream, costing a generator turn
plus every hook between the model and the agent.

The neighbouring branches in the same function (``provider_data``,
``images``, ``videos``) already test truthiness, which is what makes the
``is not None`` on ``tool_calls`` an oversight rather than a deliberate
choice.
"""

from typing import List

import pytest

from agno.models.base import MessageData, Model
from agno.models.response import ModelResponse


class _StubModel(Model):
    """Concrete Model; only _populate_stream_data is exercised."""

    def __init__(self):
        super().__init__(id="stub", name="Stub", provider="test")

    def invoke(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    async def ainvoke(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def invoke_stream(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    async def ainvoke_stream(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def _parse_provider_response(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def _parse_provider_response_delta(self, *a, **k):  # pragma: no cover
        raise NotImplementedError


def _drain(delta: ModelResponse) -> List[ModelResponse]:
    return list(_StubModel()._populate_stream_data(MessageData(), delta))


# --- the bug ---------------------------------------------------------------


def test_empty_delta_is_not_yielded():
    """A metadata-only chunk carries nothing to show and must not be yielded."""
    assert _drain(ModelResponse()) == []


def test_role_only_delta_is_not_yielded():
    """Anthropic's content_block_start shape: a role and nothing else."""
    assert _drain(ModelResponse(role="assistant")) == []


def test_empty_tool_calls_list_is_not_yielded():
    """The specific regression: [] is not None, but [] is not a payload."""
    delta = ModelResponse(tool_calls=[])
    assert delta.tool_calls == [], "guard the premise: default is a list, not None"
    assert _drain(delta) == []


# --- everything that should still be yielded -------------------------------


def test_content_is_yielded():
    assert len(_drain(ModelResponse(content="hi"))) == 1


def test_populated_tool_calls_are_yielded():
    delta = ModelResponse(tool_calls=[{"id": "c1", "function": {"name": "f", "arguments": "{}"}}])
    out = _drain(delta)
    assert len(out) == 1


def test_populated_tool_calls_still_accumulate_on_stream_data():
    """The fix must not stop tool calls being collected."""
    sd = MessageData()
    call = {"id": "c1", "function": {"name": "f", "arguments": "{}"}}
    list(_StubModel()._populate_stream_data(sd, ModelResponse(tool_calls=[call])))
    assert sd.response_tool_calls == [call]


def test_empty_tool_calls_do_not_create_an_empty_accumulator():
    """An empty delta should leave stream_data untouched, not seed [] onto it."""
    sd = MessageData()
    list(_StubModel()._populate_stream_data(sd, ModelResponse()))
    assert not sd.response_tool_calls


@pytest.mark.parametrize(
    "delta",
    [
        ModelResponse(reasoning_content="thinking"),
        ModelResponse(redacted_reasoning_content="[redacted]"),
        ModelResponse(content=""),  # empty string is still a content signal
    ],
)
def test_other_payloads_still_yield(delta):
    assert len(_drain(delta)) == 1
