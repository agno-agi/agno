from agno.models.aimlapi import AIMLAPI
from agno.models.message import Message


def test_aimlapi_format_message_signature():
    """Test that AIMLAPI._format_message correctly handles the compress_tool_results argument."""
    model = AIMLAPI(id="gpt-4o-mini", api_key="test-api-key")
    message = Message(role="user", content="Hello")

    # This should not raise a TypeError
    formatted = model._format_message(message, compress_tool_results=True)

    assert isinstance(formatted, dict)
    assert formatted["role"] == "user"
    assert formatted["content"] == "Hello"
