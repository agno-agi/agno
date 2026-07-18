"""Tests for OpenAI Responses background mode support."""

from typing import Any, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.exceptions import ModelProviderError
from agno.models.message import Message
from agno.models.openai.responses import OpenAIResponses


class _FakeError:
    def __init__(self, message: str):
        self.message = message


class _FakeResponse:
    """Minimal stand-in for openai.types.responses.Response."""

    def __init__(
        self,
        *,
        _id: str = "resp_test",
        status: str = "completed",
        output: Optional[List[Any]] = None,
        output_text: str = "hello",
        usage: Any = None,
        error: Optional[_FakeError] = None,
        incomplete_details: Any = None,
    ):
        self.id = _id
        self.status = status
        self.output = output or []
        self.output_text = output_text
        self.usage = usage
        self.error = error
        self.incomplete_details = incomplete_details


def _make_assistant_message() -> Message:
    msg = Message(role="assistant")
    # Ensure metrics timer methods don't crash
    return msg


def _make_fake_client() -> MagicMock:
    """Build a MagicMock client whose is_closed() returns False so get_client() reuses it."""
    client = MagicMock()
    client.is_closed.return_value = False
    return client


# ---------------------------------------------------------------------------
# get_request_params
# ---------------------------------------------------------------------------


def test_background_true_forces_store_true():
    """When background=True, store should be forced to True even if self.store=False."""
    model = OpenAIResponses(id="gpt-4.1-mini", background=True, store=False)
    params = model.get_request_params(messages=[Message(role="user", content="hi")])
    assert params.get("background") is True
    assert params.get("store") is True


def test_background_true_forces_store_for_reasoning_model():
    """Reasoning-model branch must not overwrite background-forced store=True back to False."""
    model = OpenAIResponses(id="gpt-5.4", background=True, store=False)
    params = model.get_request_params(messages=[Message(role="user", content="hi")])
    assert params.get("background") is True
    assert params.get("store") is True


def test_background_none_does_not_add_param():
    """When background is not set, the param should not appear in request params."""
    model = OpenAIResponses(id="gpt-4.1-mini")
    params = model.get_request_params(messages=[Message(role="user", content="hi")])
    assert "background" not in params


# ---------------------------------------------------------------------------
# _poll_background_response (sync)
# ---------------------------------------------------------------------------


def test_poll_returns_on_completed_status():
    model = OpenAIResponses(id="gpt-4.1-mini", background=True, background_poll_interval=0.01)

    fake_client = _make_fake_client()
    fake_client.responses.retrieve.side_effect = [
        _FakeResponse(status="queued"),
        _FakeResponse(status="in_progress"),
        _FakeResponse(status="completed"),
    ]
    model.client = fake_client

    result = model._poll_background_response("resp_test")
    assert result.status == "completed"
    assert fake_client.responses.retrieve.call_count == 3


def test_poll_returns_on_cancelled_status():
    """Cancelled should be treated as a terminal state."""
    model = OpenAIResponses(id="gpt-4.1-mini", background=True, background_poll_interval=0.01)

    fake_client = _make_fake_client()
    fake_client.responses.retrieve.return_value = _FakeResponse(status="cancelled")
    model.client = fake_client

    result = model._poll_background_response("resp_test")
    assert result.status == "cancelled"


def test_poll_returns_on_failed_status():
    model = OpenAIResponses(id="gpt-4.1-mini", background=True, background_poll_interval=0.01)

    fake_client = _make_fake_client()
    fake_client.responses.retrieve.return_value = _FakeResponse(status="failed")
    model.client = fake_client

    result = model._poll_background_response("resp_test")
    assert result.status == "failed"


def test_poll_timeout_cancels_and_raises():
    """When max wait is exceeded, should call cancel() and raise ModelProviderError."""
    model = OpenAIResponses(
        id="gpt-4.1-mini",
        background=True,
        background_poll_interval=0.01,
        background_max_wait=0.0,  # immediate timeout
    )

    fake_client = _make_fake_client()
    fake_client.responses.retrieve.return_value = _FakeResponse(status="in_progress")
    model.client = fake_client

    with pytest.raises(ModelProviderError, match="exceeded max wait"):
        model._poll_background_response("resp_test")

    fake_client.responses.cancel.assert_called_once_with("resp_test")


def test_poll_timeout_swallows_cancel_failure():
    """If cancel() fails after timeout, still raise the timeout error, not the cancel error."""
    model = OpenAIResponses(
        id="gpt-4.1-mini",
        background=True,
        background_poll_interval=0.01,
        background_max_wait=0.0,
    )

    fake_client = _make_fake_client()
    fake_client.responses.retrieve.return_value = _FakeResponse(status="in_progress")
    fake_client.responses.cancel.side_effect = RuntimeError("cancel failed")
    model.client = fake_client

    with pytest.raises(ModelProviderError, match="exceeded max wait"):
        model._poll_background_response("resp_test")


