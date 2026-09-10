"""Real agent tool execution with scripted responses and fixture evidence."""

import importlib
import sys

import pytest
from agno.run import RunContext


def test_inspected_citations_and_persistence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RESEARCH_MODE", "fixture")
    sys.modules.pop("research_agent", None)
    module = importlib.import_module("research_agent")
    from fixture_model import fixture_model

    module.agent.model = fixture_model()
    result = module.agent.run(
        "Should a library pilot a repair cafe?", user_id="alice", session_id="research"
    )
    assert isinstance(result.content, module.ResearchBrief)
    urls = {url for finding in result.content.findings for url in finding.sources}
    assert urls == set(result.session_state["inspected"])
    assert {tool.tool_name for tool in result.tools} == {
        "search_sources",
        "read_source",
    }
    saved = module.agent.get_session(session_id="research")
    assert saved.runs[0].content == result.content.model_dump()
    context = RunContext(run_id="r", session_id="s", session_state={})
    with pytest.raises(ValueError, match="Search"):
        module.read_source("https://unread.example", context)
