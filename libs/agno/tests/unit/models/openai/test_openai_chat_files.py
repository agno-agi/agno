from agno.media import File
from agno.models.deepseek.deepseek import DeepSeek
from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat


def _file_only_message():
    return Message(
        role="user",
        content=None,
        files=[File(content=b"%PDF-1.4 test", filename="doc.pdf", mime_type="application/pdf")],
    )


def test_format_message_keeps_files_when_content_is_none():
    formatted = OpenAIChat(id="gpt-4o-mini")._format_message(_file_only_message())

    assert isinstance(formatted["content"], list)
    assert formatted["content"]
    assert any(part.get("type") == "file" for part in formatted["content"])


def test_format_message_still_uses_empty_string_when_no_files():
    formatted = OpenAIChat(id="gpt-4o-mini")._format_message(Message(role="user", content=None))

    assert formatted["content"] == ""


def test_deepseek_format_message_keeps_files_when_content_is_none():
    formatted = DeepSeek(id="deepseek-chat")._format_message(_file_only_message())

    assert isinstance(formatted["content"], list)
    assert formatted["content"]
    assert any(part.get("type") == "file" for part in formatted["content"])
