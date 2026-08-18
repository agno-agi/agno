"""Unit tests for grouped config parameters on Agent.

Grouped config objects (agno.config) are constructor-side sugar: they resolve
to the same flat attributes the flat parameters set, and flat parameters
remain fully supported.

Merge semantics are field-level: a config field left as None means "not set"
and the flat value (or its default) wins for that field alone. A set config
field wins over the flat parameter, warning only when the flat parameter was
explicitly set to a different value. Booleans on group parameters only flip
the cluster's master switch.
"""

from unittest.mock import patch

import pytest

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.config import (
    CallableCacheConfig,
    CultureConfig,
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
from agno.culture.manager import CultureManager
from agno.memory import MemoryManager
from agno.session.summary import SessionSummaryManager

# =============================================================================
# History
# =============================================================================


def test_history_flat_params_unchanged():
    agent = Agent(add_history_to_context=True, num_history_runs=5, read_tool_call_history=True)
    assert agent.add_history_to_context is True
    assert agent.num_history_runs == 5
    assert agent.read_tool_call_history is True


def test_history_config_resolves_to_flat_attributes():
    agent = Agent(
        history=HistoryConfig(
            num_runs=7,
            max_tool_calls=4,
            read_chat_history=True,
            read_tool_call_history=True,
            search_past_sessions=True,
            num_past_sessions=10,
            num_past_session_runs=2,
        )
    )
    assert agent.add_history_to_context is True
    assert agent.num_history_runs == 7
    assert agent.max_tool_calls_from_history == 4
    assert agent.read_chat_history is True
    assert agent.read_tool_call_history is True
    assert agent.search_past_sessions is True
    assert agent.num_past_sessions_to_search == 10
    assert agent.num_past_session_runs_in_search == 2


def test_history_bool_only_flips_master_switch():
    agent = Agent(history=True, num_history_runs=9)
    assert agent.add_history_to_context is True
    assert agent.num_history_runs == 9

    agent = Agent(history=False, num_history_runs=9)
    assert agent.add_history_to_context is False
    assert agent.num_history_runs == 9


def test_history_unset_config_fields_keep_flat_values():
    agent = Agent(history=HistoryConfig(num_runs=7), read_chat_history=True, max_tool_calls_from_history=2)
    assert agent.num_history_runs == 7
    assert agent.read_chat_history is True
    assert agent.max_tool_calls_from_history == 2


def test_history_config_wins_over_flat_params_with_warning():
    with patch("agno.config.log_warning") as mock_warning:
        agent = Agent(history=HistoryConfig(num_runs=4), num_history_runs=8)
    assert agent.num_history_runs == 4
    mock_warning.assert_called_once()
    assert "num_history_runs" in mock_warning.call_args[0][0]


def test_history_no_warning_when_flat_equals_config():
    with patch("agno.config.log_warning") as mock_warning:
        agent = Agent(history=HistoryConfig(num_runs=4), num_history_runs=4)
    assert agent.num_history_runs == 4
    mock_warning.assert_not_called()


def test_history_num_messages_defaulting_preserved():
    agent = Agent()
    assert agent.num_history_runs == 3
    assert agent.num_history_messages is None

    agent = Agent(history=HistoryConfig(num_messages=20))
    assert agent.num_history_messages == 20
    assert agent.num_history_runs is None


# =============================================================================
# Session
# =============================================================================


def test_session_flat_params_unchanged():
    agent = Agent(session_id="s1", session_state={"k": 1}, cache_session=True)
    assert agent.session_id == "s1"
    assert agent.session_state == {"k": 1}
    assert agent.cache_session is True


def test_session_config_resolves_to_flat_attributes():
    agent = Agent(
        session=SessionConfig(
            id="s2",
            state={"k": 2},
            add_state_to_context=True,
            agentic_state=True,
            overwrite_db_state=True,
            cache=True,
        )
    )
    assert agent.session_id == "s2"
    assert agent.session_state == {"k": 2}
    assert agent.add_session_state_to_context is True
    assert agent.enable_agentic_state is True
    assert agent.overwrite_db_session_state is True
    assert agent.cache_session is True


def test_session_unset_config_fields_keep_flat_values():
    agent = Agent(session=SessionConfig(id="s3"), session_state={"x": 1}, cache_session=True)
    assert agent.session_id == "s3"
    assert agent.session_state == {"x": 1}
    assert agent.cache_session is True


def test_session_summaries_bool_in_config():
    agent = Agent(session=SessionConfig(summaries=True))
    assert agent.enable_session_summaries is True

    agent = Agent(session=SessionConfig(summaries=False), enable_session_summaries=True)
    assert agent.enable_session_summaries is False


def test_session_summaries_manager_in_config():
    manager = SessionSummaryManager()
    agent = Agent(session=SessionConfig(summaries=manager, add_summaries_to_context=True))
    assert agent.enable_session_summaries is True
    assert agent.session_summary_manager is manager
    assert agent.add_session_summary_to_context is True


def test_session_summary_manager_flat_param_still_enables_summaries():
    manager = SessionSummaryManager()
    agent = Agent(session_summary_manager=manager)
    assert agent.enable_session_summaries is True
    assert agent.session_summary_manager is manager


# =============================================================================
# Storage
# =============================================================================


def test_storage_flat_params_unchanged():
    agent = Agent(store_media=False, store_history_messages=True, store_events=True)
    assert agent.store_media is False
    assert agent.store_history_messages is True
    assert agent.store_events is True


def test_storage_config_resolves_to_flat_attributes():
    agent = Agent(storage=StorageConfig(media=False, tool_messages=False, history_messages=True, events=True))
    assert agent.store_media is False
    assert agent.store_tool_messages is False
    assert agent.store_history_messages is True
    assert agent.store_events is True


def test_storage_unset_config_fields_keep_defaults():
    agent = Agent(storage=StorageConfig(events=True))
    assert agent.store_media is True
    assert agent.store_tool_messages is True
    assert agent.store_history_messages is False


def test_storage_executor_outputs_unsupported_on_agent():
    with patch("agno.config.log_warning") as mock_warning:
        Agent(storage=StorageConfig(executor_outputs=False))
    assert any("executor_outputs" in str(call) for call in mock_warning.call_args_list)


# =============================================================================
# Knowledge
# =============================================================================


def test_knowledge_flat_params_unchanged():
    agent = Agent(add_knowledge_to_context=True, references_format="yaml", update_knowledge=True)
    assert agent.add_knowledge_to_context is True
    assert agent.references_format == "yaml"
    assert agent.update_knowledge is True


def test_knowledge_config_resolves_to_flat_attributes():
    agent = Agent(
        knowledge_config=KnowledgeConfig(
            filters={"team": "eng"},
            agentic_filters=True,
            add_to_context=True,
            references_format="yaml",
            search_knowledge=False,
            add_search_instructions=False,
            update_knowledge=True,
        )
    )
    assert agent.knowledge_filters == {"team": "eng"}
    assert agent.enable_agentic_knowledge_filters is True
    assert agent.add_knowledge_to_context is True
    assert agent.references_format == "yaml"
    assert agent.search_knowledge is False
    assert agent.add_search_knowledge_instructions is False
    assert agent.update_knowledge is True


def test_knowledge_unset_config_fields_keep_defaults():
    agent = Agent(knowledge_config=KnowledgeConfig(add_to_context=True))
    assert agent.search_knowledge is True
    assert agent.references_format == "json"


# =============================================================================
# Parsing
# =============================================================================


def test_parsing_flat_params_unchanged():
    agent = Agent(parser_model_prompt="p", use_json_mode=True, parse_response=False)
    assert agent.parser_model_prompt == "p"
    assert agent.use_json_mode is True
    assert agent.parse_response is False


def test_parsing_config_resolves_to_flat_attributes():
    agent = Agent(
        parsing=ParsingConfig(
            parser_prompt="pp",
            output_prompt="op",
            parse_response=False,
            structured_outputs=True,
            use_json_mode=True,
        )
    )
    assert agent.parser_model_prompt == "pp"
    assert agent.output_model_prompt == "op"
    assert agent.parse_response is False
    assert agent.structured_outputs is True
    assert agent.use_json_mode is True


def test_parsing_unset_config_fields_keep_flat_values():
    agent = Agent(parsing=ParsingConfig(use_json_mode=True), parser_model_prompt="flat")
    assert agent.parser_model_prompt == "flat"
    assert agent.use_json_mode is True
    assert agent.parse_response is True


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


def test_reasoning_unset_config_fields_keep_flat_values():
    agent = Agent(reasoning=ReasoningConfig(max_steps=5), reasoning_min_steps=3)
    assert agent.reasoning_min_steps == 3
    assert agent.reasoning_max_steps == 5


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


def test_memory_unset_config_fields_keep_flat_values():
    agent = Agent(memory=MemoryConfig(agentic=True), update_memory_on_run=True)
    assert agent.enable_agentic_memory is True
    assert agent.update_memory_on_run is True


# =============================================================================
# Culture
# =============================================================================


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


def test_compression_manager_shorthand():
    manager = CompressionManager()
    agent = Agent(compress_tool_results=manager)
    assert agent.compress_tool_results is True
    assert agent.compression_manager is manager


# =============================================================================
# Followups
# =============================================================================


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


def test_retry_config_resolves_to_flat_attributes():
    agent = Agent(retry=RetryConfig(retries=4, delay=2, exponential_backoff=True))
    assert agent.retries == 4
    assert agent.delay_between_retries == 2
    assert agent.exponential_backoff is True


def test_retry_unset_config_fields_keep_flat_values():
    agent = Agent(retry=RetryConfig(retries=4), delay_between_retries=9)
    assert agent.retries == 4
    assert agent.delay_between_retries == 9


# =============================================================================
# Callable cache
# =============================================================================


def test_callable_cache_flat_params_unchanged():
    def key_fn(*args, **kwargs):
        return "k"

    agent = Agent(cache_callables=False, callable_tools_cache_key=key_fn)
    assert agent.cache_callables is False
    assert agent.callable_tools_cache_key is key_fn


def test_callable_cache_config_enables_caching():
    def key_fn(*args, **kwargs):
        return "k"

    agent = Agent(cache_callables=CallableCacheConfig(tools_cache_key=key_fn))
    assert agent.cache_callables is True
    assert agent.callable_tools_cache_key is key_fn


def test_callable_cache_members_key_unsupported_on_agent():
    def key_fn(*args, **kwargs):
        return "k"

    with patch("agno.config.log_warning") as mock_warning:
        Agent(cache_callables=CallableCacheConfig(members_cache_key=key_fn))
    assert any("members_cache_key" in str(call) for call in mock_warning.call_args_list)


# =============================================================================
# deep_copy round-trip
# =============================================================================


def test_deep_copy_round_trip_with_grouped_configs():
    agent = Agent(
        session=SessionConfig(id="s9", summaries=True),
        history=HistoryConfig(num_runs=7, search_past_sessions=True),
        reasoning=ReasoningConfig(max_steps=5),
        memory=True,
        storage=StorageConfig(history_messages=True),
        retry=RetryConfig(retries=3),
        followups=FollowupConfig(num=2),
    )
    copy = agent.deep_copy()
    assert copy.session_id == "s9"
    assert copy.enable_session_summaries is True
    assert copy.num_history_runs == 7
    assert copy.search_past_sessions is True
    assert copy.reasoning_max_steps == 5
    assert copy.update_memory_on_run is True
    assert copy.store_history_messages is True
    assert copy.retries == 3
    assert copy.num_followups == 2
