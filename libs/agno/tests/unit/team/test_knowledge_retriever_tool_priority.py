"""Tests for unified knowledge search tool registration on Team.

Regression test for https://github.com/agno-agi/agno/issues/6533
Same fix as Agent: all knowledge search goes through a single unified path
via get_relevant_docs_from_knowledge().
"""

from unittest.mock import MagicMock

from agno.models.base import Function
from agno.run.base import RunContext
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team.team import Team


class MockKnowledge:
    """Minimal mock that satisfies the knowledge protocol."""

    def __init__(self):
        self.max_results = 5
        self.vector_db = None


def _make_run_context():
    return RunContext(run_id="test-run", session_id="test-session")


def _make_session():
    return TeamSession(session_id="test-session")


def _make_run_response():
    return TeamRunOutput(run_id="test-run", session_id="test-session", team_id="test-team")


def _make_model():
    model = MagicMock()
    model.get_tools_for_api.return_value = []
    model.add_tool.return_value = None
    return model


def _get_knowledge_tools(tools):
    return [t for t in tools if isinstance(t, Function) and t.name == "search_knowledge_base"]


def test_team_tools_registers_search_tool_when_both_knowledge_and_retriever_set():
    """When both knowledge and knowledge_retriever are set, a search tool is registered."""
    from agno.team._tools import _determine_tools_for_model

    def custom_retriever(query, team=None, num_documents=None, **kwargs):
        return [{"content": "from retriever"}]

    team = Team(name="test-team", members=[])
    team.knowledge = MockKnowledge()  # type: ignore
    team.knowledge_retriever = custom_retriever  # type: ignore
    team.search_knowledge = True

    tools = _determine_tools_for_model(
        team=team,
        model=_make_model(),
        run_response=_make_run_response(),
        run_context=_make_run_context(),
        team_run_context={},
        session=_make_session(),
        async_mode=False,
    )

    knowledge_tools = _get_knowledge_tools(tools)
    assert len(knowledge_tools) == 1


def test_team_tools_registers_search_tool_when_only_knowledge_set():
    """When only knowledge is set (no retriever), a search tool is still registered."""
    from agno.team._tools import _determine_tools_for_model

    team = Team(name="test-team", members=[])
    team.knowledge = MockKnowledge()  # type: ignore
    team.knowledge_retriever = None
    team.search_knowledge = True

    tools = _determine_tools_for_model(
        team=team,
        model=_make_model(),
        run_response=_make_run_response(),
        run_context=_make_run_context(),
        team_run_context={},
        session=_make_session(),
        async_mode=False,
    )

    knowledge_tools = _get_knowledge_tools(tools)
    assert len(knowledge_tools) == 1


def test_team_tools_registers_search_tool_when_only_retriever_set():
    """When only knowledge_retriever is set (no knowledge), a search tool is registered."""
    from agno.team._tools import _determine_tools_for_model

    def custom_retriever(query, team=None, num_documents=None, **kwargs):
        return [{"content": "from retriever"}]

    team = Team(name="test-team", members=[])
    team.knowledge = None
    team.knowledge_retriever = custom_retriever  # type: ignore
    team.search_knowledge = True

    tools = _determine_tools_for_model(
        team=team,
        model=_make_model(),
        run_response=_make_run_response(),
        run_context=_make_run_context(),
        team_run_context={},
        session=_make_session(),
        async_mode=False,
    )

    knowledge_tools = _get_knowledge_tools(tools)
    assert len(knowledge_tools) == 1


def test_team_search_tool_invokes_custom_retriever_when_both_set():
    """End-to-end: when both knowledge and retriever are set, invoking the tool calls the retriever."""
    from agno.team._tools import _determine_tools_for_model

    retriever_mock = MagicMock(return_value=[{"content": "from team retriever"}])

    team = Team(name="test-team", members=[])
    team.knowledge = MockKnowledge()  # type: ignore
    team.knowledge_retriever = retriever_mock  # type: ignore
    team.search_knowledge = True

    tools = _determine_tools_for_model(
        team=team,
        model=_make_model(),
        run_response=_make_run_response(),
        run_context=_make_run_context(),
        team_run_context={},
        session=_make_session(),
        async_mode=False,
    )

    knowledge_tools = _get_knowledge_tools(tools)
    assert len(knowledge_tools) == 1

    result = knowledge_tools[0].entrypoint("test query")
    retriever_mock.assert_called_once()
    assert "from team retriever" in result
