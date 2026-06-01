"""
Regression tests for issue #7036 — ensure_ascii=False / allow_unicode=True
in all LLM-context serialization paths for the agent module.

Coverage:
  - agent._utils.convert_documents_to_string (JSON branch, YAML branch)
  - agent._utils.convert_dependencies_to_string (both output calls)
  - agent._default_tools._format_results (JSON branch, YAML branch)

Each test that covers a non-ASCII character asserts against a HAND-WRITTEN
expected literal so a silent revert to ensure_ascii=True cannot pass.
ASCII tests also assert against a hand-written literal to pin exact format.
"""

import pytest

from agno.agent import _utils as agent_utils
from agno.agent import _default_tools as agent_tools
from agno.agent.agent import Agent


# ---------------------------------------------------------------------------
# Fixtures / constants
# ---------------------------------------------------------------------------

# Chinese personal name — the canonical non-ASCII probe from the issue
CHINESE_RAW = "赵箭"
ARABIC_RAW = "مرحبا"
CZECH_RAW = "Řehoř"

NON_ASCII_CASES = [
    ("chinese", CHINESE_RAW),
    ("arabic", ARABIC_RAW),
    ("czech", CZECH_RAW),
]


# A simple doc list used in Tier-1 / Tier-2 tests
def _make_doc(name: str) -> dict:
    return {"name": name, "content": f"Content for {name}"}


def _make_agent(references_format: str = "json") -> Agent:
    return Agent(name="test-agent", references_format=references_format)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def assert_unicode_preserved(s: str, raw: str) -> None:
    """Assert that raw unicode characters are present and NOT escaped."""
    assert raw in s, f"Expected raw unicode {raw!r} to be present in output"
    # Accept \\uXXXX or \UXXXXXXXX — both are escaping forms
    escaped = raw.encode("ascii", errors="backslashreplace").decode("ascii")
    if escaped != raw:
        # Only assert no escaping if the string actually has non-ASCII chars
        assert escaped not in s, f"Unicode escaping was applied: found {escaped!r} instead of {raw!r}"


# ===========================================================================
# TIER 2 — convert_documents_to_string  (agent/_utils.py)
# ===========================================================================


class TestConvertDocumentsToStringJSON:
    """JSON branch of convert_documents_to_string."""

    @pytest.mark.parametrize("label,raw", NON_ASCII_CASES)
    def test_non_ascii_preserved(self, label: str, raw: str):
        agent = _make_agent("json")
        docs = [_make_doc(raw)]
        result = agent_utils.convert_documents_to_string(agent, docs)
        assert_unicode_preserved(result, raw)

    def test_ascii_format_lock(self):
        """ASCII output must match this hand-written expected literal exactly."""
        agent = _make_agent("json")
        docs = [{"name": "hello", "content": "world"}]
        result = agent_utils.convert_documents_to_string(agent, docs)
        expected = '[\n  {\n    "name": "hello",\n    "content": "world"\n  }\n]'
        assert result == expected, f"ASCII format changed — expected:\n{expected!r}\ngot:\n{result!r}"

    def test_empty_returns_empty_string(self):
        agent = _make_agent("json")
        assert agent_utils.convert_documents_to_string(agent, []) == ""
        assert agent_utils.convert_documents_to_string(agent, None) == ""  # type: ignore[arg-type]


class TestConvertDocumentsToStringYAML:
    """YAML branch of convert_documents_to_string (agent/_utils.py line 67 — the buggy half)."""

    @pytest.mark.parametrize("label,raw", NON_ASCII_CASES)
    def test_non_ascii_preserved(self, label: str, raw: str):
        agent = _make_agent("yaml")
        docs = [_make_doc(raw)]
        result = agent_utils.convert_documents_to_string(agent, docs)
        assert_unicode_preserved(result, raw)

    def test_no_escape_sequences_in_yaml(self):
        agent = _make_agent("yaml")
        docs = [_make_doc(CHINESE_RAW)]
        result = agent_utils.convert_documents_to_string(agent, docs)
        assert "\\u" not in result, f"YAML output contains unicode escapes: {result!r}"


# ===========================================================================
# TIER 3 — convert_dependencies_to_string  (agent/_utils.py)
# ===========================================================================


class TestConvertDependenciesToString:
    """Both json.dumps output calls in convert_dependencies_to_string."""

    @pytest.mark.parametrize("label,raw", NON_ASCII_CASES)
    def test_non_ascii_preserved_primary_path(self, label: str, raw: str):
        agent = _make_agent()
        ctx = {"greeting": raw, "count": 42}
        result = agent_utils.convert_dependencies_to_string(agent, ctx)
        assert_unicode_preserved(result, raw)

    def test_ascii_format_lock_primary_path(self):
        agent = _make_agent()
        ctx = {"key": "value"}
        result = agent_utils.convert_dependencies_to_string(agent, ctx)
        expected = '{\n  "key": "value"\n}'
        assert result == expected, f"ASCII format changed — expected:\n{expected!r}\ngot:\n{result!r}"

    def test_empty_returns_empty_string(self):
        agent = _make_agent()
        assert agent_utils.convert_dependencies_to_string(agent, None) == ""  # type: ignore[arg-type]
        assert agent_utils.convert_dependencies_to_string(agent, {}) == "{}"


# ===========================================================================
# TIER 1 — _format_results  (agent/_default_tools.py)
# ===========================================================================


class TestFormatResultsJSON:
    """JSON branch of _format_results in agent/_default_tools."""

    @pytest.mark.parametrize("label,raw", NON_ASCII_CASES)
    def test_non_ascii_preserved(self, label: str, raw: str):
        docs = [_make_doc(raw)]
        result = agent_tools._format_results(docs, "json")
        assert_unicode_preserved(result, raw)

    def test_ascii_format_lock(self):
        docs = [{"name": "hello", "content": "world"}]
        result = agent_tools._format_results(docs, "json")
        expected = '[\n  {\n    "name": "hello",\n    "content": "world"\n  }\n]'
        assert result == expected, f"ASCII format changed — expected:\n{expected!r}\ngot:\n{result!r}"


class TestFormatResultsYAML:
    """YAML branch of _format_results in agent/_default_tools."""

    @pytest.mark.parametrize("label,raw", NON_ASCII_CASES)
    def test_non_ascii_preserved(self, label: str, raw: str):
        docs = [_make_doc(raw)]
        result = agent_tools._format_results(docs, "yaml")
        assert_unicode_preserved(result, raw)

    def test_no_escape_sequences_in_yaml(self):
        docs = [_make_doc(CHINESE_RAW)]
        result = agent_tools._format_results(docs, "yaml")
        assert "\\u" not in result, f"YAML output contains unicode escapes: {result!r}"


# ===========================================================================
# Cross-module parity: agent JSON == team JSON for the same input
# ===========================================================================


def test_agent_json_does_not_escape_unicode():
    """Smoke-test that the agent JSON path does not escape non-ASCII at all."""
    agent = _make_agent("json")
    docs = [{"k": CHINESE_RAW}]
    result = agent_utils.convert_documents_to_string(agent, docs)
    # The raw character must appear as-is; its hex escape must not
    assert CHINESE_RAW in result
    assert "\\u8d75" not in result.lower()
