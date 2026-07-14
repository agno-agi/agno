"""Tests for AgenticChunking with custom prompts."""

from unittest.mock import Mock, patch

import pytest

from agno.knowledge.chunking.agentic import DEFAULT_INSTRUCTIONS, MAX_CHUNK_SIZE, AgenticChunking
from agno.knowledge.document.base import Document


@pytest.fixture
def mock_model():
    """Create a mock model for testing."""
    model = Mock()
    model.response = Mock()
    return model


def test_custom_prompt_uses_default_instructions(mock_model):
    """Test that custom_prompt is wrapped with DEFAULT_INSTRUCTIONS."""
    mock_response = Mock()
    mock_response.content = "500"
    mock_model.response.return_value = mock_response

    custom_prompt = "Break at sentence boundaries"
    with patch("agno.knowledge.chunking.agentic.get_model", return_value=mock_model):
        chunker = AgenticChunking(model="test-model", max_chunk_size=1000, custom_prompt=custom_prompt)

    doc = Document(id="test", name="test", content="A" * 2000)
    chunks = chunker.chunk(doc)

    assert mock_model.response.called

    call_args = mock_model.response.call_args
    messages = call_args[0][0]
    actual_prompt = messages[0].content

    assert "Break at sentence boundaries" in actual_prompt
    assert "1000" in actual_prompt
    assert "Constraint:" in actual_prompt
    assert "Text:" in actual_prompt
    assert len(chunks) > 0


def test_early_return_for_small_content(mock_model):
    """Test that small content returns early without calling LLM."""
    with patch("agno.knowledge.chunking.agentic.get_model", return_value=mock_model):
        chunker = AgenticChunking(model="test-model")

    small_content = "Small content"
    doc = Document(id="test", name="test", content=small_content)
    chunks = chunker.chunk(doc)

    # Model should NOT be called because content is smaller than max_chunk_size
    assert not mock_model.response.called
    # Should return single document
    assert len(chunks) == 1
    assert chunks[0].content == small_content


def test_early_return_with_custom_prompt(mock_model):
    """Test that small content returns early even with custom_prompt."""
    custom_prompt = "Split at logical boundaries"
    with patch("agno.knowledge.chunking.agentic.get_model", return_value=mock_model):
        chunker = AgenticChunking(model="test-model", custom_prompt=custom_prompt)

    small_content = "Small content"
    doc = Document(id="test", name="test", content=small_content)
    chunks = chunker.chunk(doc)

    # Model should NOT be called even with custom_prompt if content is small
    assert not mock_model.response.called
    assert len(chunks) == 1
    assert chunks[0].content == small_content


def test_no_custom_prompt_uses_default_prompt(mock_model):
    """Test that without custom_prompt, the default prompt is used."""
    mock_response = Mock()
    mock_response.content = "1000"
    mock_model.response.return_value = mock_response

    with patch("agno.knowledge.chunking.agentic.get_model", return_value=mock_model):
        chunker = AgenticChunking(model="test-model", max_chunk_size=2000)

    doc = Document(id="test", name="test", content="A" * 3000)
    chunks = chunker.chunk(doc)

    assert mock_model.response.called

    call_args = mock_model.response.call_args
    messages = call_args[0][0]
    actual_prompt = messages[0].content

    assert "Analyze this text and determine a natural breakpoint" in actual_prompt
    assert "semantic completeness, paragraph boundaries, and topic transitions" in actual_prompt
    assert "User Instructions:" not in actual_prompt
    assert len(chunks) > 0


def test_custom_prompt_formatting(mock_model):
    """Test that custom_prompt correctly formats all placeholders."""
    mock_response = Mock()
    mock_response.content = "500"
    mock_model.response.return_value = mock_response

    custom_prompt = "My custom chunking logic"
    max_chunk_size = 1000
    with patch("agno.knowledge.chunking.agentic.get_model", return_value=mock_model):
        chunker = AgenticChunking(model="test-model", max_chunk_size=max_chunk_size, custom_prompt=custom_prompt)

    content = "A" * 1500
    doc = Document(id="test", name="test", content=content)
    chunks = chunker.chunk(doc)

    call_args = mock_model.response.call_args_list[0]
    messages = call_args[0][0]
    actual_prompt = messages[0].content

    assert custom_prompt in actual_prompt
    assert str(max_chunk_size) in actual_prompt
    assert "User Instructions:" in actual_prompt
    assert "Constraint:" in actual_prompt
    assert "Text:" in actual_prompt
    assert content[:max_chunk_size] in actual_prompt
    assert len(chunks) > 0


