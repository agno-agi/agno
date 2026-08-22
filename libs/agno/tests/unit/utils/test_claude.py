import base64

import pytest

from agno.media import File
from agno.utils.models.claude import _format_file_for_message, _validate_request_cache_order


class TestFormatFileForMessage:
    def test_filepath_text_csv_returns_text_source(self, tmp_path):
        csv_content = "name,age\nAlice,30\nBob,25"
        p = tmp_path / "data.csv"
        p.write_text(csv_content)

        result = _format_file_for_message(File(filepath=str(p), mime_type="text/csv"))

        assert result["type"] == "document"
        assert result["source"]["type"] == "text"
        # Anthropic's text document source only accepts "text/plain" as the media_type.
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
        [
            "text/plain",
            "text/html",
            "text/xml",
            "text/javascript",
            "text/markdown",
            "text/csv",
            "application/json",
            "application/x-python",
        ],
    )
    def test_all_text_mimes_route_to_text_source(self, mime_type):
        raw = b"some text content"

        result = _format_file_for_message(File(content=raw, mime_type=mime_type))

        assert result["source"]["type"] == "text"
        # Regardless of the original text subtype, Anthropic only accepts "text/plain"
        # for a text document source, so all of these must be normalised to it.
        assert result["source"]["media_type"] == "text/plain"

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


class TestValidateRequestCacheOrder:
    def test_no_tools_no_error(self):
        system = [{"text": "test", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
        _validate_request_cache_order(tools=None, system=system)

    def test_no_system_no_error(self):
        tools = [{"name": "test", "cache_control": {"type": "ephemeral", "ttl": "5m"}}]
        _validate_request_cache_order(tools=tools, system=None)

    def test_no_cached_tools_no_error(self):
        tools = [{"name": "test"}]
        system = [{"text": "test", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
        _validate_request_cache_order(tools=tools, system=system)

    def test_5m_tools_with_5m_system_no_error(self):
        tools = [{"name": "test", "cache_control": {"type": "ephemeral", "ttl": "5m"}}]
        system = [{"text": "test", "cache_control": {"type": "ephemeral", "ttl": "5m"}}]
        _validate_request_cache_order(tools=tools, system=system)

    def test_1h_tools_with_1h_system_no_error(self):
        tools = [{"name": "test", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
        system = [{"text": "test", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
        _validate_request_cache_order(tools=tools, system=system)

    def test_5m_tools_with_no_cached_system_no_error(self):
        tools = [{"name": "test", "cache_control": {"type": "ephemeral", "ttl": "5m"}}]
        system = [{"text": "test"}]
        _validate_request_cache_order(tools=tools, system=system)

    def test_5m_tools_with_1h_system_raises_error(self):
        tools = [{"name": "test", "cache_control": {"type": "ephemeral", "ttl": "5m"}}]
        system = [{"text": "test", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]

        with pytest.raises(ValueError, match="Invalid Anthropic cache TTL ordering"):
            _validate_request_cache_order(tools=tools, system=system)

    def test_error_message_includes_fix_suggestions(self):
        tools = [{"name": "test", "cache_control": {"type": "ephemeral", "ttl": "5m"}}]
        system = [{"text": "test", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]

        with pytest.raises(ValueError) as exc_info:
            _validate_request_cache_order(tools=tools, system=system)

        error_msg = str(exc_info.value)
        assert "cache_tools=False" in error_msg
        assert "ttl to '5m' or None" in error_msg
        assert "extended_cache_time=True AND cache_tools=False" in error_msg

    def test_multiple_tools_last_one_cached_5m(self):
        tools = [
            {"name": "tool1"},
            {"name": "tool2"},
            {"name": "tool3", "cache_control": {"type": "ephemeral", "ttl": "5m"}},
        ]
        system = [{"text": "test", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]

        with pytest.raises(ValueError, match="Invalid Anthropic cache TTL ordering"):
            _validate_request_cache_order(tools=tools, system=system)

    def test_multiple_system_blocks_first_one_1h(self):
        tools = [{"name": "test", "cache_control": {"type": "ephemeral", "ttl": "5m"}}]
        system = [
            {"text": "block1", "cache_control": {"type": "ephemeral", "ttl": "1h"}},
            {"text": "block2"},
        ]

        with pytest.raises(ValueError, match="Invalid Anthropic cache TTL ordering"):
            _validate_request_cache_order(tools=tools, system=system)

    def test_default_5m_cache_detected(self):
        tools = [{"name": "test", "cache_control": {"type": "ephemeral"}}]
        system = [{"text": "test", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]

        with pytest.raises(ValueError, match="Invalid Anthropic cache TTL ordering"):
            _validate_request_cache_order(tools=tools, system=system)
