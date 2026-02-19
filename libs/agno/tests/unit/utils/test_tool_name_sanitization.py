"""Tests for tool function name sanitization (Azure OpenAI 64-char limit guard)."""

import pytest

from agno.utils.tools import (
    MAX_FUNCTION_NAME_LENGTH,
    _detect_repeating_pattern,
    sanitize_function_name,
    sanitize_tool_calls,
)


class TestDetectRepeatingPattern:
    def test_exact_repetition(self):
        assert _detect_repeating_pattern("abcabc") == "abc"

    def test_triple_repetition(self):
        assert _detect_repeating_pattern("SearchAgnoSearchAgnoSearchAgno") == "SearchAgno"

    def test_single_char_repetition(self):
        assert _detect_repeating_pattern("aaaa") == "a"

    def test_no_repetition(self):
        assert _detect_repeating_pattern("hello") is None

    def test_partial_repetition(self):
        # "SearchAgnoSearchAgnoSear" - starts with two full repeats of "SearchAgno"
        result = _detect_repeating_pattern("SearchAgnoSearchAgnoSear")
        assert result == "SearchAgno"

    def test_empty_string(self):
        assert _detect_repeating_pattern("") is None

    def test_single_char(self):
        assert _detect_repeating_pattern("a") is None

    def test_two_chars_same(self):
        assert _detect_repeating_pattern("aa") == "a"

    def test_two_chars_different(self):
        assert _detect_repeating_pattern("ab") is None

    def test_long_repetition(self):
        pattern = "get_weather_data"
        repeated = pattern * 10
        assert _detect_repeating_pattern(repeated) == pattern


class TestSanitizeFunctionName:
    def test_short_name_unchanged(self):
        assert sanitize_function_name("search_agno") == "search_agno"

    def test_exactly_64_chars_unchanged(self):
        name = "a" * 64
        assert sanitize_function_name(name) == name

    def test_name_within_limit_unchanged(self):
        name = "get_weather_for_city"
        assert sanitize_function_name(name) == name
        assert len(name) <= MAX_FUNCTION_NAME_LENGTH

    def test_repeated_name_extracted(self):
        """Simulates model repetition loop: 'SearchAgno' repeated many times."""
        base = "SearchAgno"
        repeated = base * 20  # 200 chars, way over 64
        result = sanitize_function_name(repeated)
        assert result == base
        assert len(result) <= MAX_FUNCTION_NAME_LENGTH

    def test_long_non_repeating_name_truncated(self):
        name = "a_very_long_function_name_that_does_not_repeat_and_exceeds_the_sixty_four_character_limit_for_azure"
        result = sanitize_function_name(name)
        assert len(result) == MAX_FUNCTION_NAME_LENGTH
        assert result == name[:MAX_FUNCTION_NAME_LENGTH]

    def test_empty_name_unchanged(self):
        assert sanitize_function_name("") == ""

    def test_real_world_repetition_scenario(self):
        """Test a realistic scenario from the issue: model generates repeated tool name."""
        base = "SearchAgnoSearchAgno"
        # If the model concatenates the base name with itself multiple times
        name = base * 5  # "SearchAgnoSearchAgno" * 5 = 100 chars
        result = sanitize_function_name(name)
        # Should detect "SearchAgno" as the repeating unit
        assert result == "SearchAgno"
        assert len(result) <= MAX_FUNCTION_NAME_LENGTH


class TestSanitizeToolCalls:
    def test_normal_tool_calls_unchanged(self):
        tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {"name": "search", "arguments": '{"query": "test"}'},
            }
        ]
        result = sanitize_tool_calls(tool_calls)
        assert result[0]["function"]["name"] == "search"

    def test_long_name_sanitized(self):
        long_name = "SearchAgno" * 20
        tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {"name": long_name, "arguments": '{"query": "test"}'},
            }
        ]
        result = sanitize_tool_calls(tool_calls)
        assert len(result[0]["function"]["name"]) <= MAX_FUNCTION_NAME_LENGTH
        assert result[0]["function"]["name"] == "SearchAgno"

    def test_multiple_tool_calls_sanitized(self):
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "short_name", "arguments": "{}"},
            },
            {
                "id": "call_2",
                "type": "function",
                "function": {"name": "LongName" * 20, "arguments": "{}"},
            },
        ]
        result = sanitize_tool_calls(tool_calls)
        assert result[0]["function"]["name"] == "short_name"
        assert result[1]["function"]["name"] == "LongName"
        assert len(result[1]["function"]["name"]) <= MAX_FUNCTION_NAME_LENGTH

    def test_tool_call_without_function_key(self):
        tool_calls = [{"id": "call_123", "type": "function"}]
        # Should not raise
        result = sanitize_tool_calls(tool_calls)
        assert result == tool_calls

    def test_tool_call_with_none_name(self):
        tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {"name": None, "arguments": "{}"},
            }
        ]
        # Should not raise
        result = sanitize_tool_calls(tool_calls)
        assert result[0]["function"]["name"] is None

    def test_preserves_other_fields(self):
        tool_calls = [
            {
                "id": "call_abc",
                "type": "function",
                "function": {"name": "X" * 100, "arguments": '{"key": "value"}'},
            }
        ]
        result = sanitize_tool_calls(tool_calls)
        assert result[0]["id"] == "call_abc"
        assert result[0]["type"] == "function"
        assert result[0]["function"]["arguments"] == '{"key": "value"}'
        assert len(result[0]["function"]["name"]) <= MAX_FUNCTION_NAME_LENGTH

    def test_empty_list(self):
        assert sanitize_tool_calls([]) == []
