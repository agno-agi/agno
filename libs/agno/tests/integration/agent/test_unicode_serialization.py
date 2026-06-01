"""
Integration tests for issue #7036 — Unicode preservation end-to-end
through the agent message-construction pipeline.

These tests exercise the FULL stack from Agent configuration down to the
Message objects that would be sent to the model, without requiring a live
LLM API key.  They complement the unit tests in tests/unit by verifying
the serialized strings actually reach the prompt via the real code paths
(get_user_message, get_run_messages).

Convention: mirrors tests/integration/agent/test_dependencies.py — real
Agent objects and real session/run-context objects; inspects constructed
Message content for correctness.
"""

import json

import pytest

from agno.agent._messages import get_run_messages, get_user_message
from agno.agent.agent import Agent
from agno.run.agent import RunOutput
from agno.run.base import RunContext
from agno.session.agent import AgentSession

# ---------------------------------------------------------------------------
# Non-ASCII probes — same characters used in unit tests (cross-layer parity)
# ---------------------------------------------------------------------------
CHINESE = "赵箭"
ARABIC = "مرحبا"
CZECH = "Řehoř"

NON_ASCII_CASES = [("chinese", CHINESE), ("arabic", ARABIC), ("czech", CZECH)]


# ---------------------------------------------------------------------------
# Helpers — no model required for message-construction tests
# ---------------------------------------------------------------------------


def _make_agent(**kwargs) -> Agent:
    """Agent with static system_message so get_run_messages works without a real model."""
    kwargs.setdefault("system_message", "You are a helpful assistant.")
    """Agent without a model — sufficient for all message-construction tests."""
    return Agent(**kwargs)


def _make_session(agent: Agent) -> AgentSession:
    agent.set_id()
    return AgentSession(session_id="test-session", agent_id=agent.id or "agent-1")


def _make_run_response(agent: Agent) -> RunOutput:
    return RunOutput(run_id="test-run-id", session_id="test-session", agent_id=agent.id or "agent-1")


def _make_run_context(**kwargs) -> RunContext:
    return RunContext(run_id="test-run-id", session_id="test-session", **kwargs)


def _content(msg) -> str:
    return msg.content if isinstance(msg.content, str) else str(msg.content)


def _assert_unicode_preserved(text: str, raw: str) -> None:
    assert raw in text, f"Raw Unicode {raw!r} missing from message content"
    escaped = raw.encode("ascii", errors="backslashreplace").decode("ascii")
    if escaped != raw:
        assert escaped not in text, f"Unicode escaped in message: found {escaped!r} instead of {raw!r}"


# ===========================================================================
# 1. dependencies → user message  (Tier 3: convert_dependencies_to_string)
#    Mirrors: test_dependencies.py::test_add_dependencies_to_context
# ===========================================================================


class TestDependenciesUnicodeInUserMessage:
    """Serialized context dict injected via add_dependencies_to_context must
    preserve raw Unicode — not \\uXXXX escapes."""

    @pytest.mark.parametrize("label,raw", NON_ASCII_CASES)
    def test_unicode_value_not_escaped(self, label: str, raw: str):
        agent = _make_agent(add_dependencies_to_context=True)
        run_context = _make_run_context(dependencies={"greeting": raw})
        msg = get_user_message(
            agent,
            input="Hello",
            session=_make_session(agent),
            run_response=_make_run_response(agent),
            run_context=run_context,
            add_dependencies_to_context=True,
        )
        assert msg is not None
        _assert_unicode_preserved(_content(msg), raw)

    def test_ascii_format_unchanged(self):
        """ASCII dependencies must appear with the exact JSON format (indent=2)."""
        agent = _make_agent(add_dependencies_to_context=True)
        run_context = _make_run_context(dependencies={"robot_name": "Anna"})
        msg = get_user_message(
            agent,
            input="Hello",
            session=_make_session(agent),
            run_response=_make_run_response(agent),
            run_context=run_context,
            add_dependencies_to_context=True,
        )
        expected = json.dumps({"robot_name": "Anna"}, indent=2, default=str, ensure_ascii=False)
        assert expected in _content(msg), f"Expected {expected!r} in message"

    @pytest.mark.parametrize("label,raw", NON_ASCII_CASES)
    def test_unicode_and_ascii_mixed_context(self, label: str, raw: str):
        ctx = {"name": raw, "score": 42, "tag": "ok"}
        agent = _make_agent(add_dependencies_to_context=True)
        run_context = _make_run_context(dependencies=ctx)
        msg = get_user_message(
            agent,
            input="Hi",
            session=_make_session(agent),
            run_response=_make_run_response(agent),
            run_context=run_context,
            add_dependencies_to_context=True,
        )
        _assert_unicode_preserved(_content(msg), raw)
        assert "42" in _content(msg)  # ASCII numbers intact


# ===========================================================================
# 2. knowledge references → user message  (Tier 2: convert_documents_to_string)
#    Mirrors: test_custom_retriever.py::test_agent_with_custom_knowledge_retriever
# ===========================================================================


