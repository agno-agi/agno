"""Tests for Knowledge bug fixes.

Bug #1: Loop continuation - return -> continue in topic loaders
Bug #2: List filter validation - validate FilterExpr keys
Bug #3: Search tool exception handling - catch and return error message
"""

from typing import Set
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.filters import AND, EQ, OR

# --- Bug #1: Loop continuation tests ---


def test_load_from_topics_continues_after_skip():
    """Sync topic loading processes all topics even if some are skipped."""
    from agno.knowledge.knowledge import Knowledge

    knowledge = Knowledge()
    knowledge.vector_db = MagicMock()
    knowledge.vector_db.__class__.__name__ = "MockVectorDb"
    knowledge.vector_db.content_hash_exists = MagicMock(return_value=False)

    # Track which topics were processed
    processed_topics = []

    # Mock _should_skip to skip first topic only
    skip_pattern = [True, False, False]  # Skip A, process B and C
    skip_index = [0]

    def mock_should_skip(content_hash, skip_if_exists):
        result = skip_pattern[skip_index[0] % len(skip_pattern)]
        skip_index[0] += 1
        return result

    knowledge._should_skip = mock_should_skip
    knowledge._insert_contents_db = MagicMock()
    knowledge._update_content = MagicMock()
    knowledge._handle_vector_db_insert = MagicMock()
    knowledge._build_content_hash = MagicMock(return_value="hash")
    knowledge._prepare_documents_for_insert = MagicMock()

    # Create a mock reader that tracks what it reads
    mock_reader = MagicMock()
    mock_reader.read = MagicMock(side_effect=lambda topic: (processed_topics.append(topic), [MagicMock()])[1])

    from agno.knowledge.content import Content

    content = Content(topics=["A", "B", "C"], reader=mock_reader)

    knowledge._load_from_topics(content, upsert=False, skip_if_exists=True)

    # B and C should have been processed (A was skipped)
    assert "B" in processed_topics
    assert "C" in processed_topics


@pytest.mark.asyncio
async def test_aload_from_topics_continues_after_skip():
    """Async topic loading processes all topics even if some are skipped."""
    from agno.knowledge.knowledge import Knowledge

    knowledge = Knowledge()
    knowledge.vector_db = MagicMock()
    knowledge.vector_db.__class__.__name__ = "MockVectorDb"
    knowledge.vector_db.content_hash_exists = MagicMock(return_value=False)

    # Track which topics were processed
    processed_topics = []

    # Mock _should_skip to skip first topic only
    skip_pattern = [True, False, False]  # Skip A, process B and C
    skip_index = [0]

    def mock_should_skip(content_hash, skip_if_exists):
        result = skip_pattern[skip_index[0] % len(skip_pattern)]
        skip_index[0] += 1
        return result

    knowledge._should_skip = mock_should_skip
    knowledge._ainsert_contents_db = AsyncMock()
    knowledge._aupdate_content = AsyncMock()
    knowledge._ahandle_vector_db_insert = AsyncMock()
    knowledge._build_content_hash = MagicMock(return_value="hash")
    knowledge._prepare_documents_for_insert = MagicMock()

    # Create a mock reader that tracks what it reads
    mock_reader = MagicMock()

    async def mock_async_read(topic):
        processed_topics.append(topic)
        return [MagicMock()]

    mock_reader.async_read = mock_async_read

    from agno.knowledge.content import Content

    content = Content(topics=["A", "B", "C"], reader=mock_reader)

    await knowledge._aload_from_topics(content, upsert=False, skip_if_exists=True)

    # B and C should have been processed (A was skipped)
    assert "B" in processed_topics
    assert "C" in processed_topics


# --- Bug #2: Filter validation tests ---


def test_validate_filters_removes_invalid_dict_keys():
    """Invalid dict filter keys are removed during validation."""
    from agno.knowledge.knowledge import Knowledge

    knowledge = Knowledge()
    filters = {"region": "us", "invalid_key": "value"}
    valid_metadata: Set[str] = {"region", "year"}

    valid, invalid = knowledge._validate_filters(filters, valid_metadata)

    assert "region" in valid
    assert "invalid_key" not in valid
    assert "invalid_key" in invalid


