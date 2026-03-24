import base64

import pytest

from agno.media import File
from agno.models.message import Message
from agno.utils.models.claude import _format_file_for_message, validate_messages_for_claude_model


class TestFormatFileForMessage:
    def test_filepath_text_csv_returns_text_source(self, tmp_path):
        csv_content = "name,age\nAlice,30\nBob,25"
        p = tmp_path / "data.csv"
        p.write_text(csv_content)

        result = _format_file_for_message(File(filepath=str(p), mime_type="text/csv"))

        assert result["type"] == "document"
        assert result["source"]["type"] == "text"
        assert result["source"]["media_type"] == "text/plain"
        assert result["source"]["data"] == csv_content
        assert result["citations"] == {"enabled": True}

    def test_filepath_pdf_returns_base64_source(self, tmp_path):
        pdf_bytes = b"%PDF-1.4 fake content"
        p = tmp_path / "doc.pdf"
        p.write_bytes(pdf_bytes)

        result = _format_file_for_message(File(filepath=str(p), mime_type="application/pdf"))

        assert result["type"] == "document"
        assert result["source"]["type"] == "base64"
        assert result["source"]["media_type"] == "application/pdf"
        assert base64.standard_b64decode(result["source"]["data"]) == pdf_bytes

    def test_bytes_content_text_mime_returns_text_source(self):
        raw = b"col1,col2\na,b"

        result = _format_file_for_message(File(content=raw, mime_type="text/csv"))

        assert result["source"]["type"] == "text"
        assert result["source"]["media_type"] == "text/plain"
        assert result["source"]["data"] == "col1,col2\na,b"

    def test_bytes_content_pdf_returns_base64_source(self):
        raw = b"fake-pdf-bytes"

        result = _format_file_for_message(File(content=raw, mime_type="application/pdf"))

        assert result["source"]["type"] == "base64"
        assert result["source"]["media_type"] == "application/pdf"
        assert base64.standard_b64decode(result["source"]["data"]) == raw

    def test_filepath_no_mime_guesses_from_extension(self, tmp_path):
        p = tmp_path / "report.csv"
        p.write_text("x,y\n1,2")

        result = _format_file_for_message(File(filepath=str(p)))

        assert result["source"]["type"] == "text"
        assert result["source"]["data"] == "x,y\n1,2"

    def test_filepath_nonexistent_returns_none(self):
        result = _format_file_for_message(File(filepath="/nonexistent/file.pdf", mime_type="application/pdf"))

        assert result is None

    @pytest.mark.parametrize(
        "mime_type",
        ["text/plain", "text/html", "text/xml", "text/javascript", "application/json", "application/x-python"],
    )
    def test_all_text_mimes_route_to_text_source(self, mime_type):
        raw = b"some text content"

        result = _format_file_for_message(File(content=raw, mime_type=mime_type))

        assert result["source"]["type"] == "text"
        assert result["source"]["media_type"] == "text/plain"

    def test_text_data_is_not_base64_encoded(self, tmp_path):
        """Regression: old code base64-encoded before checking MIME, sending gibberish as text."""
        csv_content = "name,value\ntest,123"
        p = tmp_path / "test.csv"
        p.write_text(csv_content)

        result = _format_file_for_message(File(filepath=str(p), mime_type="text/csv"))

        assert result["source"]["data"] == csv_content
        assert result["source"]["data"] != base64.standard_b64encode(csv_content.encode()).decode()


class TestValidateMessagesForClaudeModel:
    def test_raises_for_final_assistant_prefill_on_claude_46(self):
        messages = [
            Message(role="system", content="You return compact JSON."),
            Message(role="user", content="Classify the ticket."),
            Message(role="assistant", content='{"priority":'),
        ]

        with pytest.raises(ValueError, match="does not support assistant message prefills"):
            validate_messages_for_claude_model(messages, "claude-sonnet-4-6")

    def test_allows_final_assistant_prefill_for_claude_45(self):
        messages = [
            Message(role="user", content="Classify the ticket."),
            Message(role="assistant", content='{"priority":'),
        ]

        validate_messages_for_claude_model(messages, "claude-sonnet-4-5-20250929")

    def test_allows_valid_user_final_message_for_claude_46(self):
        messages = [
            Message(role="assistant", content="Previous answer."),
            Message(role="user", content="Please continue with more detail."),
        ]

        validate_messages_for_claude_model(messages, "claude-sonnet-4-6")

    def test_raises_for_non_text_final_assistant_message_on_claude_46(self):
        messages = [
            Message(
                role="assistant",
                tool_calls=[
                    {
                        "id": "tool_1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": "{}"},
                    }
                ],
            )
        ]

        with pytest.raises(ValueError, match="does not support assistant message prefills"):
            validate_messages_for_claude_model(messages, "claude-sonnet-4-6")
