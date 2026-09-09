"""
Tests for `Claude._handle_api_error` logging (#9952).

A 529 or an in-stream `overloaded_error` (which surfaces with the stream's HTTP
status, 200) is retried by `base.py`, which already logs every attempt at WARNING.
The old code logged ERROR before classifying, so each recovered overload left a
misleading `Claude API error (status 200)` ERROR line behind — the noisiest line
in some production logs.
"""

from typing import List, Tuple

import httpx
import pytest
from anthropic import APIStatusError

from agno.exceptions import ModelProviderError, ModelRateLimitError
from agno.models.anthropic.claude import Claude


def _status_error(status_code: int, message: str) -> APIStatusError:
    """Build an `APIStatusError` the way the Anthropic SDK does, with the given HTTP status."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status_code, request=request, text=message)
    return APIStatusError(message, response=response, body=None)


@pytest.fixture
def model() -> Claude:
    return Claude()


@pytest.fixture
def log_calls(monkeypatch) -> List[Tuple[str, str]]:
    """Record `(level, message)` for every `log_warning`/`log_error` call in the module under test."""
    calls: List[Tuple[str, str]] = []
    monkeypatch.setattr("agno.models.anthropic.claude.log_warning", lambda msg, *a, **k: calls.append(("WARNING", msg)))
    monkeypatch.setattr("agno.models.anthropic.claude.log_error", lambda msg, *a, **k: calls.append(("ERROR", msg)))
    return calls


def test_in_stream_overloaded_error_warns_and_names_the_error(model, log_calls):
    e = _status_error(200, "overloaded_error: Overloaded")

    with pytest.raises(ModelRateLimitError) as exc_info:
        model._handle_api_error(e)

    assert exc_info.value.status_code == 200
    # No ERROR line for a retryable overload, and the message names the error type
    # instead of the stream's meaningless HTTP status.
    assert log_calls == [("WARNING", "Claude API overloaded: overloaded_error: Overloaded")]


def test_529_overloaded_warns(model, log_calls):
    e = _status_error(529, "Overloaded")

    with pytest.raises(ModelRateLimitError):
        model._handle_api_error(e)

    assert log_calls == [("WARNING", "Claude API overloaded: Overloaded")]


def test_other_api_status_error_still_logs_error(model, log_calls):
    e = _status_error(400, "invalid_request_error: max_tokens is required")

    with pytest.raises(ModelProviderError):
        model._handle_api_error(e)

    assert log_calls == [("ERROR", "Claude API error (status 400)")]