def test_validate_filters_removes_invalid_list_items():
    """Invalid list filter items are removed during validation."""
    from agno.knowledge.knowledge import Knowledge

    knowledge = Knowledge()
    filters = [EQ("region", "us"), EQ("invalid_key", "value")]
    valid_metadata: Set[str] = {"region", "year"}

    valid, invalid = knowledge._validate_filters(filters, valid_metadata)

    valid_keys = [f.key for f in valid]
    assert "region" in valid_keys
    assert "invalid_key" not in valid_keys
    assert "invalid_key" in invalid


def test_validate_filters_keeps_complex_filters():
    """Complex filters (AND, OR) are kept even without key attribute."""
    from agno.knowledge.knowledge import Knowledge

    knowledge = Knowledge()
    # AND/OR filters don't have a .key attribute directly
    filters = [AND(EQ("region", "us"), EQ("year", 2024)), OR(EQ("region", "eu"))]
    valid_metadata: Set[str] = {"region", "year"}

    valid, invalid = knowledge._validate_filters(filters, valid_metadata)

    # Complex filters should be kept as-is
    assert len(valid) == 2
    assert len(invalid) == 0


# --- Bug #3: Search exception handling tests ---


def test_search_tool_catches_exceptions():
    """Search tool returns error message instead of raising."""
    from agno.knowledge.knowledge import Knowledge

    knowledge = Knowledge()
    knowledge.vector_db = MagicMock()
    knowledge.search = MagicMock(side_effect=Exception("Connection refused"))

    tool = knowledge._create_search_tool(async_mode=False)
    result = tool.entrypoint(query="test")

    assert isinstance(result, str)
    assert "Error searching knowledge base" in result
    assert "Exception" in result  # Exception type name


def test_search_tool_with_filters_catches_exceptions():
    """Search tool with filters returns error message instead of raising."""
    from agno.knowledge.knowledge import Knowledge

    knowledge = Knowledge()
    knowledge.vector_db = MagicMock()
    knowledge.search = MagicMock(side_effect=Exception("DB timeout"))

    tool = knowledge._create_search_tool_with_filters(async_mode=False)
    result = tool.entrypoint(query="test")

    assert isinstance(result, str)
    assert "Error searching knowledge base" in result


@pytest.mark.asyncio
async def test_async_search_tool_catches_exceptions():
    """Async search tool returns error message instead of raising."""
    from agno.knowledge.knowledge import Knowledge

    knowledge = Knowledge()
    knowledge.vector_db = MagicMock()
    knowledge.asearch = AsyncMock(side_effect=Exception("Network error"))

    tool = knowledge._create_search_tool(async_mode=True)
    result = await tool.entrypoint(query="test")

    assert isinstance(result, str)
    assert "Error searching knowledge base" in result


@pytest.mark.asyncio
async def test_async_search_tool_with_filters_catches_exceptions():
    """Async search tool with filters returns error message instead of raising."""
    from agno.knowledge.knowledge import Knowledge

    knowledge = Knowledge()
    knowledge.vector_db = MagicMock()
    knowledge.asearch = AsyncMock(side_effect=Exception("Connection timeout"))

    tool = knowledge._create_search_tool_with_filters(async_mode=True)
    result = await tool.entrypoint(query="test")

    assert isinstance(result, str)
    assert "Error searching knowledge base" in result


def test_search_tool_does_not_leak_sensitive_info():
    """Search tool error message uses exception type, not full message."""
    from agno.knowledge.knowledge import Knowledge

    knowledge = Knowledge()
    knowledge.vector_db = MagicMock()
    # Simulate an exception with sensitive connection string
    knowledge.search = MagicMock(side_effect=Exception("Connection failed: postgres://user:password@host:5432/db"))

    tool = knowledge._create_search_tool(async_mode=False)
    result = tool.entrypoint(query="test")

    # Should contain exception type name, not the sensitive connection string
    assert "Exception" in result
    assert "password" not in result


# --- Bug #1 extended: Multiple skip scenarios ---


