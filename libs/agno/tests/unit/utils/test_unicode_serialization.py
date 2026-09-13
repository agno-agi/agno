"""Regression tests for unicode preservation in context serialization (issue #7036).

Non-ASCII content (e.g. Chinese) must survive serialization into the LLM context
instead of being escaped to ``\\uXXXX`` sequences, which degrade model quality and
log readability. Covers the knowledge-references and dependencies formatters for
both Agent and Team, in json and yaml modes.
"""

from agno.agent import Agent
from agno.agent._default_tools import create_knowledge_search_tool
from agno.agent._run import save_run_response_to_file
from agno.agent._utils import convert_dependencies_to_string, convert_documents_to_string
from agno.run.agent import RunOutput
from agno.team._utils import _convert_dependencies_to_string, _convert_documents_to_string
from agno.utils.message import get_text_from_message
from agno.utils.prompts import get_json_output_prompt


class _FormatHolder:
    """Minimal stand-in exposing only the attribute the formatters read."""

    def __init__(self, references_format: str) -> None:
        self.references_format = references_format


DOCS = [{"name": "赵箭", "note": "café"}]
CONTEXT = {"作者": "赵箭", "city": "Köln"}


def test_agent_documents_unicode_preserved_json():
    result = convert_documents_to_string(_FormatHolder("json"), DOCS)
    assert "赵箭" in result
    assert "\\u" not in result


def test_agent_documents_unicode_preserved_yaml():
    result = convert_documents_to_string(_FormatHolder("yaml"), DOCS)
    assert "赵箭" in result
    assert "\\u" not in result


def test_team_documents_unicode_preserved_json():
    result = _convert_documents_to_string(_FormatHolder("json"), DOCS)
    assert "赵箭" in result
    assert "\\u" not in result


def test_team_documents_unicode_preserved_yaml():
    result = _convert_documents_to_string(_FormatHolder("yaml"), DOCS)
    assert "赵箭" in result
    assert "\\u" not in result


def test_agent_dependencies_unicode_preserved():
    result = convert_dependencies_to_string(_FormatHolder("json"), CONTEXT)
    assert "赵箭" in result
    assert "作者" in result
    assert "\\u" not in result


def test_team_dependencies_unicode_preserved():
    result = _convert_dependencies_to_string(_FormatHolder("json"), CONTEXT)
    assert "赵箭" in result
    assert "作者" in result
    assert "\\u" not in result


def test_json_output_prompt_unicode_preserved():
    result = get_json_output_prompt({"作者": "赵箭"})
    assert "赵箭" in result
    assert "\\u" not in result


def test_get_text_from_message_unicode_preserved():
    result = get_text_from_message({"名字": "赵箭"})
    assert "赵箭" in result
    assert "\\u" not in result


def _retriever(query=None, num_documents=None, **kwargs):
    return [{"name": "赵箭", "fact": "赵箭 是一名工程师"}]


def test_knowledge_search_tool_format_results_json():
    """The literal issue-#7036 path: the knowledge-search tool result (json mode)."""
    agent = Agent()
    agent.knowledge_retriever = _retriever  # type: ignore
    agent.references_format = "json"
    result = create_knowledge_search_tool(agent).entrypoint(query="anything")
    assert "赵箭" in result
    assert "\\u" not in result


def test_knowledge_search_tool_format_results_yaml():
    """The knowledge-search tool result in yaml mode."""
    agent = Agent()
    agent.knowledge_retriever = _retriever  # type: ignore
    agent.references_format = "yaml"
    result = create_knowledge_search_tool(agent).entrypoint(query="anything")
    assert "赵箭" in result
    assert "\\u" not in result


def test_save_run_response_to_file_unicode_and_encoding(tmp_path):
    """Regression guard for the file-write path: raw unicode is written and the file
    is UTF-8 encoded (the encoding="utf-8" addition that prevents a UnicodeEncodeError
    crash on non-UTF-8 locales)."""
    out = tmp_path / "out.json"
    agent = Agent()
    agent.save_response_to_file = str(out)  # type: ignore
    save_run_response_to_file(agent, RunOutput(content={"name": "赵箭", "role": "工程师"}, run_id="r1"), input="x")
    saved = out.read_text(encoding="utf-8")
    assert "赵箭" in saved
    assert "\\u" not in saved
    # Bytes on disk are valid UTF-8 (would raise if written under a non-UTF-8 codec).
    out.read_bytes().decode("utf-8")