# ---------------------------------------------------------------------------
# _apoll_background_response (async)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apoll_returns_on_completed_status():
    model = OpenAIResponses(id="gpt-4.1-mini", background=True, background_poll_interval=0.01)

    fake_client = _make_fake_client()
    fake_client.responses.retrieve = AsyncMock(
        side_effect=[
            _FakeResponse(status="in_progress"),
            _FakeResponse(status="completed"),
        ]
    )
    model.async_client = fake_client

    result = await model._apoll_background_response("resp_test")
    assert result.status == "completed"
    assert fake_client.responses.retrieve.call_count == 2


@pytest.mark.asyncio
async def test_apoll_timeout_cancels_and_raises():
    model = OpenAIResponses(
        id="gpt-4.1-mini",
        background=True,
        background_poll_interval=0.01,
        background_max_wait=0.0,
    )

    fake_client = _make_fake_client()
    fake_client.responses.retrieve = AsyncMock(return_value=_FakeResponse(status="in_progress"))
    fake_client.responses.cancel = AsyncMock()
    model.async_client = fake_client

    with pytest.raises(ModelProviderError, match="exceeded max wait"):
        await model._apoll_background_response("resp_test")

    fake_client.responses.cancel.assert_awaited_once_with("resp_test")


# ---------------------------------------------------------------------------
# invoke / ainvoke integration with polling
# ---------------------------------------------------------------------------


def test_invoke_polls_when_background_response_not_terminal():
    model = OpenAIResponses(id="gpt-4.1-mini", background=True, background_poll_interval=0.01)

    fake_client = _make_fake_client()
    fake_client.responses.create.return_value = _FakeResponse(_id="resp_1", status="queued")
    fake_client.responses.retrieve.side_effect = [
        _FakeResponse(_id="resp_1", status="in_progress"),
        _FakeResponse(_id="resp_1", status="completed", output_text="done"),
    ]
    model.client = fake_client

    assistant = _make_assistant_message()
    with patch.object(model, "_format_messages", return_value=[]):
        result = model.invoke(
            messages=[Message(role="user", content="hi")],
            assistant_message=assistant,
        )

    assert fake_client.responses.retrieve.call_count == 2
    # Parsed response should come from the final polled response
    assert result is not None


def test_invoke_raises_on_cancelled_status():
    model = OpenAIResponses(id="gpt-4.1-mini", background=True, background_poll_interval=0.01)

    fake_client = _make_fake_client()
    fake_client.responses.create.return_value = _FakeResponse(_id="resp_1", status="cancelled")
    model.client = fake_client

    assistant = _make_assistant_message()
    with patch.object(model, "_format_messages", return_value=[]):
        with pytest.raises(ModelProviderError, match="was cancelled"):
            model.invoke(
                messages=[Message(role="user", content="hi")],
                assistant_message=assistant,
            )


def test_invoke_raises_on_failed_status():
    model = OpenAIResponses(id="gpt-4.1-mini", background=True, background_poll_interval=0.01)

    fake_client = _make_fake_client()
    fake_client.responses.create.return_value = _FakeResponse(
        _id="resp_1",
        status="failed",
        error=_FakeError("model crashed"),
    )
    model.client = fake_client

    assistant = _make_assistant_message()
    with patch.object(model, "_format_messages", return_value=[]):
        with pytest.raises(ModelProviderError, match="model crashed"):
            model.invoke(
                messages=[Message(role="user", content="hi")],
                assistant_message=assistant,
            )


@pytest.mark.asyncio
async def test_ainvoke_polls_when_background_response_not_terminal():
    model = OpenAIResponses(id="gpt-4.1-mini", background=True, background_poll_interval=0.01)

    fake_client = _make_fake_client()
    fake_client.responses.create = AsyncMock(return_value=_FakeResponse(_id="resp_1", status="queued"))
    fake_client.responses.retrieve = AsyncMock(
        side_effect=[
            _FakeResponse(_id="resp_1", status="in_progress"),
            _FakeResponse(_id="resp_1", status="completed", output_text="done"),
        ]
    )
    model.async_client = fake_client

    assistant = _make_assistant_message()
    with patch.object(model, "_format_messages", return_value=[]):
        result = await model.ainvoke(
            messages=[Message(role="user", content="hi")],
            assistant_message=assistant,
        )

    assert fake_client.responses.retrieve.call_count == 2
    assert result is not None


# ---------------------------------------------------------------------------
# Streaming: background should be stripped
# ---------------------------------------------------------------------------


def test_invoke_stream_strips_background_flag():
    """invoke_stream should pop `background` from request params before calling the API."""
    model = OpenAIResponses(id="gpt-4.1-mini", background=True)

    fake_client = _make_fake_client()
    fake_client.responses.create.return_value = iter([])
    model.client = fake_client

    assistant = _make_assistant_message()
    with patch.object(model, "_format_messages", return_value=[]):
        list(
            model.invoke_stream(
                messages=[Message(role="user", content="hi")],
                assistant_message=assistant,
            )
        )

    # Verify background was NOT passed to responses.create
    assert fake_client.responses.create.called
    _, kwargs = fake_client.responses.create.call_args
    assert "background" not in kwargs
    assert kwargs.get("stream") is True
