import base64

import pytest

from agno.media import File, Image
from agno.models.message import Message
from agno.utils.models.claude import _format_file_for_message, format_messages


class TestFormatFileForMessage:
    def test_filepath_text_csv_returns_text_source(self, tmp_path):
        csv_content = "name,age\nAlice,30\nBob,25"
        p = tmp_path / "data.csv"
        p.write_text(csv_content)

        result = _format_file_for_message(File(filepath=str(p), mime_type="text/csv"))

        assert result["type"] == "document"
        assert result["source"]["type"] == "text"
        assert result["source"]["media_type"] == "text/csv"
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
        assert result["source"]["media_type"] == "text/csv"
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
        assert result["source"]["media_type"] == mime_type

    def test_text_data_is_not_base64_encoded(self, tmp_path):
        """Regression: old code base64-encoded before checking MIME, sending gibberish as text."""
        csv_content = "name,value\ntest,123"
        p = tmp_path / "test.csv"
        p.write_text(csv_content)

        result = _format_file_for_message(File(filepath=str(p), mime_type="text/csv"))

        assert result["source"]["data"] == csv_content
        assert result["source"]["data"] != base64.standard_b64encode(csv_content.encode()).decode()


    def test_enable_citations_false_omits_citations_block(self, tmp_path):
        """Anthropic rejects citations + output_format; caller must be able to suppress."""
        p = tmp_path / "doc.pdf"
        p.write_bytes(b"%PDF-1.4 fake")

        result = _format_file_for_message(File(filepath=str(p), mime_type="application/pdf"), enable_citations=False)

        assert "citations" not in result

    def test_enable_citations_default_true_adds_citations_block(self, tmp_path):
        p = tmp_path / "doc.pdf"
        p.write_bytes(b"%PDF-1.4 fake")

        result = _format_file_for_message(File(filepath=str(p), mime_type="application/pdf"))

        assert result["citations"] == {"enabled": True}

    def test_file_citations_false_overrides_caller_default(self, tmp_path):
        """Per-file opt-out wins over the caller default."""
        p = tmp_path / "doc.pdf"
        p.write_bytes(b"%PDF-1.4 fake")

        result = _format_file_for_message(
            File(filepath=str(p), mime_type="application/pdf", citations=False),
            enable_citations=True,
        )

        assert "citations" not in result

    def test_caller_false_is_a_ceiling_even_when_file_requests_citations(self):
        """Safety: File(citations=True) must NOT re-enable citations when the caller
        has disabled them (e.g. structured output is active — re-enabling would
        reintroduce the very 400 this feature exists to prevent)."""
        result = _format_file_for_message(
            File(content=b"fake", mime_type="application/pdf", citations=True),
            enable_citations=False,
        )

        assert "citations" not in result

    def test_citations_not_attached_to_anthropic_uploaded_file(self):
        """Case 0 (external file) has never attached citations — regression guard."""

        class _Ext:
            id = "file_123"

        result = _format_file_for_message(File(external=_Ext()))

        assert "citations" not in result

    def test_url_source_citations_suppressed_when_disabled(self):
        result = _format_file_for_message(File(url="https://example.com/doc.pdf"), enable_citations=False)

        assert result["source"]["type"] == "url"
        assert "citations" not in result


class TestToolResultWithImages:
    def test_tool_result_with_images(self):
        """Tool message with images should produce content list with text + image blocks."""
        # Minimal 1x1 PNG
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
            b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
            b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        msgs = [
            Message(role="user", content="Describe this"),
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": "toolu_001",
                        "type": "function",
                        "function": {"name": "screenshot", "arguments": "{}"},
                    }
                ],
            ),
            Message(
                role="tool",
                tool_call_id="toolu_001",
                tool_name="screenshot",
                content="Screenshot taken",
                images=[Image(content=png_bytes, format="png")],
            ),
        ]
        formatted, _system = format_messages(msgs)

        # Tool result is the last (merged into user) message
        tool_result = formatted[2]["content"][0]
        assert tool_result["type"] == "tool_result"
        assert tool_result["tool_use_id"] == "toolu_001"

        # Content should be a list with text + image blocks
        content = tool_result["content"]
        assert isinstance(content, list)
        assert len(content) == 2
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "Screenshot taken"
        assert content[1]["type"] == "image"

    def test_tool_result_without_images_unchanged(self):
        """Tool message without images should produce str content (backward compat)."""
        msgs = [
            Message(role="user", content="Hello"),
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": "toolu_002",
                        "type": "function",
                        "function": {"name": "search", "arguments": "{}"},
                    }
                ],
            ),
            Message(
                role="tool",
                tool_call_id="toolu_002",
                tool_name="search",
                content="Result text",
            ),
        ]
        formatted, _system = format_messages(msgs)

        tool_result = formatted[2]["content"][0]
        assert tool_result["type"] == "tool_result"
        assert tool_result["content"] == "Result text"
