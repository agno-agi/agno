import os
from unittest.mock import MagicMock, patch

import pytest

# Set test API key to avoid env var lookup errors
os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

from agno.exceptions import ModelProviderError
from agno.models.openai.chat import OpenAIChat


@pytest.fixture
def model():
    """Create a model instance for testing."""
    return OpenAIChat(id="gpt-4o-mini", retries=3)


@pytest.fixture
def model_with_retries():
    """Create a model instance with retries and no delay."""
    return OpenAIChat(id="gpt-4o-mini", retries=3, delay_between_retries=0)


@pytest.fixture
def model_with_two_retries():
    """Create a model instance with 2 retries and no delay."""
    return OpenAIChat(id="gpt-4o-mini", retries=2, delay_between_retries=0)


# =============================================================================
# Tests for _is_retryable_error method - Status Codes
# =============================================================================


@pytest.mark.parametrize(
    "status_code",
    [400, 401, 403, 413, 422],
    ids=["bad_request", "unauthorized", "forbidden", "payload_too_large", "unprocessable_entity"],
)
def test_non_retryable_status_codes(model, status_code):
    """Verify that client error status codes are not retryable."""
    error = ModelProviderError("Test error", status_code=status_code)
    assert model._is_retryable_error(error) is False


@pytest.mark.parametrize(
    "status_code",
    [429, 500, 502, 503, 504],
    ids=["rate_limit", "internal_error", "bad_gateway", "service_unavailable", "gateway_timeout"],
)
def test_retryable_status_codes(model, status_code):
    """Verify that server error and rate limit status codes are retryable."""
    error = ModelProviderError("Test error", status_code=status_code)
    assert model._is_retryable_error(error) is True


# =============================================================================
# Tests for _is_retryable_error method - Error Message Patterns
# =============================================================================


@pytest.mark.parametrize(
    "error_message",
    [
        "context_length_exceeded",
        "This model's maximum context length is 8192 tokens",
        "Your request exceeded the context window limit",
        "token limit exceeded",
        "max_tokens exceeded",
        "You have too many tokens in your request",
        "payload too large",
        "content_too_large",
        "request too large for model",
        "input too long",
        "Request exceeds the model's context limit",
    ],
    ids=[
        "context_length_exceeded",
        "maximum_context_length",
        "context_window",
        "token_limit",
        "max_tokens",
        "too_many_tokens",
        "payload_too_large",
        "content_too_large",
        "request_too_large",
        "input_too_long",
        "exceeds_the_model",
    ],
)
def test_non_retryable_error_patterns(model, error_message):
    """Verify that context/token limit error patterns are not retryable even with retryable status."""
    # Using status code 500 (normally retryable) to test that message patterns take precedence
    error = ModelProviderError(error_message, status_code=500)
    assert model._is_retryable_error(error) is False


@pytest.mark.parametrize(
    "error_message",
    [
        "Rate limit exceeded, please retry",
        "Server error, please try again",
        "Connection timeout",
        "Internal server error",
        "Service temporarily unavailable",
        "Gateway timeout occurred",
        "Temporary failure in name resolution",
    ],
    ids=[
        "rate_limit_message",
        "server_error",
        "connection_timeout",
        "internal_error",
        "service_unavailable",
        "gateway_timeout",
        "dns_failure",
    ],
)
def test_retryable_error_patterns(model, error_message):
    """Verify that transient error messages are retryable."""
    error = ModelProviderError(error_message, status_code=500)
    assert model._is_retryable_error(error) is True


def test_case_insensitive_pattern_matching(model):
    """Verify that error message pattern matching is case-insensitive."""
    patterns = [
        "CONTEXT_LENGTH_EXCEEDED",
        "Maximum Context Length Exceeded",
        "TOKEN LIMIT",
        "PAYLOAD TOO LARGE",
    ]
    for pattern in patterns:
        error = ModelProviderError(pattern, status_code=500)
        assert model._is_retryable_error(error) is False, f"Pattern '{pattern}' should not be retryable"


# =============================================================================
# Tests for Sync Retry Behavior
# =============================================================================


def test_sync_non_retryable_error_not_retried(model_with_retries):
    """Verify that non-retryable errors are raised immediately without retries."""
    call_count = 0

    def mock_invoke(**kwargs):
        nonlocal call_count
        call_count += 1
        raise ModelProviderError(
            "This model's maximum context length is 8192 tokens",
            status_code=400,
        )

    with patch.object(model_with_retries, "invoke", side_effect=mock_invoke):
        with pytest.raises(ModelProviderError) as exc_info:
            model_with_retries._invoke_with_retry(messages=[])

        assert call_count == 1, "Non-retryable error should not trigger retries"
        assert "maximum context length" in str(exc_info.value)


