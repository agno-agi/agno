"""Unit tests for grouped config parameters on Team.

The resolvers are shared with Agent (see tests/unit/agent), so these tests
focus on the Team wiring and Team-only groups rather than re-testing every
resolution rule.
"""

from unittest.mock import patch

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.config import (
    CallableCacheConfig,
    DelegationConfig,
    FollowupConfig,
    HistoryConfig,
    KnowledgeConfig,
    MemoryConfig,
    ParsingConfig,
    ReasoningConfig,
    RetryConfig,
    SessionConfig,
    StorageConfig,
)
from agno.memory import MemoryManager
from agno.session.summary import SessionSummaryManager
from agno.team import Team
from agno.team.mode import TeamMode


def _member() -> Agent:
    return Agent(name="member")


def test_flat_params_unchanged():
    team = Team(members=[_member()], respond_directly=True, num_history_runs=4, retries=1)
    assert team.respond_directly is True
    assert team.mode == TeamMode.route
    assert team.num_history_runs == 4
    assert team.retries == 1


# =============================================================================
# Delegation
# =============================================================================


def test_delegation_config_resolves_to_flat_attributes():
    team = Team(
        members=[_member()],
        delegation=DelegationConfig(
            mode=TeamMode.broadcast,
            max_iterations=5,
            share_member_interactions=True,
            add_member_tools_to_context=True,
            get_member_information_tool=True,
            store_member_responses=True,
            stream_member_events=False,
            show_members_responses=True,
            add_team_history_to_members=True,
            num_team_history_runs=7,
        ),
    )
    assert team.mode == TeamMode.broadcast
    assert team.delegate_to_all_members is True
    assert team.max_iterations == 5
    assert team.share_member_interactions is True
    assert team.add_member_tools_to_context is True
    assert team.get_member_information_tool is True
    assert team.store_member_responses is True
    assert team.stream_member_events is False
    assert team.show_members_responses is True
    assert team.add_team_history_to_members is True
    assert team.num_team_history_runs == 7


def test_delegation_unset_config_fields_keep_flat_values():
    team = Team(members=[_member()], delegation=DelegationConfig(max_iterations=7), respond_directly=True)
    assert team.max_iterations == 7
    assert team.respond_directly is True
    assert team.mode == TeamMode.route


def test_delegation_config_wins_over_flat_params_with_warning():
    with patch("agno.config.log_warning") as mock_warning:
        team = Team(members=[_member()], delegation=DelegationConfig(max_iterations=5), max_iterations=20)
    assert team.max_iterations == 5
    mock_warning.assert_called_once()


def test_delegation_defaults_unchanged():
    team = Team(members=[_member()])
    assert team.mode == TeamMode.coordinate
    assert team.max_iterations == 10
    assert team.stream_member_events is True
    assert team.determine_input_for_members is True


# =============================================================================
# Shared groups on Team
# =============================================================================


def test_session_config_with_summaries():
    manager = SessionSummaryManager()
    team = Team(members=[_member()], session=SessionConfig(id="ts", agentic_state=True, summaries=manager))
    assert team.session_id == "ts"
    assert team.enable_agentic_state is True
    assert team.enable_session_summaries is True
    assert team.session_summary_manager is manager


def test_history_config_resolves_to_flat_attributes():
    team = Team(members=[_member()], history=HistoryConfig(num_runs=6, read_chat_history=True))
    assert team.add_history_to_context is True
    assert team.num_history_runs == 6
    assert team.read_chat_history is True


def test_history_read_tool_call_history_unsupported_on_team():
    with patch("agno.config.log_warning") as mock_warning:
        Team(members=[_member()], history=HistoryConfig(read_tool_call_history=True))
    assert any("read_tool_call_history" in str(call) for call in mock_warning.call_args_list)


def test_storage_config_resolves_to_flat_attributes():
    team = Team(members=[_member()], storage=StorageConfig(media=False, events=True, history_messages=True))
    assert team.store_media is False
    assert team.store_events is True
    assert team.store_history_messages is True
    assert team.store_tool_messages is True


def test_parsing_config_resolves_to_flat_attributes():
    team = Team(members=[_member()], parsing=ParsingConfig(parser_prompt="pp", use_json_mode=True))
    assert team.parser_model_prompt == "pp"
    assert team.use_json_mode is True
    assert team.parse_response is True


def test_parsing_structured_outputs_unsupported_on_team():
    with patch("agno.config.log_warning") as mock_warning:
        Team(members=[_member()], parsing=ParsingConfig(structured_outputs=True))
    assert any("structured_outputs" in str(call) for call in mock_warning.call_args_list)


def test_knowledge_config_resolves_to_flat_attributes():
    team = Team(members=[_member()], knowledge_config=KnowledgeConfig(add_to_context=True, references_format="yaml"))
    assert team.add_knowledge_to_context is True
    assert team.references_format == "yaml"
    assert team.search_knowledge is True


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


def test_callable_cache_config_with_members_key():
    def key_fn(*args, **kwargs):
        return "k"

    team = Team(members=[_member()], cache_callables=CallableCacheConfig(members_cache_key=key_fn))
    assert team.cache_callables is True
    assert team.callable_members_cache_key is key_fn


def test_deep_copy_round_trip_with_grouped_configs():
    team = Team(
        members=[_member()],
        session=SessionConfig(id="ts2"),
        delegation=DelegationConfig(max_iterations=6),
        history=HistoryConfig(num_runs=6),
        retry=RetryConfig(retries=3),
    )
    copy = team.deep_copy()
    assert copy.session_id == "ts2"
    assert copy.max_iterations == 6
    assert copy.num_history_runs == 6
    assert copy.retries == 3
