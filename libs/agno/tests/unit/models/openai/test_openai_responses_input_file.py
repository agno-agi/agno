"""Tests for input_file support in OpenAIResponses.

Covers _has_file_search_tool(), _format_file_for_input(),
and _format_messages() file embedding logic.
"""

import base64
import tempfile
from pathlib import Path

from agno.media import File
from agno.models.message import Message
from agno.models.openai.responses import OpenAIResponses
from agno.tools.function import Function

# ---------------------------------------------------------------------------
# _has_file_search_tool tests
# ---------------------------------------------------------------------------


def test_has_file_search_tool_none():
    assert OpenAIResponses._has_file_search_tool(None) is False


def test_has_file_search_tool_empty():
    assert OpenAIResponses._has_file_search_tool([]) is False


def test_has_file_search_tool_with_file_search():
    tools = [{"type": "file_search"}]
    assert OpenAIResponses._has_file_search_tool(tools) is True


def test_has_file_search_tool_mixed_tools():
    tools = [
        {"type": "web_search_preview"},
        {"type": "file_search"},
    ]
    assert OpenAIResponses._has_file_search_tool(tools) is True


def test_has_file_search_tool_without_file_search():
    tools = [{"type": "web_search_preview"}]
    assert OpenAIResponses._has_file_search_tool(tools) is False


def test_has_file_search_tool_function_objects_only():
    """Function objects never represent file_search, should return False."""
    fn = Function(name="my_func", description="test")
    assert OpenAIResponses._has_file_search_tool([fn]) is False


def test_has_file_search_tool_mixed_function_and_dict():
    fn = Function(name="my_func", description="test")
    tools = [fn, {"type": "web_search_preview"}]
    assert OpenAIResponses._has_file_search_tool(tools) is False


# ---------------------------------------------------------------------------
# _format_file_for_input tests
# ---------------------------------------------------------------------------


def test_format_file_url():
    """URL files should produce a file_url block without filename."""
    file = File(url="https://example.com/report.pdf")
    result = OpenAIResponses._format_file_for_input(file)

    assert result is not None
    assert result["type"] == "input_file"
    assert result["file_url"] == "https://example.com/report.pdf"
    assert "filename" not in result
    assert "file_data" not in result
    assert "file_id" not in result


def test_format_file_filepath():
    """Local files should produce a file_data block with base64 data URI."""
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
        f.write("test content")
        tmp_path = f.name

    try:
        file = File(filepath=tmp_path, mime_type="text/plain")
        result = OpenAIResponses._format_file_for_input(file)

        assert result is not None
        assert result["type"] == "input_file"
        assert result["file_data"].startswith("data:text/plain;base64,")
        assert result["filename"] == Path(tmp_path).name
        assert "file_url" not in result
        assert "file_id" not in result

        # Verify base64 content decodes correctly
        b64_part = result["file_data"].split(",", 1)[1]
        decoded = base64.b64decode(b64_part).decode("utf-8")
        assert decoded == "test content"
    finally:
        Path(tmp_path).unlink()


def test_format_file_content_bytes():
    """Raw bytes content should produce a file_data block."""
    file = File(content=b"hello world", mime_type="text/plain", filename="greeting.txt")
    result = OpenAIResponses._format_file_for_input(file)

    assert result is not None
    assert result["type"] == "input_file"
    assert result["file_data"].startswith("data:text/plain;base64,")
    assert result["filename"] == "greeting.txt"


def test_format_file_id():
    """OpenAI file IDs should produce a file_id block."""
    file = File(id="file-abc123")
    result = OpenAIResponses._format_file_for_input(file)

    assert result is not None
    assert result["type"] == "input_file"
    assert result["file_id"] == "file-abc123"
    assert "filename" not in result
    assert "file_data" not in result


def test_format_file_mime_type_guessed_from_filepath():
    """MIME type should be guessed from filepath when not explicitly set."""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
        f.write("a,b,c")
        tmp_path = f.name

    try:
        file = File(filepath=tmp_path)
        result = OpenAIResponses._format_file_for_input(file)

        assert result is not None
        assert "text/csv" in result["file_data"]
    finally:
        Path(tmp_path).unlink()


def test_format_file_mime_type_fallback():
    """Unknown extensions should fall back to application/octet-stream."""
    file = File(content=b"\x00\x01\x02", filename="data.qzx9")
    result = OpenAIResponses._format_file_for_input(file)

    assert result is not None
    assert "application/octet-stream" in result["file_data"]


def test_format_file_filename_resolution_order():
    """Filename should prefer file.filename > file.name > basename of filepath."""
    # filename takes priority
    file1 = File(content=b"x", filename="preferred.txt", name="fallback.txt", mime_type="text/plain")
    result1 = OpenAIResponses._format_file_for_input(file1)
    assert result1 is not None
    assert result1["filename"] == "preferred.txt"

    # name is next
    file2 = File(content=b"x", name="second.txt", mime_type="text/plain")
    result2 = OpenAIResponses._format_file_for_input(file2)
    assert result2 is not None
    assert result2["filename"] == "second.txt"