def test_sync_retryable_error_is_retried(model_with_retries):
    """Verify that retryable errors trigger the configured number of retries."""
    call_count = 0

    def mock_invoke(**kwargs):
        nonlocal call_count
        call_count += 1
        raise ModelProviderError("Internal server error", status_code=500)

    with patch.object(model_with_retries, "invoke", side_effect=mock_invoke):
        with pytest.raises(ModelProviderError):
            model_with_retries._invoke_with_retry(messages=[])

        # With retries=3, expect 4 total calls (1 initial + 3 retries)
        assert call_count == 4, f"Expected 4 calls (1 + 3 retries), got {call_count}"


def test_sync_success_after_transient_failure(model_with_retries):
    """Verify that success after a transient failure stops retrying."""
    call_count = 0
    mock_response = MagicMock()

    def mock_invoke(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ModelProviderError("Server error", status_code=500)
        return mock_response

    with patch.object(model_with_retries, "invoke", side_effect=mock_invoke):
        result = model_with_retries._invoke_with_retry(messages=[])

        assert result == mock_response
        assert call_count == 3, "Should succeed on third attempt"


def test_sync_auth_error_not_retried(model_with_retries):
    """Verify that authentication errors (401) are not retried."""
    call_count = 0

    def mock_invoke(**kwargs):
        nonlocal call_count
        call_count += 1
        raise ModelProviderError("Invalid API key", status_code=401)

    with patch.object(model_with_retries, "invoke", side_effect=mock_invoke):
        with pytest.raises(ModelProviderError):
            model_with_retries._invoke_with_retry(messages=[])

        assert call_count == 1, "Auth errors should not be retried"


def test_sync_payload_too_large_not_retried(model_with_retries):
    """Verify that payload too large errors (413) are not retried."""
    call_count = 0

    def mock_invoke(**kwargs):
        nonlocal call_count
        call_count += 1
        raise ModelProviderError("Request entity too large", status_code=413)

    with patch.object(model_with_retries, "invoke", side_effect=mock_invoke):
        with pytest.raises(ModelProviderError):
            model_with_retries._invoke_with_retry(messages=[])

        assert call_count == 1, "Payload too large errors should not be retried"


# =============================================================================
# Tests for Async Retry Behavior
# =============================================================================


@pytest.mark.asyncio
async def test_async_non_retryable_error_not_retried(model_with_retries):
    """Verify that non-retryable errors are raised immediately without retries (async)."""
    call_count = 0

    async def mock_ainvoke(**kwargs):
        nonlocal call_count
        call_count += 1
        raise ModelProviderError(
            "This model's maximum context length is 8192 tokens",
            status_code=400,
        )

    with patch.object(model_with_retries, "ainvoke", side_effect=mock_ainvoke):
        with pytest.raises(ModelProviderError) as exc_info:
            await model_with_retries._ainvoke_with_retry(messages=[])

        assert call_count == 1, "Non-retryable error should not trigger retries"
        assert "maximum context length" in str(exc_info.value)


@pytest.mark.asyncio
async def test_async_retryable_error_is_retried(model_with_retries):
    """Verify that retryable errors trigger retries (async)."""
    call_count = 0

    async def mock_ainvoke(**kwargs):
        nonlocal call_count
        call_count += 1
        raise ModelProviderError("Internal server error", status_code=500)

    with patch.object(model_with_retries, "ainvoke", side_effect=mock_ainvoke):
        with pytest.raises(ModelProviderError):
            await model_with_retries._ainvoke_with_retry(messages=[])

        assert call_count == 4, f"Expected 4 calls, got {call_count}"


@pytest.mark.asyncio
async def test_async_success_after_transient_failure(model_with_retries):
    """Verify that success after a transient failure stops retrying (async)."""
    call_count = 0
    mock_response = MagicMock()

    async def mock_ainvoke(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise ModelProviderError("Server error", status_code=503)
        return mock_response

    with patch.object(model_with_retries, "ainvoke", side_effect=mock_ainvoke):
        result = await model_with_retries._ainvoke_with_retry(messages=[])

        assert result == mock_response
        assert call_count == 2


# =============================================================================
# Tests for Streaming Retry Behavior
# =============================================================================


def test_sync_stream_non_retryable_error_not_retried(model_with_two_retries):
    """Verify that non-retryable errors in streaming are not retried."""
    call_count = 0

    def mock_invoke_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        raise ModelProviderError("context_length_exceeded", status_code=400)
        yield  # Make it a generator

    with patch.object(model_with_two_retries, "invoke_stream", side_effect=mock_invoke_stream):
        with pytest.raises(ModelProviderError):
            list(model_with_two_retries._invoke_stream_with_retry(messages=[]))

        assert call_count == 1, "Non-retryable stream error should not trigger retries"


def test_sync_stream_retryable_error_is_retried(model_with_two_retries):
    """Verify that retryable errors in streaming trigger retries."""
    call_count = 0

    def mock_invoke_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        raise ModelProviderError("Server error", status_code=500)
        yield  # Make it a generator

    with patch.object(model_with_two_retries, "invoke_stream", side_effect=mock_invoke_stream):
        with pytest.raises(ModelProviderError):
            list(model_with_two_retries._invoke_stream_with_retry(messages=[]))

        # With retries=2, expect 3 total calls (1 initial + 2 retries)
        assert call_count == 3, f"Expected 3 calls, got {call_count}"


@pytest.mark.asyncio
async def test_async_stream_non_retryable_error_not_retried(model_with_two_retries):
    """Verify that non-retryable errors in async streaming are not retried."""
    call_count = 0

    async def mock_ainvoke_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        raise ModelProviderError("context_length_exceeded", status_code=400)
        yield  # Make it an async generator

    with patch.object(model_with_two_retries, "ainvoke_stream", side_effect=mock_ainvoke_stream):
        with pytest.raises(ModelProviderError):
            async for _ in model_with_two_retries._ainvoke_stream_with_retry(messages=[]):
                pass

        assert call_count == 1, "Non-retryable async stream error should not trigger retries"


@pytest.mark.asyncio
async def test_async_stream_retryable_error_is_retried(model_with_two_retries):
    """Verify that retryable errors in async streaming trigger retries."""
    call_count = 0

    async def mock_ainvoke_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        raise ModelProviderError("Server error", status_code=500)
        yield  # Make it an async generator

    with patch.object(model_with_two_retries, "ainvoke_stream", side_effect=mock_ainvoke_stream):
        with pytest.raises(ModelProviderError):
            async for _ in model_with_two_retries._ainvoke_stream_with_retry(messages=[]):
                pass

        assert call_count == 3, f"Expected 3 calls, got {call_count}"


# =============================================================================
# Tests for Retry Configuration
# =============================================================================


def test_zero_retries_means_no_retry():
    """Verify that retries=0 means only one attempt."""
    model = OpenAIChat(id="gpt-4o-mini", retries=0)
    call_count = 0

    def mock_invoke(**kwargs):
        nonlocal call_count
        call_count += 1
        raise ModelProviderError("Server error", status_code=500)

    with patch.object(model, "invoke", side_effect=mock_invoke):
        with pytest.raises(ModelProviderError):
            model._invoke_with_retry(messages=[])

        assert call_count == 1, "With retries=0, only one attempt should be made"


def test_exponential_backoff_delay_calculation():
    """Verify that exponential backoff calculates delays correctly."""
    model = OpenAIChat(id="gpt-4o-mini", retries=3, delay_between_retries=1, exponential_backoff=True)

    assert model._get_retry_delay(0) == 1  # 1 * 2^0 = 1
    assert model._get_retry_delay(1) == 2  # 1 * 2^1 = 2
    assert model._get_retry_delay(2) == 4  # 1 * 2^2 = 4
    assert model._get_retry_delay(3) == 8  # 1 * 2^3 = 8


def test_linear_delay_calculation():
    """Verify that linear (non-exponential) delay is constant."""
    model = OpenAIChat(id="gpt-4o-mini", retries=3, delay_between_retries=2, exponential_backoff=False)

    assert model._get_retry_delay(0) == 2
    assert model._get_retry_delay(1) == 2
    assert model._get_retry_delay(2) == 2
    assert model._get_retry_delay(3) == 2


# =============================================================================
# Tests for ModelProviderError Attributes
# =============================================================================


def test_error_with_model_info(model):
    """Verify error classification works with model name and id."""
    error = ModelProviderError(
        "context_length_exceeded",
        status_code=400,
        model_name="gpt-4o",
        model_id="gpt-4o-2024-05-13",
    )
    assert model._is_retryable_error(error) is False
    assert error.model_name == "gpt-4o"
    assert error.model_id == "gpt-4o-2024-05-13"


def test_default_status_code(model):
    """Verify that default status code (502) is retryable."""
    error = ModelProviderError("Unknown error")  # Default status_code=502
    assert model._is_retryable_error(error) is True
