"""Unit tests for grouped config parameters on Team.

The resolvers are shared with Agent (see tests/unit/agent), so these tests
cover the Team wiring rather than re-testing every resolution rule.
"""

from unittest.mock import patch

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.config import (
    FollowupConfig,
    HistoryConfig,
    MemoryConfig,
    ReasoningConfig,
    RetryConfig,
    SessionSummaryConfig,
)
from agno.memory import MemoryManager
from agno.session.summary import SessionSummaryManager
from agno.team import Team


def _member() -> Agent:
    return Agent(name="member")


def test_flat_params_unchanged():
    team = Team(members=[_member()], add_history_to_context=True, num_history_runs=4, retries=1)
    assert team.add_history_to_context is True
    assert team.num_history_runs == 4
    assert team.retries == 1


def test_history_config_resolves_to_flat_attributes():
    team = Team(members=[_member()], history=HistoryConfig(num_runs=6, read_chat_history=True, store_messages=True))
    assert team.add_history_to_context is True
    assert team.num_history_runs == 6
    assert team.read_chat_history is True
    assert team.store_history_messages is True


def test_history_bool_only_flips_master_switch():
    team = Team(members=[_member()], history=True, num_history_runs=8)
    assert team.add_history_to_context is True
    assert team.num_history_runs == 8


def test_history_config_wins_over_flat_params_with_warning():
    with patch("agno.config.log_warning") as mock_warning:
        team = Team(members=[_member()], history=HistoryConfig(num_runs=4), num_history_runs=8)
    assert team.num_history_runs == 4
    mock_warning.assert_called_once()


def test_reasoning_config_enables_reasoning():
    team = Team(members=[_member()], reasoning=ReasoningConfig(min_steps=2, max_steps=5))
    assert team.reasoning is True
    assert team.reasoning_min_steps == 2
    assert team.reasoning_max_steps == 5


def test_memory_shorthands():
    manager = MemoryManager()
    team = Team(members=[_member()], memory=manager)
    assert team.memory_manager is manager
    assert team.update_memory_on_run is True

    team = Team(members=[_member()], memory=MemoryConfig(agentic=True))
    assert team.enable_agentic_memory is True
    assert team.update_memory_on_run is False


def test_session_summaries_shorthands():
    manager = SessionSummaryManager()
    team = Team(members=[_member()], session_summaries=manager)
    assert team.enable_session_summaries is True
    assert team.session_summary_manager is manager

    team = Team(members=[_member()], session_summaries=SessionSummaryConfig(add_to_context=True))
    assert team.enable_session_summaries is True
    assert team.add_session_summary_to_context is True

    # Passing a manager via the flat param still enables summaries
    team = Team(members=[_member()], session_summary_manager=manager)
    assert team.enable_session_summaries is True


def test_compression_manager_shorthand():
    manager = CompressionManager()
    team = Team(members=[_member()], compress_tool_results=manager)
    assert team.compress_tool_results is True
    assert team.compression_manager is manager


def test_followups_config():
    team = Team(members=[_member()], followups=FollowupConfig(num=2))
    assert team.followups is True
    assert team.num_followups == 2


def test_retry_config():
    team = Team(members=[_member()], retry=RetryConfig(retries=5, exponential_backoff=True))
    assert team.retries == 5
    assert team.exponential_backoff is True


def test_deep_copy_round_trip_with_grouped_configs():
    team = Team(
        members=[_member()],
        history=HistoryConfig(num_runs=6),
        reasoning=ReasoningConfig(max_steps=5),
        retry=RetryConfig(retries=3),
    )
    copy = team.deep_copy()
    assert copy.num_history_runs == 6
    assert copy.reasoning_max_steps == 5
    assert copy.retries == 3
