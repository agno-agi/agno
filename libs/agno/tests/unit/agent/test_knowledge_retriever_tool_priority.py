"""Tests for unified knowledge search tool registration.

Regression test for https://github.com/agno-agi/agno/issues/6533
All knowledge search goes through a single unified path via
get_relevant_docs_from_knowledge(), which checks knowledge_retriever
first and falls back to knowledge.search().
"""

import pytest
from unittest.mock import MagicMock

from agno.agent import Agent
from agno.agent._tools import aget_tools, get_tools
from agno.models.base import Function
from agno.run.agent import RunOutput
from agno.run.base import RunContext
from agno.session.agent import AgentSession


class MockKnowledge:
    """Minimal mock that satisfies the knowledge protocol."""

    def __init__(self):
        self.max_results = 5
        self.vector_db = None


def _make_run_context():
    return RunContext(run_id="test-run", session_id="test-session")


def _make_session():
    return AgentSession(session_id="test-session")


def _make_run_response():
    return RunOutput(run_id="test-run", session_id="test-session", agent_id="test-agent")


def _get_knowledge_tools(tools):
    return [t for t in tools if isinstance(t, Function) and t.name == "search_knowledge_base"]


def test_get_tools_registers_search_tool_when_both_knowledge_and_retriever_set():
    """When both knowledge and knowledge_retriever are set, a search tool is registered."""

    def custom_retriever(query, agent=None, num_documents=None, **kwargs):
        return [{"content": "from retriever"}]

    agent = Agent()
    agent.knowledge = MockKnowledge()  # type: ignore
    agent.knowledge_retriever = custom_retriever  # type: ignore
    agent.search_knowledge = True

    tools = get_tools(agent, _make_run_response(), _make_run_context(), _make_session())

    knowledge_tools = _get_knowledge_tools(tools)
    assert len(knowledge_tools) == 1


def test_get_tools_registers_search_tool_when_only_knowledge_set():
    """When only knowledge is set (no retriever), a search tool is still registered."""

    agent = Agent()
    agent.knowledge = MockKnowledge()  # type: ignore
    agent.knowledge_retriever = None
    agent.search_knowledge = True

    tools = get_tools(agent, _make_run_response(), _make_run_context(), _make_session())

    knowledge_tools = _get_knowledge_tools(tools)
    assert len(knowledge_tools) == 1


def test_get_tools_registers_search_tool_when_only_retriever_set():
    """When only knowledge_retriever is set (no knowledge), a search tool is registered."""

    def custom_retriever(query, agent=None, num_documents=None, **kwargs):
        return [{"content": "from retriever"}]

    agent = Agent()
    agent.knowledge = None
    agent.knowledge_retriever = custom_retriever  # type: ignore
    agent.search_knowledge = True

    tools = get_tools(agent, _make_run_response(), _make_run_context(), _make_session())

    knowledge_tools = _get_knowledge_tools(tools)
    assert len(knowledge_tools) == 1


def test_get_tools_no_search_tool_when_neither_knowledge_nor_retriever_set():
    """When neither knowledge nor knowledge_retriever is set, no search tool is registered."""

    agent = Agent()
    agent.knowledge = None
    agent.knowledge_retriever = None
    agent.search_knowledge = True

    tools = get_tools(agent, _make_run_response(), _make_run_context(), _make_session())

    knowledge_tools = _get_knowledge_tools(tools)
    assert len(knowledge_tools) == 0


def test_search_tool_invokes_custom_retriever_when_both_set():
    """End-to-end: when both knowledge and retriever are set, invoking the tool calls the retriever."""
    retriever_mock = MagicMock(return_value=[{"content": "from custom retriever"}])

    agent = Agent()
    agent.knowledge = MockKnowledge()  # type: ignore
    agent.knowledge_retriever = retriever_mock  # type: ignore
    agent.search_knowledge = True

    tools = get_tools(agent, _make_run_response(), _make_run_context(), _make_session())
    knowledge_tools = _get_knowledge_tools(tools)
    assert len(knowledge_tools) == 1

    # Invoke the tool's entrypoint directly
    result = knowledge_tools[0].entrypoint("test query")
    retriever_mock.assert_called_once()
    assert "from custom retriever" in result


def test_search_tool_invokes_custom_retriever_when_only_retriever_set():
    """End-to-end: when only retriever is set (no knowledge), invoking the tool calls the retriever."""
    retriever_mock = MagicMock(return_value=[{"content": "retriever only"}])

    agent = Agent()
    agent.knowledge = None
    agent.knowledge_retriever = retriever_mock  # type: ignore
    agent.search_knowledge = True

    tools = get_tools(agent, _make_run_response(), _make_run_context(), _make_session())
    knowledge_tools = _get_knowledge_tools(tools)
    assert len(knowledge_tools) == 1

    result = knowledge_tools[0].entrypoint("test query")
    retriever_mock.assert_called_once()
    assert "retriever only" in result


@pytest.mark.asyncio
async def test_aget_tools_registers_search_tool_when_both_knowledge_and_retriever_set():
    """Async: when both are set, a search tool is registered."""

    def custom_retriever(query, agent=None, num_documents=None, **kwargs):
        return [{"content": "from retriever"}]

    agent = Agent()
    agent.knowledge = MockKnowledge()  # type: ignore
    agent.knowledge_retriever = custom_retriever  # type: ignore
    agent.search_knowledge = True

    tools = await aget_tools(agent, _make_run_response(), _make_run_context(), _make_session())

    knowledge_tools = _get_knowledge_tools(tools)
    assert len(knowledge_tools) == 1


@pytest.mark.asyncio
async def test_aget_tools_registers_search_tool_when_only_knowledge_set():
    """Async: when only knowledge is set, a search tool is still registered."""

    agent = Agent()
    agent.knowledge = MockKnowledge()  # type: ignore
    agent.knowledge_retriever = None
    agent.search_knowledge = True

    tools = await aget_tools(agent, _make_run_response(), _make_run_context(), _make_session())

    knowledge_tools = _get_knowledge_tools(tools)
    assert len(knowledge_tools) == 1
