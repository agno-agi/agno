"""Tests for LearningMode.PROPOSE behavior in LearnedKnowledgeStore.

PROPOSE mode uses a text-based confirmation flow driven by the system prompt:
- The model proposes learnings in its response text
- The user confirms in the next message
- The model then calls save_learning (a plain callable, same as AGENTIC mode)

The difference between PROPOSE and AGENTIC is in the system prompt instructions,
not in the tool signatures. Both modes return identical plain callables.
"""

import pytest

from agno.learn.config import LearnedKnowledgeConfig, LearningMode
from agno.learn.machine import LearningMachine
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
# PROPOSE mode: tools are plain callables (text-based confirmation via prompt)
# ---------------------------------------------------------------------------


def test_propose_mode_save_tool_is_plain_callable():
    """PROPOSE mode should return a plain callable for save_learning (no Function wrapper)."""
    config = LearnedKnowledgeConfig(
        mode=LearningMode.PROPOSE,
        knowledge=MockKnowledge(),
        enable_agent_tools=True,
        agent_can_save=True,
        agent_can_search=True,
    )
    store = LearnedKnowledgeStore(config=config)
    tools = store.get_agent_tools(namespace="global")

    save_tools = [t for t in tools if callable(t) and getattr(t, "__name__", "") == "save_learning"]
    assert len(save_tools) == 1, f"Expected exactly 1 save_learning callable, got {len(save_tools)}"
    assert not isinstance(save_tools[0], Function), "PROPOSE mode save_learning must be a plain callable, not Function"


def test_propose_mode_search_tool_is_plain_callable():
    """PROPOSE mode should return a plain callable for search_learnings."""
    config = LearnedKnowledgeConfig(
        mode=LearningMode.PROPOSE,
        knowledge=MockKnowledge(),
        enable_agent_tools=True,
        agent_can_save=True,
        agent_can_search=True,
    )
    store = LearnedKnowledgeStore(config=config)
    tools = store.get_agent_tools(namespace="global")

    search_tools = [t for t in tools if callable(t) and getattr(t, "__name__", "") == "search_learnings"]
    assert len(search_tools) == 1, "Expected exactly 1 search_learnings callable"
    assert not isinstance(search_tools[0], Function), "search_learnings should be a plain callable"


# ---------------------------------------------------------------------------
# PROPOSE and AGENTIC return identical tool signatures
# ---------------------------------------------------------------------------


def test_propose_and_agentic_return_same_tool_types():
    """PROPOSE and AGENTIC modes should both return plain callables with the same names."""
    for mode in [LearningMode.PROPOSE, LearningMode.AGENTIC]:
        config = LearnedKnowledgeConfig(
            mode=mode,
            knowledge=MockKnowledge(),
            enable_agent_tools=True,
            agent_can_save=True,
            agent_can_search=True,
        )
        store = LearnedKnowledgeStore(config=config)
        tools = store.get_agent_tools(namespace="global")

        assert len(tools) == 2, f"{mode} mode should return 2 tools"
        for tool in tools:
            assert callable(tool), f"Tool must be callable in {mode} mode"
            assert not isinstance(tool, Function), f"Tool must be a plain callable in {mode} mode"

        names = {getattr(t, "__name__", "") for t in tools}
        assert names == {"search_learnings", "save_learning"}, f"Unexpected tool names in {mode} mode: {names}"


# ---------------------------------------------------------------------------
# Async variant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_mode_async_tools_are_plain_callables():
    """Async PROPOSE mode should also return plain callables."""
    config = LearnedKnowledgeConfig(
        mode=LearningMode.PROPOSE,
        knowledge=MockKnowledge(),
        enable_agent_tools=True,
        agent_can_save=True,
        agent_can_search=True,
    )
    store = LearnedKnowledgeStore(config=config)
    tools = await store.aget_agent_tools(namespace="global")

    assert len(tools) == 2
    for tool in tools:
        assert callable(tool), "Async tool must be callable"
        assert not isinstance(tool, Function), "Async tool must be a plain callable"


# ---------------------------------------------------------------------------
# get_tools respects enable_agent_tools
# ---------------------------------------------------------------------------


def test_propose_mode_get_tools_respects_enable_flag():
    """get_tools should return empty when enable_agent_tools=False."""
    config = LearnedKnowledgeConfig(
        mode=LearningMode.PROPOSE,
        knowledge=MockKnowledge(),
        enable_agent_tools=False,
    )
    store = LearnedKnowledgeStore(config=config)
    tools = store.get_tools(namespace="global")
    assert tools == []


def test_propose_mode_get_tools_delegates_correctly():
    """get_tools should delegate to get_agent_tools and return plain callables."""
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
    assert callable(tools[0])
    assert not isinstance(tools[0], Function)


# ---------------------------------------------------------------------------
# LearningMachine.requires_history
# ---------------------------------------------------------------------------


def test_learning_machine_requires_history_for_propose_mode():
    """LearningMachine should report requires_history=True when a store uses PROPOSE mode."""
    lm = LearningMachine(
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.PROPOSE,
            knowledge=MockKnowledge(),
        ),
    )
    assert lm.requires_history is True


def test_learning_machine_no_history_for_agentic_mode():
    """LearningMachine should report requires_history=False for AGENTIC mode."""
    lm = LearningMachine(
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
            knowledge=MockKnowledge(),
        ),
    )
    assert lm.requires_history is False
