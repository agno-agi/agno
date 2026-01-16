"""Tests for Knowledge bug fixes."""

from typing import Set
from unittest.mock import MagicMock

import pytest

from agno.filters import EQ


# --- Loop continuation tests ---


def test_continue_skips_only_current_item():
    """Continue in a loop skips to next iteration, not the entire function."""

    def process_with_continue(items, skip_items):
        processed = []
        for item in items:
            if item in skip_items:
                continue
            processed.append(item)
        return processed

    assert process_with_continue(["a", "b", "c"], {"a"}) == ["b", "c"]
    assert process_with_continue(["a", "b", "c"], {"b"}) == ["a", "c"]
    assert process_with_continue(["a", "b", "c"], {"a", "c"}) == ["b"]


def test_topic_loading_skips_existing():
    """Topics with existing hashes are skipped, others still load."""

    def load_topics(topics, existing_hashes):
        loaded = []
        for topic in topics:
            if f"hash_{topic}" in existing_hashes:
                continue
            loaded.append(topic)
        return loaded

    assert load_topics(["A", "B", "C"], set()) == ["A", "B", "C"]
    assert load_topics(["A", "B", "C"], {"hash_A"}) == ["B", "C"]


# --- Filter validation tests ---


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


# --- Search exception handling tests ---


def test_search_tool_catches_exceptions():
    """Search tool returns error message instead of raising."""
    from agno.knowledge.knowledge import Knowledge

    knowledge = Knowledge()
    knowledge.vector_db = MagicMock()
    knowledge.search = MagicMock(side_effect=Exception("Search failed"))

    tool = knowledge._create_search_tool(async_mode=False)
    result = tool.entrypoint(query="test")

    assert isinstance(result, str)
    assert "Search failed" in result


def test_search_tool_with_filters_catches_exceptions():
    """Search tool with filters returns error message instead of raising."""
    from agno.knowledge.knowledge import Knowledge

    knowledge = Knowledge()
    knowledge.vector_db = MagicMock()
    knowledge.search = MagicMock(side_effect=Exception("DB error"))

    tool = knowledge._create_search_tool_with_filters(async_mode=False)
    result = tool.entrypoint(query="test")

    assert isinstance(result, str)
    assert "DB error" in result


# --- Filter merge tests ---


def test_filter_merge_raises_on_type_mismatch():
    """Merging dict and list filters raises ValueError."""
    from agno.utils.knowledge import get_agentic_or_user_search_filters

    with pytest.raises(ValueError):
        get_agentic_or_user_search_filters({"region": "us"}, [EQ("year", 2024)])
