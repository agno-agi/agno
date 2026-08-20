"""Test Slack mrkdwn sanitization for tool names and args."""

from unittest.mock import MagicMock

import pytest

from agno.os.interfaces.slack.types import sanitize_mrkdwn_text, tool_name


class TestSanitizeMrkdwnText:
    """Test the sanitize_mrkdwn_text function."""

    def test_backtick_replaced(self):
        # Backtick would close a code span in mrkdwn
        assert "`" not in sanitize_mrkdwn_text("hello`world")
        assert sanitize_mrkdwn_text("hello`world") == "helloˋworld"

    def test_angle_brackets_replaced(self):
        # Angle brackets create Slack control sequences
        assert "<" not in sanitize_mrkdwn_text("hello<@U123>world")
        assert ">" not in sanitize_mrkdwn_text("hello<@U123>world")
        assert sanitize_mrkdwn_text("<@U123>") == "‹@U123›"

    def test_newlines_escaped(self):
        # Newlines exit inline code spans
        assert "\n" not in sanitize_mrkdwn_text("hello\nworld")
        assert "\r" not in sanitize_mrkdwn_text("hello\rworld")
        assert sanitize_mrkdwn_text("hello\nworld") == "hello\\nworld"
        assert sanitize_mrkdwn_text("hello\rworld") == "hello\\rworld"

    def test_safe_text_unchanged(self):
        safe = "normal_tool_name"
        assert sanitize_mrkdwn_text(safe) == safe

    def test_combined_attack(self):
        # Malicious tool name that would break mrkdwn formatting
        malicious = "send`_email<@U123>"
        sanitized = sanitize_mrkdwn_text(malicious)
        # Should not contain any dangerous characters
        assert "`" not in sanitized
        assert "<" not in sanitized
        assert ">" not in sanitized
        # Should use homoglyphs
        assert "ˋ" in sanitized
        assert "‹" in sanitized
        assert "›" in sanitized


class TestToolName:
    """Test that tool_name sanitizes the name from requirements."""

    def test_normal_tool_name(self):
        mock_req = MagicMock()
        mock_req.tool_execution = MagicMock()
        mock_req.tool_execution.tool_name = "send_email"

        result = tool_name(mock_req)
        assert result == "send_email"

    def test_malicious_tool_name_sanitized(self):
        mock_req = MagicMock()
        mock_req.tool_execution = MagicMock()
        mock_req.tool_execution.tool_name = "send`_email<@U123>"

        result = tool_name(mock_req)
        # Should be sanitized
        assert "`" not in result
        assert "<" not in result
        assert ">" not in result
        assert "sendˋ_email‹@U123›" == result

    def test_none_tool_name_fallback(self):
        mock_req = MagicMock()
        mock_req.tool_execution = MagicMock()
        mock_req.tool_execution.tool_name = None

        result = tool_name(mock_req)
        assert result == "tool"

    def test_no_tool_execution(self):
        mock_req = MagicMock()
        mock_req.tool_execution = None

        result = tool_name(mock_req)
        assert result == "tool"
