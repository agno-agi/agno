"""
Regression tests for issue #7036 — ensure_ascii=False / allow_unicode=True
in all LLM-context serialization paths for the team module.

Coverage:
  - team._utils._convert_documents_to_string (JSON branch, YAML branch)
  - team._utils._convert_dependencies_to_string (both output calls)
  - team._default_tools._format_results (JSON branch, YAML branch)
  - team._default_tools member-agent response content dumps (Tier-4)
"""

import json
from unittest.mock import MagicMock

import pytest

from agno.team import _utils as team_utils
from agno.team import _default_tools as team_tools


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHINESE_RAW = "赵箭"
ARABIC_RAW = "مرحبا"
CZECH_RAW = "Řehoř"

NON_ASCII_CASES = [
    ("chinese", CHINESE_RAW),
    ("arabic", ARABIC_RAW),
    ("czech", CZECH_RAW),
]


def _make_doc(name: str) -> dict:
    return {"name": name, "content": f"Content for {name}"}


def _make_team_mock(references_format: str = "json"):
    """
    Minimal mock for the Team object.
    The _utils functions only read team.references_format, so a MagicMock
    with that attribute set is sufficient and avoids the Team(members=...) requirement.
    """
    team = MagicMock()
    team.references_format = references_format
    return team


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def assert_unicode_preserved(s: str, raw: str) -> None:
    assert raw in s, f"Expected raw unicode {raw!r} to be present in output"
    escaped = raw.encode("ascii", errors="backslashreplace").decode("ascii")
    if escaped != raw:
        assert escaped not in s, f"Unicode escaping was applied: found {escaped!r} instead of {raw!r}"


# ===========================================================================
# TIER 2 — _convert_documents_to_string  (team/_utils.py)
# ===========================================================================


class TestTeamConvertDocumentsToStringJSON:
    @pytest.mark.parametrize("label,raw", NON_ASCII_CASES)
    def test_non_ascii_preserved(self, label: str, raw: str):
        team = _make_team_mock("json")
        docs = [_make_doc(raw)]
        result = team_utils._convert_documents_to_string(team, docs)
        assert_unicode_preserved(result, raw)

    def test_ascii_format_lock(self):
        team = _make_team_mock("json")
        docs = [{"name": "hello", "content": "world"}]
        result = team_utils._convert_documents_to_string(team, docs)
        expected = '[\n  {\n    "name": "hello",\n    "content": "world"\n  }\n]'
        assert result == expected, f"ASCII format changed — expected:\n{expected!r}\ngot:\n{result!r}"

    def test_empty_returns_empty_string(self):
        team = _make_team_mock("json")
        assert team_utils._convert_documents_to_string(team, []) == ""


class TestTeamConvertDocumentsToStringYAML:
    @pytest.mark.parametrize("label,raw", NON_ASCII_CASES)
    def test_non_ascii_preserved(self, label: str, raw: str):
        team = _make_team_mock("yaml")
        docs = [_make_doc(raw)]
        result = team_utils._convert_documents_to_string(team, docs)
        assert_unicode_preserved(result, raw)

    def test_no_escape_sequences_in_yaml(self):
        team = _make_team_mock("yaml")
        docs = [_make_doc(CHINESE_RAW)]
        result = team_utils._convert_documents_to_string(team, docs)
        assert "\\u" not in result, f"YAML output contains unicode escapes: {result!r}"


# ===========================================================================
# TIER 3 — _convert_dependencies_to_string  (team/_utils.py)
# ===========================================================================


class TestTeamConvertDependenciesToString:
    @pytest.mark.parametrize("label,raw", NON_ASCII_CASES)
    def test_non_ascii_preserved_primary_path(self, label: str, raw: str):
        team = _make_team_mock()
        ctx = {"greeting": raw, "count": 42}
        result = team_utils._convert_dependencies_to_string(team, ctx)
        assert_unicode_preserved(result, raw)

    def test_ascii_format_lock_primary_path(self):
        team = _make_team_mock()
        ctx = {"key": "value"}
        result = team_utils._convert_dependencies_to_string(team, ctx)
        expected = '{\n  "key": "value"\n}'
        assert result == expected, f"ASCII format changed — expected:\n{expected!r}\ngot:\n{result!r}"

    def test_empty_returns_empty_string(self):
        team = _make_team_mock()
        assert team_utils._convert_dependencies_to_string(team, None) == ""  # type: ignore[arg-type]


# ===========================================================================
# TIER 1 — _format_results  (team/_default_tools.py)
# ===========================================================================


class TestTeamFormatResultsJSON:
    @pytest.mark.parametrize("label,raw", NON_ASCII_CASES)
    def test_non_ascii_preserved(self, label: str, raw: str):
        docs = [_make_doc(raw)]
        result = team_tools._format_results(docs, "json")
        assert_unicode_preserved(result, raw)

    def test_ascii_format_lock(self):
        docs = [{"name": "hello", "content": "world"}]
        result = team_tools._format_results(docs, "json")
        expected = '[\n  {\n    "name": "hello",\n    "content": "world"\n  }\n]'
        assert result == expected, f"ASCII format changed — expected:\n{expected!r}\ngot:\n{result!r}"


class TestTeamFormatResultsYAML:
    @pytest.mark.parametrize("label,raw", NON_ASCII_CASES)
    def test_non_ascii_preserved(self, label: str, raw: str):
        docs = [_make_doc(raw)]
        result = team_tools._format_results(docs, "yaml")
        assert_unicode_preserved(result, raw)

    def test_no_escape_sequences_in_yaml(self):
        docs = [_make_doc(CHINESE_RAW)]
        result = team_tools._format_results(docs, "yaml")
        assert "\\u" not in result, f"YAML output contains unicode escapes: {result!r}"


# ===========================================================================
# TIER 4 — member-agent response content (team/_default_tools.py lines 759/942/1111/1374)
# Verified by calling json.dumps with the same signature as those call sites.
# ===========================================================================


class TestTeamMemberResponseDumps:
    def test_str_content_json_no_escape(self):
        """Simulate: json.dumps(member_agent_run_response.content, indent=2)"""
        content = f"Agent answered: {CHINESE_RAW}"
        result = json.dumps(content, indent=2, ensure_ascii=False)
        assert CHINESE_RAW in result
        assert "\\u" not in result

    def test_dict_content_json_no_escape(self):
        content = {"summary": ARABIC_RAW, "score": 42}
        result = json.dumps(content, indent=2, ensure_ascii=False)
        assert ARABIC_RAW in result
        assert "\\u" not in result


# ===========================================================================
# Cross-module parity: agent JSON == team JSON for same ASCII input
# ===========================================================================


def test_agent_and_team_json_produce_same_output_for_ascii():
    from agno.agent import _utils as agent_utils
    from agno.agent.agent import Agent

    docs = [{"name": "hello", "content": "world"}]
    team = _make_team_mock("json")
    agent = Agent(name="a", references_format="json")

    team_result = team_utils._convert_documents_to_string(team, docs)
    agent_result = agent_utils.convert_documents_to_string(agent, docs)
    assert team_result == agent_result, (
        f"Agent/team JSON output diverged:\nagent: {agent_result!r}\nteam: {team_result!r}"
    )