def test_load_from_topics_multiple_skips():
    """Topic loading handles multiple consecutive skips correctly."""
    from agno.knowledge.content import Content
    from agno.knowledge.knowledge import Knowledge

    knowledge = Knowledge()
    knowledge.vector_db = MagicMock()
    knowledge.vector_db.__class__.__name__ = "MockVectorDb"
    knowledge.vector_db.content_hash_exists = MagicMock(return_value=False)

    processed_topics = []

    # A exists, B exists, C new, D exists, E new
    skip_pattern = [True, True, False, True, False]
    skip_index = [0]

    def mock_should_skip(content_hash, skip_if_exists):
        result = skip_pattern[skip_index[0] % len(skip_pattern)]
        skip_index[0] += 1
        return result

    knowledge._should_skip = mock_should_skip
    knowledge._insert_contents_db = MagicMock()
    knowledge._update_content = MagicMock()
    knowledge._handle_vector_db_insert = MagicMock()
    knowledge._build_content_hash = MagicMock(return_value="hash")
    knowledge._prepare_documents_for_insert = MagicMock()

    mock_reader = MagicMock()
    mock_reader.read = MagicMock(side_effect=lambda topic: (processed_topics.append(topic), [MagicMock()])[1])

    content = Content(topics=["A", "B", "C", "D", "E"], reader=mock_reader)
    knowledge._load_from_topics(content, upsert=False, skip_if_exists=True)

    # Only C and E should be processed
    assert processed_topics == ["C", "E"]


def test_load_from_topics_all_skipped():
    """Topic loading handles case where all topics are skipped."""
    from agno.knowledge.content import Content
    from agno.knowledge.knowledge import Knowledge

    knowledge = Knowledge()
    knowledge.vector_db = MagicMock()
    knowledge.vector_db.__class__.__name__ = "MockVectorDb"

    processed_topics = []

    # All topics already exist
    knowledge._should_skip = MagicMock(return_value=True)
    knowledge._insert_contents_db = MagicMock()
    knowledge._update_content = MagicMock()
    knowledge._build_content_hash = MagicMock(return_value="hash")

    mock_reader = MagicMock()
    mock_reader.read = MagicMock(side_effect=lambda topic: (processed_topics.append(topic), [MagicMock()])[1])

    content = Content(topics=["A", "B", "C"], reader=mock_reader)
    knowledge._load_from_topics(content, upsert=False, skip_if_exists=True)

    # No topics should be processed
    assert processed_topics == []
    # But update_content should be called for each skipped topic
    assert knowledge._update_content.call_count == 3


# --- Bug #2 extended: Filter validation edge cases ---


def test_validate_filters_with_prefixed_keys():
    """Filter validation handles meta_data.key prefixed keys."""
    from agno.knowledge.knowledge import Knowledge

    knowledge = Knowledge()
    filters = {"meta_data.region": "us", "meta_data.invalid": "value"}
    valid_metadata: Set[str] = {"region", "year"}

    valid, invalid = knowledge._validate_filters(filters, valid_metadata)

    # meta_data.region should match because base_key "region" is valid
    assert "meta_data.region" in valid
    assert "meta_data.invalid" not in valid
    assert "meta_data.invalid" in invalid


def test_validate_filters_empty_metadata():
    """Filter validation returns original list when no metadata available."""
    from agno.knowledge.knowledge import Knowledge

    knowledge = Knowledge()
    filters = [EQ("region", "us")]

    # Empty metadata set
    valid, invalid = knowledge._validate_filters(filters, set())

    # Should return original filters with warning
    assert valid == filters
    assert invalid == []


def test_validate_filters_mixed_valid_invalid_list():
    """Filter validation correctly separates valid and invalid list filters."""
    from agno.knowledge.knowledge import Knowledge

    knowledge = Knowledge()
    filters = [
        EQ("region", "us"),
        EQ("invalid1", "value"),
        EQ("year", 2024),
        EQ("invalid2", "value"),
    ]
    valid_metadata: Set[str] = {"region", "year"}

    valid, invalid = knowledge._validate_filters(filters, valid_metadata)

    assert len(valid) == 2
    assert len(invalid) == 2
    valid_keys = [f.key for f in valid]
    assert "region" in valid_keys
    assert "year" in valid_keys
    assert "invalid1" in invalid
    assert "invalid2" in invalid


# --- Filter merge tests ---


def test_filter_merge_raises_on_type_mismatch():
    """Merging dict and list filters raises ValueError."""
    from agno.utils.knowledge import get_agentic_or_user_search_filters

    with pytest.raises(ValueError):
        get_agentic_or_user_search_filters({"region": "us"}, [EQ("year", 2024)])