def test_format_file_default_filename():
    """When no filename info is available, default to 'document'."""
    file = File(content=b"x", mime_type="text/plain")
    result = OpenAIResponses._format_file_for_input(file)

    assert result is not None
    assert result["filename"] == "document"


def test_format_file_external_only_returns_none():
    """File with only external set should return None (not handled inline)."""

    class FakeExternal:
        pass

    file = File(external=FakeExternal())
    result = OpenAIResponses._format_file_for_input(file)
    assert result is None


# ---------------------------------------------------------------------------
# _format_messages file embedding integration tests
# ---------------------------------------------------------------------------


def test_format_messages_embeds_files_without_file_search():
    """Files should be embedded inline when no file_search tool is present."""
    model = OpenAIResponses(id="gpt-4o")
    msg = Message(role="user", content="Summarize this")
    msg.files = [File(url="https://example.com/doc.pdf")]

    formatted = model._format_messages([msg], tools=[{"type": "web_search_preview"}])

    user_msgs = [m for m in formatted if isinstance(m, dict) and m.get("role") == "user"]
    assert len(user_msgs) == 1

    content = user_msgs[0]["content"]
    assert isinstance(content, list)
    assert len(content) == 2

    text_block = content[0]
    assert text_block["type"] == "input_text"
    assert text_block["text"] == "Summarize this"

    file_block = content[1]
    assert file_block["type"] == "input_file"
    assert file_block["file_url"] == "https://example.com/doc.pdf"


def test_format_messages_skips_files_with_file_search():
    """Files should NOT be embedded inline when file_search tool is present."""
    model = OpenAIResponses(id="gpt-4o")
    msg = Message(role="user", content="Summarize this")
    msg.files = [File(url="https://example.com/doc.pdf")]

    formatted = model._format_messages([msg], tools=[{"type": "file_search"}])

    user_msgs = [m for m in formatted if isinstance(m, dict) and m.get("role") == "user"]
    assert len(user_msgs) == 1

    # Content should remain a plain string, not a list with input_file blocks
    content = user_msgs[0]["content"]
    assert isinstance(content, str)


def test_format_messages_embeds_files_no_tools():
    """Files should be embedded inline when tools is None."""
    model = OpenAIResponses(id="gpt-4o")
    msg = Message(role="user", content="Read this")
    msg.files = [File(url="https://example.com/file.txt")]

    formatted = model._format_messages([msg])

    user_msgs = [m for m in formatted if isinstance(m, dict) and m.get("role") == "user"]
    content = user_msgs[0]["content"]
    assert isinstance(content, list)
    assert any(c.get("type") == "input_file" for c in content)


def test_format_messages_mixed_images_and_files():
    """Both images and files should coexist in the content array."""
    from agno.media import Image

    model = OpenAIResponses(id="gpt-4o")
    msg = Message(role="user", content="Analyze these")
    msg.images = [Image(url="https://example.com/photo.png")]
    msg.files = [File(url="https://example.com/data.csv")]

    formatted = model._format_messages([msg])

    user_msgs = [m for m in formatted if isinstance(m, dict) and m.get("role") == "user"]
    content = user_msgs[0]["content"]
    assert isinstance(content, list)

    types = [c.get("type") for c in content]
    assert "input_text" in types
    assert "input_file" in types


def test_format_messages_multiple_files():
    """Multiple files should each get their own input_file block."""
    model = OpenAIResponses(id="gpt-4o")
    msg = Message(role="user", content="Compare these")
    msg.files = [
        File(url="https://example.com/a.pdf"),
        File(url="https://example.com/b.pdf"),
    ]

    formatted = model._format_messages([msg])

    user_msgs = [m for m in formatted if isinstance(m, dict) and m.get("role") == "user"]
    content = user_msgs[0]["content"]
    assert isinstance(content, list)

    file_blocks = [c for c in content if c.get("type") == "input_file"]
    assert len(file_blocks) == 2


def test_format_messages_system_message_with_files():
    """System messages with files should also get input_file blocks."""
    model = OpenAIResponses(id="gpt-4o")
    msg = Message(role="system", content="You have context")
    msg.files = [File(url="https://example.com/context.txt")]

    formatted = model._format_messages([msg])

    sys_msgs = [m for m in formatted if isinstance(m, dict) and m.get("role") in ("system", "developer")]
    content = sys_msgs[0]["content"]
    assert isinstance(content, list)
    assert any(c.get("type") == "input_file" for c in content)


def test_format_messages_no_files_unchanged():
    """Messages without files should not be affected by the new logic."""
    model = OpenAIResponses(id="gpt-4o")
    msg = Message(role="user", content="Hello")

    formatted = model._format_messages([msg])

    user_msgs = [m for m in formatted if isinstance(m, dict) and m.get("role") == "user"]
    assert user_msgs[0]["content"] == "Hello"
