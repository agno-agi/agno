"""Tests for skills file_ids extraction and container info capture in streaming and non-streaming paths."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from anthropic.types import MessageStopEvent

from agno.models.anthropic import Claude


def _create_mock_usage():
    mock_usage = MagicMock()
    mock_usage.input_tokens = 10
    mock_usage.output_tokens = 20
    mock_usage.cache_creation_input_tokens = None
    mock_usage.cache_read_input_tokens = None
    return mock_usage


def _create_file_output_block(file_id: str):
    """Create a bash_code_execution_tool_result block with a file_id."""
    file_output = MagicMock()
    file_output.type = "bash_code_execution_output"
    file_output.file_id = file_id

    code_result_content = MagicMock()
    code_result_content.content = [file_output]

    block = MagicMock()
    block.type = "bash_code_execution_tool_result"
    block.content = code_result_content
    return block


def _create_text_block(text: str = "Done"):
    block = MagicMock()
    block.type = "text"
    block.text = text
    block.citations = None
    return block


def _create_container_mock(container_id: str = "container_xyz", expires_at=None):
    container = MagicMock()
    container.id = container_id
    container.expires_at = expires_at or datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc)
    return container


def _create_non_streaming_response(content_blocks, container=None):
    response = MagicMock()
    response.id = "msg_test"
    response.model = "claude-sonnet-4-5-20250929"
    response.role = "assistant"
    response.stop_reason = "end_turn"
    response.content = content_blocks
    response.usage = _create_mock_usage()
    response.container = container
    response.context_management = None
    return response


def _create_stream_stop_event(content_blocks, container=None):
    """Create a MessageStopEvent with message content — this is what the streaming path receives."""
    message = MagicMock()
    message.content = content_blocks
    message.usage = _create_mock_usage()
    message.context_management = None
    message.container = container

    event = MagicMock(spec=MessageStopEvent)
    event.type = "message_stop"
    event.message = message
    return event


# =============================================================================
# Non-streaming: file_ids extraction
# =============================================================================


def test_non_streaming_extracts_file_ids_when_skills_enabled():
    """Skills-enabled model should extract file_ids from bash_code_execution_tool_result."""
    model = Claude(
        id="claude-sonnet-4-5-20250929",
        skills=[{"type": "anthropic", "skill_id": "xlsx", "version": "latest"}],
    )
    response = _create_non_streaming_response(
        [
            _create_text_block(),
            _create_file_output_block("file_abc123"),
        ]
    )

    result = model._parse_provider_response(response)

    assert result.provider_data is not None
    assert result.provider_data["file_ids"] == ["file_abc123"]


def test_non_streaming_extracts_file_ids_without_skills():
    """Model without skills (standalone code_execution) should still extract file_ids."""
    model = Claude(id="claude-sonnet-4-5-20250929")
    response = _create_non_streaming_response(
        [
            _create_text_block(),
            _create_file_output_block("file_abc123"),
        ]
    )

    result = model._parse_provider_response(response)

    assert result.provider_data is not None
    assert result.provider_data["file_ids"] == ["file_abc123"]


# =============================================================================
# Non-streaming: container info
# =============================================================================


def test_non_streaming_captures_container_info():
    """Container ID and expiry should be captured in provider_data."""
    model = Claude(id="claude-sonnet-4-5-20250929")
    container = _create_container_mock("container_xyz789")
    response = _create_non_streaming_response([_create_text_block()], container=container)

    result = model._parse_provider_response(response)

    assert result.provider_data is not None
    assert result.provider_data["container"]["id"] == "container_xyz789"


# =============================================================================
# Streaming: file_ids extraction (the critical fix)
# =============================================================================


def test_streaming_extracts_file_ids_at_message_stop():
    """Streaming path should extract file_ids from the final MessageStopEvent."""
    model = Claude(
        id="claude-sonnet-4-5-20250929",
        skills=[{"type": "anthropic", "skill_id": "xlsx", "version": "latest"}],
    )
    event = _create_stream_stop_event(
        [
            _create_text_block(),
            _create_file_output_block("file_stream_456"),
        ]
    )

    result = model._parse_provider_response_delta(event)

    assert result.provider_data is not None
    assert result.provider_data["file_ids"] == ["file_stream_456"]


def test_streaming_captures_container_at_message_stop():
    """Streaming path should capture container info from the final MessageStopEvent."""
    model = Claude(
        id="claude-sonnet-4-5-20250929",
        skills=[{"type": "anthropic", "skill_id": "xlsx", "version": "latest"}],
    )
    container = _create_container_mock("container_stream_999")
    event = _create_stream_stop_event([_create_text_block()], container=container)

    result = model._parse_provider_response_delta(event)

    assert result.provider_data is not None
    assert result.provider_data["container"]["id"] == "container_stream_999"


def test_streaming_extracts_multiple_file_ids():
    """Multiple file_ids from different code execution blocks should all be captured."""
    model = Claude(
        id="claude-sonnet-4-5-20250929",
        skills=[{"type": "anthropic", "skill_id": "xlsx", "version": "latest"}],
    )
    event = _create_stream_stop_event(
        [
            _create_text_block(),
            _create_file_output_block("file_one"),
            _create_file_output_block("file_two"),
        ]
    )

    result = model._parse_provider_response_delta(event)

    assert result.provider_data is not None
    assert result.provider_data["file_ids"] == ["file_one", "file_two"]


# =============================================================================
# Container ID reuse across turns (reads from messages, not model instance)
# =============================================================================


def _make_message(role: str, container_id: str | None = None):
    """Create a minimal Message-like mock with optional container provider_data."""
    msg = MagicMock()
    msg.role = role
    if container_id:
        msg.provider_data = {"container": {"id": container_id}}
    else:
        msg.provider_data = None
    return msg


def test_extract_container_id_from_messages_returns_last():
    """Should return the container ID from the most recent message that has one."""
    model = Claude(id="claude-sonnet-4-5-20250929")
    messages = [
        _make_message("user"),
        _make_message("assistant", container_id="container_turn1"),
        _make_message("user"),
        _make_message("assistant", container_id="container_turn2"),
    ]
    assert model._extract_container_id_from_messages(messages) == "container_turn2"


def test_extract_container_id_from_messages_returns_none_when_absent():
    """Should return None when no message has a container ID."""
    model = Claude(id="claude-sonnet-4-5-20250929")
    messages = [_make_message("user"), _make_message("assistant")]
    assert model._extract_container_id_from_messages(messages) is None


def test_prepare_request_kwargs_includes_container_id_when_messages_have_one():
    """get_request_params should include container.id when messages contain a prior container."""
    model = Claude(
        id="claude-sonnet-4-5-20250929",
        skills=[{"type": "anthropic", "skill_id": "xlsx", "version": "latest"}],
    )
    messages = [
        _make_message("user"),
        _make_message("assistant", container_id="container_abc"),
    ]
    kwargs = model._prepare_request_kwargs("system prompt", messages=messages)
    assert kwargs["container"]["id"] == "container_abc"
    assert kwargs["container"]["skills"] == model.skills


def test_prepare_request_kwargs_omits_container_id_on_first_turn():
    """On the first turn (no prior assistant message with container), no id should be set."""
    model = Claude(
        id="claude-sonnet-4-5-20250929",
        skills=[{"type": "anthropic", "skill_id": "xlsx", "version": "latest"}],
    )
    messages = [_make_message("user")]
    kwargs = model._prepare_request_kwargs("system prompt", messages=messages)
    assert "id" not in kwargs["container"]
    assert kwargs["container"]["skills"] == model.skills


def test_prepare_request_kwargs_safe_with_shared_model_instance():
    """Two independent runs using the same model instance should not share container IDs."""
    model = Claude(
        id="claude-sonnet-4-5-20250929",
        skills=[{"type": "anthropic", "skill_id": "xlsx", "version": "latest"}],
    )
    # Run A has a container from a previous turn
    messages_a = [_make_message("assistant", container_id="container_run_a")]
    kwargs_a = model._prepare_request_kwargs("system", messages=messages_a)
    assert kwargs_a["container"]["id"] == "container_run_a"

    # Run B starts fresh — no container in its messages
    messages_b = [_make_message("user")]
    kwargs_b = model._prepare_request_kwargs("system", messages=messages_b)
    assert "id" not in kwargs_b["container"]
