"""Unit tests for token counting utilities."""

import sys
from unittest.mock import MagicMock, patch

# Import log_warning module before patching __import__ to avoid recursion
from agno.utils import log
from agno.utils.tokens import count_tokens


def test_count_tokens_basic():
    """Test basic token counting with simple text."""
    result = count_tokens("Hello world")
    assert isinstance(result, int)
    assert result > 0
    # "Hello world" should be 2 tokens with cl100k_base encoding
    assert result == 2


def test_count_tokens_empty_string():
    """Test token counting with empty string."""
    result = count_tokens("")
    assert result == 0


def test_count_tokens_single_word():
    """Test token counting with a single word."""
    result = count_tokens("Hello")
    assert isinstance(result, int)
    assert result > 0


def test_count_tokens_multiple_words():
    """Test token counting with multiple words."""
    text = "The quick brown fox jumps over the lazy dog"
    result = count_tokens(text)
    assert isinstance(result, int)
    assert result > 0


def test_count_tokens_long_text():
    """Test token counting with longer text."""
    text = " ".join(["word"] * 100)
    result = count_tokens(text)
    assert isinstance(result, int)
    assert result > 0


def test_count_tokens_special_characters():
    """Test token counting with special characters."""
    text = "Hello! How are you? I'm fine, thanks."
    result = count_tokens(text)
    assert isinstance(result, int)
    assert result > 0


def test_count_tokens_unicode():
    """Test token counting with unicode characters."""
    text = "Hello 世界 🌍"
    result = count_tokens(text)
    assert isinstance(result, int)
    assert result > 0


def test_count_tokens_newlines():
    """Test token counting with newlines."""
    text = "Line 1\nLine 2\nLine 3"
    result = count_tokens(text)
    assert isinstance(result, int)
    assert result > 0


def test_count_tokens_whitespace():
    """Test token counting with various whitespace."""
    text = "   Multiple   spaces   and\t\ttabs   "
    result = count_tokens(text)
    assert isinstance(result, int)
    assert result > 0


def test_count_tokens_import_error_fallback():
    """Test fallback to character-based estimation when tiktoken is not available."""
    # Remove tiktoken from sys.modules to simulate it not being installed
    original_tiktoken = sys.modules.pop("tiktoken", None)
    original_import = __import__

    def import_side_effect(name, *args, **kwargs):
        if name == "tiktoken":
            raise ImportError(f"No module named '{name}'")
        # For other imports, use the real import
        return original_import(name, *args, **kwargs)

    try:
        with patch("builtins.__import__", side_effect=import_side_effect):
            with patch.object(log, "log_warning") as mock_log:
                result = count_tokens("Hello world")

                # Should use fallback: len("Hello world") // 4 = 11 // 4 = 2
                assert result == 2
                # Should log a warning
                mock_log.assert_called_once()
                assert "tiktoken not installed" in mock_log.call_args[0][0].lower()
    finally:
        # Restore tiktoken if it was there
        if original_tiktoken is not None:
            sys.modules["tiktoken"] = original_tiktoken


def test_count_tokens_import_error_fallback_empty_string():
    """Test fallback with empty string when tiktoken is not available."""
    # Remove tiktoken from sys.modules to simulate it not being installed
    original_tiktoken = sys.modules.pop("tiktoken", None)
    original_import = __import__

    def import_side_effect(name, *args, **kwargs):
        if name == "tiktoken":
            raise ImportError(f"No module named '{name}'")
        return original_import(name, *args, **kwargs)

    try:
        with patch("builtins.__import__", side_effect=import_side_effect):
            with patch.object(log, "log_warning"):
                result = count_tokens("")
                assert result == 0
    finally:
        # Restore tiktoken if it was there
        if original_tiktoken is not None:
            sys.modules["tiktoken"] = original_tiktoken


def test_count_tokens_import_error_fallback_long_text():
    """Test fallback with longer text when tiktoken is not available."""
    # Remove tiktoken from sys.modules to simulate it not being installed
    original_tiktoken = sys.modules.pop("tiktoken", None)
    original_import = __import__

    def import_side_effect(name, *args, **kwargs):
        if name == "tiktoken":
            raise ImportError(f"No module named '{name}'")
        return original_import(name, *args, **kwargs)

    try:
        text = "a" * 100  # 100 characters
        with patch("builtins.__import__", side_effect=import_side_effect):
            with patch.object(log, "log_warning"):
                result = count_tokens(text)
                # Fallback: 100 // 4 = 25
                assert result == 25
    finally:
        # Restore tiktoken if it was there
        if original_tiktoken is not None:
            sys.modules["tiktoken"] = original_tiktoken


def test_count_tokens_general_exception_fallback():
    """Test fallback to character-based estimation when tiktoken raises an exception."""
    # Mock tiktoken to raise an exception when get_encoding is called
    mock_tiktoken = MagicMock()
    mock_tiktoken.get_encoding.side_effect = Exception("Unexpected error")

    with patch.dict("sys.modules", {"tiktoken": mock_tiktoken}):
        with patch.object(log, "log_warning") as mock_log:
            result = count_tokens("Hello world")

            # Should use fallback: len("Hello world") // 4 = 11 // 4 = 2
            assert result == 2
            # Should log a warning
            mock_log.assert_called_once()
            assert "error counting tokens" in mock_log.call_args[0][0].lower()


def test_count_tokens_general_exception_fallback_empty_string():
    """Test fallback with empty string when tiktoken raises an exception."""
    # Mock tiktoken to raise an exception when encode is called
    mock_tiktoken = MagicMock()
    mock_encoding = MagicMock()
    mock_encoding.encode.side_effect = Exception("Unexpected error")
    mock_tiktoken.get_encoding.return_value = mock_encoding

    with patch.dict("sys.modules", {"tiktoken": mock_tiktoken}):
        with patch.object(log, "log_warning"):
            result = count_tokens("")
            assert result == 0


def test_count_tokens_get_encoding_exception():
    """Test fallback when get_encoding raises an exception."""
    # Mock tiktoken to raise an exception when get_encoding is called
    mock_tiktoken = MagicMock()
    mock_tiktoken.get_encoding.side_effect = Exception("Encoding error")

    with patch.dict("sys.modules", {"tiktoken": mock_tiktoken}):
        with patch.object(log, "log_warning") as mock_log:
            result = count_tokens("Hello world")
            assert result == 2
            mock_log.assert_called_once()


def test_count_tokens_consistency():
    """Test that token counting is consistent for the same input."""
    text = "The quick brown fox"
    result1 = count_tokens(text)
    result2 = count_tokens(text)
    assert result1 == result2


def test_count_tokens_different_lengths():
    """Test that longer texts generally have more tokens."""
    short_text = "Hello"
    long_text = "Hello " * 10

    short_count = count_tokens(short_text)
    long_count = count_tokens(long_text)

    assert long_count >= short_count