class TestKnowledgeReferencesUnicodeInUserMessage:
    """References from a knowledge_retriever that contain non-ASCII content
    must appear as raw Unicode in the constructed user message."""

    def _agent(self, docs: list, fmt: str = "json") -> Agent:
        def _retriever(**kwargs):
            return docs

        return _make_agent(
            knowledge_retriever=_retriever,  # type: ignore[arg-type]
            add_knowledge_to_context=True,
            references_format=fmt,
        )

    @pytest.mark.parametrize("label,raw", NON_ASCII_CASES)
    def test_json_references_not_escaped(self, label: str, raw: str):
        agent = self._agent([{"title": raw, "body": f"About {raw}"}], "json")
        msg = get_user_message(
            agent,
            input="What do you know?",
            session=_make_session(agent),
            run_response=_make_run_response(agent),
            run_context=_make_run_context(),
        )
        assert msg is not None
        _assert_unicode_preserved(_content(msg), raw)

    @pytest.mark.parametrize("label,raw", NON_ASCII_CASES)
    def test_yaml_references_not_escaped(self, label: str, raw: str):
        agent = self._agent([{"title": raw, "body": f"About {raw}"}], "yaml")
        msg = get_user_message(
            agent,
            input="What do you know?",
            session=_make_session(agent),
            run_response=_make_run_response(agent),
            run_context=_make_run_context(),
        )
        assert msg is not None
        _assert_unicode_preserved(_content(msg), raw)
        assert "\\u" not in _content(msg), "YAML references contain \\u escapes"

    def test_ascii_references_format_stable(self):
        agent = self._agent([{"city": "Paris", "fact": "Capital of France"}], "json")
        msg = get_user_message(
            agent,
            input="Tell me about Paris",
            session=_make_session(agent),
            run_response=_make_run_response(agent),
            run_context=_make_run_context(),
        )
        assert msg is not None
        assert "Paris" in _content(msg)
        assert "Capital of France" in _content(msg)

    @pytest.mark.parametrize("label,raw", NON_ASCII_CASES)
    def test_multiple_docs_all_preserved(self, label: str, raw: str):
        docs = [{"item": raw}, {"item": "ascii-only"}]
        agent = self._agent(docs, "json")
        msg = get_user_message(
            agent,
            input="List all items",
            session=_make_session(agent),
            run_response=_make_run_response(agent),
            run_context=_make_run_context(),
        )
        assert msg is not None
        _assert_unicode_preserved(_content(msg), raw)
        assert "ascii-only" in _content(msg)


# ===========================================================================
# 3. Full get_run_messages pipeline
#    Confirms Unicode survives the complete system+user message construction.
# ===========================================================================


class TestRunMessagesPipelineUnicode:
    """End-to-end: build full RunMessages and verify Unicode is intact in
    every message that would be sent to the model."""

    def _all_content(self, run_messages) -> str:
        return " ".join((_content(m)) for m in run_messages.messages if m.content)

    def test_chinese_knowledge_json_survives_pipeline(self):
        doc = {"name": CHINESE, "description": f"Expert on {CHINESE}"}

        def _retriever(**kwargs):
            return [doc]

        agent = _make_agent(
            knowledge_retriever=_retriever,  # type: ignore[arg-type]
            add_knowledge_to_context=True,
            references_format="json",
        )
        msgs = get_run_messages(
            agent,
            run_response=_make_run_response(agent),
            run_context=_make_run_context(),
            input="Tell me about the expert",
            session=_make_session(agent),
        )
        all_text = self._all_content(msgs)
        assert CHINESE in all_text, "Chinese stripped from run messages"
        assert "\\u8d75" not in all_text.lower(), "Chinese ASCII-escaped in run messages"

    def test_arabic_dependency_survives_pipeline(self):
        agent = _make_agent(add_dependencies_to_context=True)
        msgs = get_run_messages(
            agent,
            run_response=_make_run_response(agent),
            run_context=_make_run_context(dependencies={"user": ARABIC}),
            input="Hello",
            session=_make_session(agent),
            add_dependencies_to_context=True,
        )
        assert ARABIC in self._all_content(msgs), "Arabic stripped from run messages"

    def test_czech_yaml_references_survive_pipeline(self):
        def _retriever(**kwargs):
            return [{"author": CZECH}]

        agent = _make_agent(
            knowledge_retriever=_retriever,  # type: ignore[arg-type]
            add_knowledge_to_context=True,
            references_format="yaml",
        )
        msgs = get_run_messages(
            agent,
            run_response=_make_run_response(agent),
            run_context=_make_run_context(),
            input="Who wrote this?",
            session=_make_session(agent),
        )
        all_text = self._all_content(msgs)
        assert CZECH in all_text, "Czech stripped from YAML run messages"
        assert "\\u" not in all_text, "YAML path produced \\u escapes in run messages"

    @pytest.mark.parametrize("label,raw", NON_ASCII_CASES)
    def test_all_scripts_survive_json_pipeline(self, label: str, raw: str):
        def _retriever(**kwargs):
            return [{"content": raw}]

        agent = _make_agent(
            knowledge_retriever=_retriever,  # type: ignore[arg-type]
            add_knowledge_to_context=True,
            references_format="json",
        )
        msgs = get_run_messages(
            agent,
            run_response=_make_run_response(agent),
            run_context=_make_run_context(),
            input="What is this?",
            session=_make_session(agent),
        )
        _assert_unicode_preserved(self._all_content(msgs), raw)
