"""
Tests for Claude document-citation suppression.

Anthropic rejects ``citations`` + ``output_format`` with a 400. When a Claude
request will send ``output_format`` (structured output on a supporting model),
every document block must have its ``citations`` field stripped.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from pydantic import BaseModel

from agno.media import File
from agno.models.anthropic.claude import Claude
from agno.models.message import Message
from agno.utils.models.claude import format_messages


class _Schema(BaseModel):
    answer: str


class TestOutputFormatEnabled:
    def test_none_response_format_returns_false(self):
        m = Claude(id="claude-sonnet-4-5")
        assert m._output_format_enabled(None) is False

    def test_pydantic_schema_on_supporting_model_returns_true(self):
        m = Claude(id="claude-sonnet-4-5")
        assert m.supports_native_structured_outputs is True
        assert m._output_format_enabled(_Schema) is True

    def test_pydantic_schema_on_legacy_model_returns_false(self):
        """Legacy Claude without native structured output never sends output_format,
        so citations stay on."""
        m = Claude(id="claude-3-haiku-20240307")
        m.supports_native_structured_outputs = False
        assert m._output_format_enabled(_Schema) is False

    def test_json_object_dict_returns_false(self):
        """Regression: response_format={'type': 'json_object'} does NOT produce an
        output_format param, so citations must not be suppressed for it."""
        m = Claude(id="claude-sonnet-4-5")
        assert m._output_format_enabled({"type": "json_object"}) is False

    def test_dict_schema_on_supporting_model_returns_true(self):
        m = Claude(id="claude-sonnet-4-5")
        schema_dict = {
            "type": "json_schema",
            "json_schema": {"name": "x", "schema": {"type": "object"}},
        }
        assert m._output_format_enabled(schema_dict) is True

    def test_agrees_with_build_output_format(self):
        """The two predicates must never disagree — their divergence was the bug."""
        m = Claude(id="claude-sonnet-4-5")
        inputs = [
            None,
            _Schema,
            {"type": "json_object"},
            {"type": "json_schema", "json_schema": {"name": "x", "schema": {"type": "object"}}},
        ]
        for rf in inputs:
            assert m._output_format_enabled(rf) is (m._build_output_format(rf) is not None)


class TestFormatMessagesPayloadOmitsCitations:
    def _user_with_pdf(self) -> Message:
        return Message(role="user", content="Summarize", files=[File(content=b"%PDF-1.4", mime_type="application/pdf")])

    def test_citations_present_by_default(self):
        chat_messages, _ = format_messages([self._user_with_pdf()])
        doc_blocks = [b for b in chat_messages[0]["content"] if isinstance(b, dict) and b.get("type") == "document"]
        assert doc_blocks and doc_blocks[0]["citations"] == {"enabled": True}

    def test_citations_absent_when_caller_disables(self):
        chat_messages, _ = format_messages([self._user_with_pdf()], enable_citations=False)
        doc_blocks = [b for b in chat_messages[0]["content"] if isinstance(b, dict) and b.get("type") == "document"]
        assert doc_blocks and "citations" not in doc_blocks[0]

    def test_file_citations_true_cannot_reintroduce_400(self):
        """Safety net for the original footgun: even if a user sets File.citations=True,
        a structured-output request must not end up with citations in the payload."""
        msg = Message(
            role="user",
            content="Summarize",
            files=[File(content=b"%PDF-1.4", mime_type="application/pdf", citations=True)],
        )
        chat_messages, _ = format_messages([msg], enable_citations=False)
        doc_blocks = [b for b in chat_messages[0]["content"] if isinstance(b, dict) and b.get("type") == "document"]
        assert doc_blocks and "citations" not in doc_blocks[0]

    def test_url_file_default_has_citations(self):
        """Regression guard: the URL branch conditionally attaches citations — an
        indentation slip there would silently drop them from URL files."""
        msg = Message(role="user", content="Summarize", files=[File(url="https://example.com/doc.pdf")])
        chat_messages, _ = format_messages([msg])
        doc_blocks = [b for b in chat_messages[0]["content"] if isinstance(b, dict) and b.get("type") == "document"]
        assert doc_blocks and doc_blocks[0]["citations"] == {"enabled": True}


class TestClaudeInvokeOmitsCitationsUnderStructuredOutput:
    """Integration-style seam test: patch the Anthropic client and assert the outbound
    payload omits citations when ``response_format`` is set. Guards against any of the
    six ``format_messages`` call sites drifting back to the default."""

    def _mock_claude(self, monkeypatch):
        # ``beta.messages.create`` returns a minimal object that ``_parse_provider_response``
        # can consume without blowing up. We only care about what we *sent*, not the reply.
        create_mock = MagicMock(
            return_value=SimpleNamespace(
                content=[SimpleNamespace(type="text", text='{"answer": "ok"}', citations=None)],
                stop_reason="end_turn",
                usage=SimpleNamespace(
                    input_tokens=1,
                    output_tokens=1,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=0,
                ),
                id="msg_123",
                model="claude-sonnet-4-5",
                role="assistant",
            )
        )
        model = Claude(id="claude-sonnet-4-5")
        client = MagicMock()
        client.beta.messages.create = create_mock
        client.messages.create = create_mock
        monkeypatch.setattr(model, "get_client", lambda: client)
        return model, create_mock

    def test_invoke_with_response_format_and_pdf_strips_citations(self, monkeypatch):
        model, create_mock = self._mock_claude(monkeypatch)

        user_msg = Message(
            role="user",
            content="Summarize",
            files=[File(content=b"%PDF-1.4", mime_type="application/pdf")],
        )
        assistant_msg = Message(role="assistant")

        try:
            model.invoke(messages=[user_msg], assistant_message=assistant_msg, response_format=_Schema)
        except Exception:
            # _parse_provider_response may still reject the stub — we only need the call to
            # have happened. Re-raise anything that isn't downstream of that.
            if not create_mock.called:
                raise

        assert create_mock.called, "Claude client was not invoked"
        sent_messages = create_mock.call_args.kwargs["messages"]
        doc_blocks = [
            b
            for m in sent_messages
            for b in (m.get("content") if isinstance(m.get("content"), list) else [])
            if isinstance(b, dict) and b.get("type") == "document"
        ]
        assert doc_blocks, "No document block found in the outbound payload"
        for block in doc_blocks:
            assert "citations" not in block, (
                "citations must be stripped when response_format is set — "
                "Anthropic rejects citations + output_format with a 400"
            )

    def test_invoke_without_response_format_keeps_citations(self, monkeypatch):
        model, create_mock = self._mock_claude(monkeypatch)

        user_msg = Message(
            role="user",
            content="Summarize",
            files=[File(content=b"%PDF-1.4", mime_type="application/pdf")],
        )
        assistant_msg = Message(role="assistant")

        try:
            model.invoke(messages=[user_msg], assistant_message=assistant_msg)
        except Exception:
            if not create_mock.called:
                raise

        assert create_mock.called
        sent_messages = create_mock.call_args.kwargs["messages"]
        doc_blocks = [
            b
            for m in sent_messages
            for b in (m.get("content") if isinstance(m.get("content"), list) else [])
            if isinstance(b, dict) and b.get("type") == "document"
        ]
        assert doc_blocks and doc_blocks[0]["citations"] == {"enabled": True}
