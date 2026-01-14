from agno.compression.manager import CompressionManager
from agno.models.message import Message


def test_default_tool_call_compression_count_limits():
    """Test default count-based limits when no token limit is set."""
    cm = CompressionManager(compress_tool_results=True)
    assert cm.compress_tool_results_limit == 3


def test_default_context_compression_count_limits():
    """Test default count-based limits when no token limit is set."""
    cm = CompressionManager(compress_context=True)
    assert cm.compress_context_messages_limit == 10


def test_token_limit_none():
    """Test that token limit is None when no compression strategy is enabled."""
    cm = CompressionManager(compress_token_limit=1000)
    assert cm.compress_tool_results_limit is None
    assert cm.compress_context_messages_limit is None


def test_should_compress_context_count_based():
    """Test _should_compress_context with count-based threshold."""
    cm = CompressionManager(compress_context=True, compress_context_messages_limit=3)

    # Below limit
    messages = [Message(role="user", content="Hello"), Message(role="assistant", content="Hi")]
    assert cm._should_compress_context(messages) is False

    # At limit
    messages.append(Message(role="user", content="How are you?"))
    assert cm._should_compress_context(messages) is True


def test_should_compress_tools_count_based():
    """Test _should_compress_tools with count-based threshold."""
    cm = CompressionManager(compress_tool_results=True, compress_tool_results_limit=2)

    # Below limit
    messages = [Message(role="tool", content="Result 1")]
    assert cm._should_compress_tools(messages) is False

    # At limit (ignores already compressed)
    messages.append(Message(role="tool", content="Result 2", compressed_content="Compressed"))
    assert cm._should_compress_tools(messages) is False  # Only 1 uncompressed

    messages.append(Message(role="tool", content="Result 3"))
    assert cm._should_compress_tools(messages) is True  # 2 uncompressed
