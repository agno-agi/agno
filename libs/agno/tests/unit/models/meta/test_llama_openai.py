import pytest

try:
    from agno.models.meta import LlamaOpenAI
    from agno.models.message import Message

    HAS_LLAMA_API = True
except ImportError:
    HAS_LLAMA_API = False


@pytest.mark.skipif(not HAS_LLAMA_API, reason="llama-api-client is not installed")
def test_llama_openai_format_message_signature():
    """Test that LlamaOpenAI._format_message correctly handles the compress_tool_results argument."""
    model = LlamaOpenAI(id="llama-3.2", api_key="test-api-key")
    message = Message(role="user", content="Hello")

    # This should not raise a TypeError
    formatted = model._format_message(message, compress_tool_results=True)

    assert isinstance(formatted, dict)
    assert formatted["role"] == "user"
    assert formatted["content"] == "Hello"