def test_custom_prompt_respects_max_chunk_size_limit(mock_model):
    """Test that breakpoint never exceeds max_chunk_size."""
    mock_response = Mock()
    # Model returns a value larger than max_chunk_size
    mock_response.content = "6000"
    mock_model.response.return_value = mock_response

    custom_prompt = "Break into large chunks"
    with patch("agno.knowledge.chunking.agentic.get_model", return_value=mock_model):
        chunker = AgenticChunking(model="test-model", max_chunk_size=MAX_CHUNK_SIZE, custom_prompt=custom_prompt)

    doc = Document(id="test", name="test", content="A" * 10000)
    chunks = chunker.chunk(doc)

    # Each chunk should not exceed maximum chunk size
    for chunk in chunks:
        assert len(chunk.content) <= MAX_CHUNK_SIZE


def test_custom_prompt_model_failure_fallback(mock_model):
    """Test that when model fails, it falls back to max_chunk_size."""
    mock_model.response.side_effect = Exception("Model error")

    custom_prompt = "Break at logical points"
    with patch("agno.knowledge.chunking.agentic.get_model", return_value=mock_model):
        chunker = AgenticChunking(model="test-model", max_chunk_size=1000, custom_prompt=custom_prompt)

    doc = Document(id="test", name="test", content="A" * 2500)
    chunks = chunker.chunk(doc)

    # Should fallback and create chunks of max_chunk_size
    assert len(chunks) == 3
    assert len(chunks[0].content) == 1000
    assert len(chunks[1].content) == 1000
    assert len(chunks[2].content) == 500


def test_default_instructions_constant():
    """Test that DEFAULT_INSTRUCTIONS has the expected structure."""
    assert "User Instructions:" in DEFAULT_INSTRUCTIONS
    assert "{custom_instructions}" in DEFAULT_INSTRUCTIONS
    assert "{max_chunk_size}" in DEFAULT_INSTRUCTIONS
    assert "{text}" in DEFAULT_INSTRUCTIONS
    assert "Constraint:" in DEFAULT_INSTRUCTIONS
    assert "character position number" in DEFAULT_INSTRUCTIONS


def test_initialization_with_custom_prompt(mock_model):
    """Test that custom_prompt is stored correctly."""
    custom_prompt = "Test prompt"
    with patch("agno.knowledge.chunking.agentic.get_model", return_value=mock_model):
        chunker = AgenticChunking(model="test-model", max_chunk_size=1000, custom_prompt=custom_prompt)

    assert chunker.custom_prompt == custom_prompt
    assert chunker.chunk_size == 1000
    assert chunker.model is mock_model


def test_initialization_without_custom_prompt(mock_model):
    """Test that custom_prompt defaults to None."""
    with patch("agno.knowledge.chunking.agentic.get_model", return_value=mock_model):
        chunker = AgenticChunking(model="test-model", max_chunk_size=1000)

    assert chunker.custom_prompt is None
    assert chunker.chunk_size == 1000


def test_initialization_with_default_model():
    """Test that OpenAIChat model is created when no model provided."""
    mock_openai_instance = Mock()

    with patch("agno.models.openai.OpenAIChat", return_value=mock_openai_instance):
        chunker = AgenticChunking(max_chunk_size=1000, custom_prompt="Test")

        assert chunker.model is mock_openai_instance


def test_logging_when_custom_prompt_without_max_chunk_size(mock_model):
    """Test that logging occurs when custom_prompt is provided without max_chunk_size."""
    custom_prompt = "Test prompt"

    with patch("agno.knowledge.chunking.agentic.get_model", return_value=mock_model):
        with patch("agno.knowledge.chunking.agentic.log_debug") as mock_log_debug:
            chunker = AgenticChunking(model="test-model", custom_prompt=custom_prompt)

            assert mock_log_debug.called
            call_args = mock_log_debug.call_args[0][0]
            assert "default chunk size" in call_args.lower()
            assert str(MAX_CHUNK_SIZE) in call_args
            assert "custom_prompt" in call_args.lower()
            assert chunker.chunk_size == MAX_CHUNK_SIZE


def test_no_logging_when_custom_prompt_with_max_chunk_size(mock_model):
    """Test that no logging occurs when both custom_prompt and max_chunk_size are provided."""
    custom_prompt = "Test prompt"

    with patch("agno.knowledge.chunking.agentic.get_model", return_value=mock_model):
        with patch("agno.knowledge.chunking.agentic.log_debug") as mock_log_debug:
            chunker = AgenticChunking(model="test-model", max_chunk_size=3000, custom_prompt=custom_prompt)

            assert not mock_log_debug.called
            assert chunker.chunk_size == 3000


def test_no_logging_when_no_custom_prompt(mock_model):
    """Test that no logging occurs when custom_prompt is not provided."""
    with patch("agno.knowledge.chunking.agentic.get_model", return_value=mock_model):
        with patch("agno.knowledge.chunking.agentic.log_debug") as mock_log_debug:
            chunker = AgenticChunking(model="test-model")

            assert not mock_log_debug.called
            assert chunker.chunk_size == MAX_CHUNK_SIZE
