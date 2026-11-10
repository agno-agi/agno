"""``Claude._handle_api_error`` maps SDK exceptions to agno's model errors. The base model retries
the retryable ones and logs every attempt itself, so the handler must not log those at ERROR first
unless no retry will run, and an overload signalled inside a stream (which the SDK raises with the
stream's HTTP status, 200) must be reported as an overload, not as "status 200"."""

from unittest.mock import MagicMock

import httpx
import pytest
from anthropic import APIConnectionError, APIStatusError, RateLimitError

from agno.exceptions import ModelProviderError, ModelRateLimitError
from agno.models.anthropic.claude import Claude

REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.fixture
def logs(monkeypatch):
    warn, error = MagicMock(), MagicMock()
    monkeypatch.setattr("agno.models.anthropic.claude.log_warning", warn)
    monkeypatch.setattr("agno.models.anthropic.claude.log_error", error)
    return warn, error


def _status_error(status: int, error_type: str, message: str = "boom") -> APIStatusError:
    # For an error event inside a stream the SDK sets the exception message to the whole
    # JSON body (anthropic/_streaming.py, ``err_msg = f"{body}"``), so the error type is
    # part of str(exc); a plain HTTP error carries the API's message.
    body = {"type": "error", "error": {"type": error_type, "message": message}}
    return APIStatusError(
        str(body) if status == 200 else message,
        response=httpx.Response(status, request=REQUEST),
        body=body,
    )


def _rate_limit_error() -> RateLimitError:
    return RateLimitError("slow down", response=httpx.Response(429, request=REQUEST), body=None)


def _handle(exc: Exception, retries: int = 1) -> Exception:
    with pytest.raises((ModelProviderError, ModelRateLimitError)) as raised:
        Claude(id="claude-sonnet-4-6", api_key="x", retries=retries)._handle_api_error(exc)
    return raised.value


def test_in_stream_overload_is_retryable_and_named(logs):
    warn, error = logs

    raised = _handle(_status_error(200, "overloaded_error", "Overloaded"))

    assert isinstance(raised, ModelRateLimitError)
    warn.assert_called_once_with("Claude API overloaded")
    error.assert_not_called()


def test_529_is_retryable_and_logged_at_warning(logs):
    warn, error = logs

    raised = _handle(_status_error(529, "overloaded_error"))

    assert isinstance(raised, ModelRateLimitError)
    assert raised.status_code == 529
    warn.assert_called_once()
    error.assert_not_called()


def test_connection_error_is_logged_at_warning(logs):
    warn, error = logs

    raised = _handle(APIConnectionError(request=REQUEST))

    assert type(raised) is ModelProviderError
    warn.assert_called_once_with("Connection error while calling Claude API")
    error.assert_not_called()


def test_rate_limit_stays_a_warning(logs):
    warn, error = logs

    raised = _handle(_rate_limit_error())

    assert isinstance(raised, ModelRateLimitError)
    warn.assert_called_once()
    error.assert_not_called()


@pytest.mark.parametrize(
    "exc",
    [
        _status_error(200, "overloaded_error", "Overloaded"),
        _status_error(529, "overloaded_error"),
        APIConnectionError(request=REQUEST),
        _rate_limit_error(),
    ],
    ids=["in_stream_overload", "529", "connection", "rate_limit"],
)
def test_without_retries_a_retryable_error_is_terminal_and_logged_at_error(logs, exc):
    # The base model logs the final failure only when retries > 0, so with the default of 0
    # the handler's own line is the only ERROR a monitoring rule can catch.
    warn, error = logs

    _handle(exc, retries=0)

    error.assert_called_once()
    warn.assert_not_called()


def test_a_client_error_is_still_an_error(logs):
    warn, error = logs

    raised = _handle(_status_error(400, "invalid_request_error"))

    assert type(raised) is ModelProviderError
    assert raised.status_code == 400
    error.assert_called_once_with("Claude API error (status 400)")
    warn.assert_not_called()
