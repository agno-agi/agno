"""Unit tests for grouped config parameters on Agent.

Grouped config objects (agno.config) are constructor-side sugar: they resolve
to the same flat attributes the flat parameters set, flat parameters remain
fully supported, and a config object wins over flat parameters with a warning.
"""

from unittest.mock import patch

import pytest

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.config import (
    CultureConfig,
    FollowupConfig,
    HistoryConfig,
    MemoryConfig,
    ReasoningConfig,
    RetryConfig,
    SessionSummaryConfig,
)
from agno.culture.manager import CultureManager
from agno.memory import MemoryManager
from agno.session.summary import SessionSummaryManager

# =============================================================================
# History
# =============================================================================


def test_history_flat_params_unchanged():
    agent = Agent(add_history_to_context=True, num_history_runs=5, store_history_messages=True)
    assert agent.add_history_to_context is True
    assert agent.num_history_runs == 5
    assert agent.store_history_messages is True


def test_history_config_resolves_to_flat_attributes():
    agent = Agent(
        history=HistoryConfig(
            num_runs=7,
            max_tool_calls=4,
            store_messages=True,
            read_chat_history=True,
            search_past_sessions=True,
            num_past_sessions=10,
            num_past_session_runs=2,
        )
    )
    assert agent.add_history_to_context is True
    assert agent.num_history_runs == 7
    assert agent.max_tool_calls_from_history == 4
    assert agent.store_history_messages is True
    assert agent.read_chat_history is True
    assert agent.search_past_sessions is True
    assert agent.num_past_sessions_to_search == 10
    assert agent.num_past_session_runs_in_search == 2


def test_history_config_equivalent_to_flat_params():
    flat = Agent(add_history_to_context=True, num_history_runs=7, read_chat_history=True)
    grouped = Agent(history=HistoryConfig(num_runs=7, read_chat_history=True))
    for attr in (
        "add_history_to_context",
        "num_history_runs",
        "num_history_messages",
        "max_tool_calls_from_history",
        "store_history_messages",
        "read_chat_history",
        "search_past_sessions",
        "num_past_sessions_to_search",
        "num_past_session_runs_in_search",
    ):
        assert getattr(flat, attr) == getattr(grouped, attr)


def test_history_bool_only_flips_master_switch():
    agent = Agent(history=True, num_history_runs=9)
    assert agent.add_history_to_context is True
    assert agent.num_history_runs == 9

    agent = Agent(history=False, num_history_runs=9)
    assert agent.add_history_to_context is False
    assert agent.num_history_runs == 9


def test_history_config_wins_over_flat_params_with_warning():
    with patch("agno.config.log_warning") as mock_warning:
        agent = Agent(history=HistoryConfig(num_runs=4), num_history_runs=8)
    assert agent.num_history_runs == 4
    mock_warning.assert_called_once()
    assert "num_history_runs" in mock_warning.call_args[0][0]


def test_history_num_messages_defaulting_preserved():
    # No history settings at all: num_history_runs defaults to 3
    agent = Agent()
    assert agent.num_history_runs == 3
    assert agent.num_history_messages is None

    # num_messages via config leaves num_runs unset
    agent = Agent(history=HistoryConfig(num_messages=20))
    assert agent.num_history_messages == 20
    assert agent.num_history_runs is None


# =============================================================================
# Reasoning
# =============================================================================


def test_reasoning_flat_params_unchanged():
    agent = Agent(reasoning=True, reasoning_min_steps=2, reasoning_max_steps=5)
    assert agent.reasoning is True
    assert agent.reasoning_min_steps == 2
    assert agent.reasoning_max_steps == 5


def test_reasoning_config_enables_reasoning():
    agent = Agent(reasoning=ReasoningConfig(min_steps=2, max_steps=5))
    assert agent.reasoning is True
    assert agent.reasoning_min_steps == 2
    assert agent.reasoning_max_steps == 5


def test_reasoning_config_wins_over_flat_params_with_warning():
    with patch("agno.config.log_warning") as mock_warning:
        agent = Agent(reasoning=ReasoningConfig(max_steps=5), reasoning_max_steps=20)
    assert agent.reasoning_max_steps == 5
    mock_warning.assert_called_once()


# =============================================================================
# Memory
# =============================================================================


def test_memory_flat_params_unchanged():
    manager = MemoryManager()
    agent = Agent(memory_manager=manager, enable_agentic_memory=True)
    assert agent.memory_manager is manager
    assert agent.enable_agentic_memory is True
    assert agent.update_memory_on_run is False


def test_memory_bool_enables_update_on_run():
    agent = Agent(memory=True)
    assert agent.update_memory_on_run is True
    assert agent.enable_agentic_memory is False


def test_memory_manager_shorthand_enables_update_on_run():
    manager = MemoryManager()
    agent = Agent(memory=manager)
    assert agent.memory_manager is manager
    assert agent.update_memory_on_run is True


