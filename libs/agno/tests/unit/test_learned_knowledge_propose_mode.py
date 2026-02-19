"""Tests for LearningMode.PROPOSE confirmation behavior in LearnedKnowledgeStore."""

import pytest

from agno.learn.config import LearnedKnowledgeConfig, LearningMode
from agno.learn.stores.learned_knowledge import LearnedKnowledgeStore
from agno.tools.function import Function


class MockKnowledge:
    """Minimal mock knowledge base for testing tool creation."""

    def __init__(self):
        self.inserted = []

    def search(self, query, max_results=5, filters=None):
        return []

    def insert(self, **kwargs):
        self.inserted.append(kwargs)


# ---------------------------------------------------------------------------
# PROPOSE mode: save_learning must require confirmation
# ---------------------------------------------------------------------------


def test_propose_mode_save_tool_requires_confirmation():
    """PROPOSE mode should return a Function with requires_confirmation=True for save_learning."""
    config = LearnedKnowledgeConfig(
        mode=LearningMode.PROPOSE,
        knowledge=MockKnowledge(),
        enable_agent_tools=True,
        agent_can_save=True,
        agent_can_search=True,
    )
    store = LearnedKnowledgeStore(config=config)
    tools = store.get_agent_tools(namespace="global")

    # Find the save_learning tool
    save_tools = [t for t in tools if isinstance(t, Function) and t.name == "save_learning"]
    assert len(save_tools) == 1, f"Expected exactly 1 Function-based save_learning, got {len(save_tools)}"

    save_func = save_tools[0]
    assert save_func.requires_confirmation is True, "PROPOSE mode save_learning must set requires_confirmation=True"


def test_propose_mode_search_tool_is_plain_callable():
    """PROPOSE mode should NOT wrap search_learnings in a Function with confirmation."""
    config = LearnedKnowledgeConfig(
        mode=LearningMode.PROPOSE,
        knowledge=MockKnowledge(),
        enable_agent_tools=True,
        agent_can_save=True,
        agent_can_search=True,
    )
    store = LearnedKnowledgeStore(config=config)
    tools = store.get_agent_tools(namespace="global")

    # The search tool should be a plain callable, not a Function with confirmation
    non_function_tools = [t for t in tools if not isinstance(t, Function)]
    assert len(non_function_tools) == 1, "search_learnings should remain a plain callable"


# ---------------------------------------------------------------------------
# AGENTIC mode: save_learning must NOT require confirmation (regression guard)
# ---------------------------------------------------------------------------


def test_agentic_mode_save_tool_no_confirmation():
    """AGENTIC mode should return a plain callable for save_learning (no confirmation)."""
    config = LearnedKnowledgeConfig(
        mode=LearningMode.AGENTIC,
        knowledge=MockKnowledge(),
        enable_agent_tools=True,
        agent_can_save=True,
        agent_can_search=True,
    )
    store = LearnedKnowledgeStore(config=config)
    tools = store.get_agent_tools(namespace="global")

    # In AGENTIC mode, save_learning should be a plain callable
    function_tools = [t for t in tools if isinstance(t, Function)]
    assert len(function_tools) == 0, "AGENTIC mode should not wrap tools in Function objects"


# ---------------------------------------------------------------------------
# Async variant: PROPOSE mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_mode_async_save_tool_requires_confirmation():
    """Async PROPOSE mode should also return a Function with requires_confirmation=True."""
    config = LearnedKnowledgeConfig(
        mode=LearningMode.PROPOSE,
        knowledge=MockKnowledge(),
        enable_agent_tools=True,
        agent_can_save=True,
        agent_can_search=True,
    )
    store = LearnedKnowledgeStore(config=config)
    tools = await store.aget_agent_tools(namespace="global")

    save_tools = [t for t in tools if isinstance(t, Function) and t.name == "save_learning"]
    assert len(save_tools) == 1, f"Expected exactly 1 Function-based save_learning (async), got {len(save_tools)}"

    save_func = save_tools[0]
    assert save_func.requires_confirmation is True, (
        "Async PROPOSE mode save_learning must set requires_confirmation=True"
    )


# ---------------------------------------------------------------------------
# get_tools respects enable_agent_tools
# ---------------------------------------------------------------------------


def test_propose_mode_get_tools_respects_enable_flag():
    """get_tools should return empty when enable_agent_tools=False, even in PROPOSE mode."""
    config = LearnedKnowledgeConfig(
        mode=LearningMode.PROPOSE,
        knowledge=MockKnowledge(),
        enable_agent_tools=False,
    )
    store = LearnedKnowledgeStore(config=config)
    tools = store.get_tools(namespace="global")
    assert tools == []


def test_propose_mode_get_tools_delegates_correctly():
    """get_tools should delegate to get_agent_tools and return the confirmation-wrapped tool."""
    config = LearnedKnowledgeConfig(
        mode=LearningMode.PROPOSE,
        knowledge=MockKnowledge(),
        enable_agent_tools=True,
        agent_can_save=True,
        agent_can_search=False,
    )
    store = LearnedKnowledgeStore(config=config)
    tools = store.get_tools(namespace="global")

    assert len(tools) == 1
    assert isinstance(tools[0], Function)
    assert tools[0].requires_confirmation is True