def test_memory_config_resolves_to_flat_attributes():
    manager = MemoryManager()
    agent = Agent(memory=MemoryConfig(manager=manager, agentic=True, add_to_context=True))
    assert agent.memory_manager is manager
    assert agent.enable_agentic_memory is True
    assert agent.update_memory_on_run is False
    assert agent.add_memories_to_context is True


def test_memory_config_wins_over_flat_params_with_warning():
    with patch("agno.config.log_warning") as mock_warning:
        agent = Agent(memory=MemoryConfig(agentic=True), update_memory_on_run=True)
    assert agent.enable_agentic_memory is True
    assert agent.update_memory_on_run is False
    mock_warning.assert_called_once()


# =============================================================================
# Session summaries
# =============================================================================


def test_session_summary_manager_alone_still_enables_summaries():
    manager = SessionSummaryManager()
    agent = Agent(session_summary_manager=manager)
    assert agent.enable_session_summaries is True
    assert agent.session_summary_manager is manager


def test_session_summaries_bool():
    agent = Agent(session_summaries=True)
    assert agent.enable_session_summaries is True

    agent = Agent(session_summaries=False)
    assert agent.enable_session_summaries is False


def test_session_summaries_manager_shorthand():
    manager = SessionSummaryManager()
    agent = Agent(session_summaries=manager)
    assert agent.enable_session_summaries is True
    assert agent.session_summary_manager is manager


def test_session_summaries_config():
    manager = SessionSummaryManager()
    agent = Agent(session_summaries=SessionSummaryConfig(manager=manager, add_to_context=True))
    assert agent.enable_session_summaries is True
    assert agent.session_summary_manager is manager
    assert agent.add_session_summary_to_context is True


# =============================================================================
# Culture
# =============================================================================


def test_culture_flat_params_unchanged():
    manager = CultureManager()
    agent = Agent(culture_manager=manager, update_cultural_knowledge=True)
    assert agent.culture_manager is manager
    assert agent.update_cultural_knowledge is True


def test_culture_bool_enables_update_on_run():
    agent = Agent(culture=True)
    assert agent.update_cultural_knowledge is True
    assert agent.enable_agentic_culture is False


def test_culture_manager_shorthand():
    manager = CultureManager()
    agent = Agent(culture=manager)
    assert agent.culture_manager is manager
    assert agent.update_cultural_knowledge is True


def test_culture_config_resolves_to_flat_attributes():
    agent = Agent(culture=CultureConfig(agentic=True, add_to_context=True))
    assert agent.enable_agentic_culture is True
    assert agent.add_culture_to_context is True
    assert agent.update_cultural_knowledge is False


# =============================================================================
# Compression
# =============================================================================


def test_compression_flat_params_unchanged():
    manager = CompressionManager()
    agent = Agent(compress_tool_results=True, compression_manager=manager)
    assert agent.compress_tool_results is True
    assert agent.compression_manager is manager


def test_compression_manager_shorthand():
    manager = CompressionManager()
    agent = Agent(compress_tool_results=manager)
    assert agent.compress_tool_results is True
    assert agent.compression_manager is manager


# =============================================================================
# Followups
# =============================================================================


def test_followups_flat_params_unchanged():
    agent = Agent(followups=True, num_followups=5)
    assert agent.followups is True
    assert agent.num_followups == 5


def test_followups_config_enables_followups():
    agent = Agent(followups=FollowupConfig(num=2))
    assert agent.followups is True
    assert agent.num_followups == 2


def test_followups_config_num_validation_preserved():
    with pytest.raises(ValueError, match="num_followups must be at least 1"):
        Agent(followups=FollowupConfig(num=0))
    with pytest.raises(ValueError, match="num_followups must be at least 1"):
        Agent(num_followups=0)


# =============================================================================
# Retry
# =============================================================================


def test_retry_flat_params_unchanged():
    agent = Agent(retries=2, delay_between_retries=3, exponential_backoff=True)
    assert agent.retries == 2
    assert agent.delay_between_retries == 3
    assert agent.exponential_backoff is True


def test_retry_config_resolves_to_flat_attributes():
    agent = Agent(retry=RetryConfig(retries=4, delay=2, exponential_backoff=True))
    assert agent.retries == 4
    assert agent.delay_between_retries == 2
    assert agent.exponential_backoff is True


def test_retry_config_wins_over_flat_params_with_warning():
    with patch("agno.config.log_warning") as mock_warning:
        agent = Agent(retry=RetryConfig(retries=4), retries=9)
    assert agent.retries == 4
    mock_warning.assert_called_once()


# =============================================================================
# deep_copy round-trip
# =============================================================================


def test_deep_copy_round_trip_with_grouped_configs():
    agent = Agent(
        history=HistoryConfig(num_runs=7, search_past_sessions=True),
        reasoning=ReasoningConfig(max_steps=5),
        memory=True,
        retry=RetryConfig(retries=3),
        followups=FollowupConfig(num=2),
    )
    copy = agent.deep_copy()
    assert copy.num_history_runs == 7
    assert copy.search_past_sessions is True
    assert copy.reasoning_max_steps == 5
    assert copy.update_memory_on_run is True
    assert copy.retries == 3
    assert copy.num_followups == 2
