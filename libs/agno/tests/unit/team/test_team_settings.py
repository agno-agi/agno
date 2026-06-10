"""
Unit tests for grouped settings dataclasses on Team.

Tests cover:
- Grouped construction: Team(session_settings=SessionSettings(...)) sets the flat attributes
- Equivalence: grouped construction produces the same team as flat construction
- Precedence: a set settings field wins over the flat kwarg, even when its value
  equals the flat default; unset (None) settings fields fall back to the flat kwarg
- Warnings: the conflict warning fires only when both values are set and differ,
  and Agent-only settings fields are ignored by Team with a warning
- Parity: every settings field maps to a Team.__init__ parameter with a matching
  flat default, and every field is exercised by a test case (no drift)
- Serialization: to_dict stays flat, deep_copy round-trips unchanged
"""

from dataclasses import fields
from inspect import signature
from unittest.mock import patch

from pydantic import BaseModel

from agno.agent.agent import Agent
from agno.compression.manager import CompressionManager
from agno.memory import MemoryManager
from agno.models.fallback import FallbackConfig
from agno.run.team import TeamRunEvent
from agno.session import SessionSummaryManager
from agno.settings import (
    CacheSettings,
    CompressionSettings,
    ContextSettings,
    DebugSettings,
    DelegationSettings,
    EventSettings,
    FollowupSettings,
    HistorySettings,
    KnowledgeSettings,
    LearningSettings,
    MemorySettings,
    ModelSettings,
    OutputSettings,
    ReasoningSettings,
    RetrySettings,
    SessionSettings,
    StorageSettings,
    ToolSettings,
)
from agno.team.mode import TeamMode
from agno.team.team import Team

TEAM_SETTINGS_CLASSES = [
    ModelSettings,
    SessionSettings,
    ContextSettings,
    KnowledgeSettings,
    MemorySettings,
    HistorySettings,
    OutputSettings,
    ToolSettings,
    ReasoningSettings,
    StorageSettings,
    EventSettings,
    FollowupSettings,
    RetrySettings,
    DebugSettings,
    CompressionSettings,
    CacheSettings,
    DelegationSettings,
    LearningSettings,
]


class OutputSchema(BaseModel):
    answer: str


class StubKnowledge:
    pass


def _knowledge_retriever(team, query, num_documents=None, **kwargs):
    return None


def _tool_hook(function_name, function_call, arguments):
    return function_call(**arguments)


def _cache_key(*args, **kwargs):
    return "cache-key"


# Non-default values for every scalar settings field supported by Team.
# Object fields (managers, models, callables) are covered by TEAM_OBJECT_CASES below.
TEAM_GROUP_CASES = {
    "session_settings": (
        SessionSettings,
        {
            "session_id": "session-123",
            "session_state": {"key": "value"},
            "add_session_state_to_context": True,
            "enable_agentic_state": True,
            "overwrite_db_session_state": True,
            "cache_session": True,
            "search_past_sessions": True,
            "num_past_sessions_to_search": 4,
            "num_past_session_runs_in_search": 2,
            "enable_session_summaries": True,
            "add_session_summary_to_context": True,
        },
    ),
    "context_settings": (
        ContextSettings,
        {
            "markdown": True,
            "add_name_to_context": True,
            "add_datetime_to_context": True,
            "add_location_to_context": True,
            "datetime_format": "%Y-%m-%d",
            "timezone_identifier": "Etc/UTC",
            "resolve_in_context": False,
            "additional_context": "extra context",
            "additional_input": ["example input"],
            "dependencies": {"dep": 1},
            "add_dependencies_to_context": True,
            "use_instruction_tags": True,
            "system_message_role": "developer",
        },
    ),
    "knowledge_settings": (
        KnowledgeSettings,
        {
            "knowledge_filters": {"topic": "ai"},
            "enable_agentic_knowledge_filters": True,
            "add_knowledge_to_context": True,
            "references_format": "yaml",
            "search_knowledge": False,
            "add_search_knowledge_instructions": False,
            "update_knowledge": True,
        },
    ),
    "memory_settings": (
        MemorySettings,
        {
            "enable_agentic_memory": True,
            "update_memory_on_run": True,
            "add_memories_to_context": True,
        },
    ),
    "history_settings": (
        HistorySettings,
        {
            "add_history_to_context": True,
            "num_history_runs": 7,
            "max_tool_calls_from_history": 5,
            "read_chat_history": True,
        },
    ),
    "output_settings": (
        OutputSettings,
        {
            "input_schema": OutputSchema,
            "output_schema": OutputSchema,
            "parser_model_prompt": "parse this",
            "output_model_prompt": "structure this",
            "parse_response": False,
            "use_json_mode": True,
        },
    ),
    "tool_settings": (
        ToolSettings,
        {
            "tool_call_limit": 4,
            "tool_choice": "auto",
            "send_media_to_model": False,
        },
    ),
    "reasoning_settings": (
        ReasoningSettings,
        {
            "reasoning": True,
            "reasoning_min_steps": 2,
            "reasoning_max_steps": 7,
        },
    ),
    "storage_settings": (
        StorageSettings,
        {
            "store_media": False,
            "store_tool_messages": False,
            "store_history_messages": True,
        },
    ),
    "event_settings": (
        EventSettings,
        {
            "stream": True,
            "stream_events": True,
            "store_events": True,
        },
    ),
    "followup_settings": (
        FollowupSettings,
        {
            "followups": True,
            "num_followups": 2,
        },
    ),
    "retry_settings": (
        RetrySettings,
        {
            "retries": 3,
            "delay_between_retries": 2,
            "exponential_backoff": True,
        },
    ),
    "debug_settings": (
        DebugSettings,
        {
            "debug_mode": True,
            "debug_level": 2,
            "telemetry": False,
        },
    ),
    "compression_settings": (
        CompressionSettings,
        {
            "compress_tool_results": True,
        },
    ),
    "cache_settings": (
        CacheSettings,
        {
            "cache_callables": False,
        },
    ),
    "delegation_settings": (
        DelegationSettings,
        {
            "mode": TeamMode.route,
            "determine_input_for_members": False,
            "max_iterations": 5,
            "add_team_history_to_members": True,
            "num_team_history_runs": 6,
            "share_member_interactions": True,
            "add_member_tools_to_context": True,
            "get_member_information_tool": True,
            "store_member_responses": True,
            "stream_member_events": False,
            "show_members_responses": True,
        },
    ),
    "learning_settings": (
        LearningSettings,
        {
            "learning": True,
            "add_learnings_to_context": False,
        },
    ),
}

# Object values for the settings fields not covered by the scalar cases above.
# Factories so each test gets fresh instances.
TEAM_OBJECT_CASES = {
    "model_settings": (ModelSettings, lambda: {"model": "openai:gpt-5.4"}),
    "session_settings": (SessionSettings, lambda: {"session_summary_manager": SessionSummaryManager()}),
    "knowledge_settings": (
        KnowledgeSettings,
        lambda: {"knowledge": StubKnowledge(), "knowledge_retriever": _knowledge_retriever},
    ),
    "memory_settings": (MemorySettings, lambda: {"memory_manager": MemoryManager()}),
    # num_history_messages is mutually exclusive with num_history_runs, so it gets its own case
    "history_settings": (HistorySettings, lambda: {"num_history_messages": 9}),
    "tool_settings": (ToolSettings, lambda: {"tool_hooks": [_tool_hook]}),
    "reasoning_settings": (
        ReasoningSettings,
        lambda: {"reasoning_model": "openai:gpt-5.4", "reasoning_agent": Agent(name="reasoning-agent")},
    ),
    "output_settings": (OutputSettings, lambda: {"parser_model": "openai:gpt-5.4", "output_model": "openai:gpt-5.4"}),
    "event_settings": (EventSettings, lambda: {"events_to_skip": [TeamRunEvent.run_started]}),
    "followup_settings": (FollowupSettings, lambda: {"followup_model": "openai:gpt-5.4"}),
    "compression_settings": (CompressionSettings, lambda: {"compression_manager": CompressionManager()}),
    "cache_settings": (
        CacheSettings,
        lambda: {
            "callable_tools_cache_key": _cache_key,
            "callable_knowledge_cache_key": _cache_key,
            "callable_members_cache_key": _cache_key,
        },
    ),
    # respond_directly and delegate_to_all_members conflict with mode normalization, so they get their own case
    "delegation_settings": (DelegationSettings, lambda: {"respond_directly": True, "delegate_to_all_members": True}),
}

# Settings fields that intentionally have no matching Team.__init__ parameter (Agent only)
TEAM_PARITY_EXCEPTIONS = {
    "user_message_role",
    "build_context",
    "build_user_context",
    "read_tool_call_history",
    "structured_outputs",
    "save_response_to_file",
    "stream_executor_events",
}

# Settings fields intentionally not exercised by the cases above
TEAM_COVERAGE_EXCEPTIONS = TEAM_PARITY_EXCEPTIONS | {
    # fallback_models is folded into fallback_config by the model wiring; covered by dedicated tests
    "fallback_models",
    "fallback_config",
}


def _member() -> Agent:
    return Agent(name="member")


# =============================================================================
# Grouped construction and equivalence
# =============================================================================


def test_grouped_construction_sets_flat_attributes():
    for group_kwarg, (settings_cls, values) in TEAM_GROUP_CASES.items():
        team = Team(members=[_member()], **{group_kwarg: settings_cls(**values)})
        for name, expected in values.items():
            assert getattr(team, name) == expected, f"{group_kwarg}.{name}"


def test_grouped_construction_matches_flat_construction():
    for group_kwarg, (settings_cls, values) in TEAM_GROUP_CASES.items():
        grouped = Team(members=[_member()], **{group_kwarg: settings_cls(**values)})
        flat = Team(members=[_member()], **values)
        for name in values:
            assert getattr(grouped, name) == getattr(flat, name), f"{group_kwarg}.{name}"


def test_object_fields_match_flat_construction():
    for group_kwarg, (settings_cls, make_values) in TEAM_OBJECT_CASES.items():
        values = make_values()
        grouped = Team(members=[_member()], **{group_kwarg: settings_cls(**values)})
        flat = Team(members=[_member()], **values)
        for name in values:
            assert getattr(grouped, name) == getattr(flat, name), f"{group_kwarg}.{name}"


def test_mode_normalization_runs_on_resolved_values():
    # mode=route sets respond_directly via the existing _init normalization
    team = Team(members=[_member()], delegation_settings=DelegationSettings(mode=TeamMode.route))
    assert team.respond_directly is True


def test_model_settings_fallback_models_match_flat_construction():
    grouped = Team(
        members=[_member()],
        model_settings=ModelSettings(model="openai:gpt-5.4", fallback_models=["openai:gpt-5.4-mini"]),
    )
    flat = Team(members=[_member()], model="openai:gpt-5.4", fallback_models=["openai:gpt-5.4-mini"])
    assert grouped.fallback_config == flat.fallback_config


def test_flat_fallback_config_wins_over_grouped_fallback_models():
    # Cross-parameter normalization runs on the resolved values: fallback_config
    # takes precedence over fallback_models regardless of how they were passed
    fallback_config = FallbackConfig(on_error=["openai:gpt-5.4-mini"])
    team = Team(
        members=[_member()],
        model="openai:gpt-5.4",
        fallback_config=fallback_config,
        model_settings=ModelSettings(fallback_models=["openai:gpt-5.4-nano"]),
    )
    assert team.fallback_config is fallback_config


def test_mutating_settings_after_construction_does_not_affect_team():
    settings = SessionSettings(session_id="before")
    team = Team(members=[_member()], session_settings=settings)
    settings.session_id = "after"
    assert team.session_id == "before"


# =============================================================================
# Precedence and unsupported fields
# =============================================================================


def test_settings_object_wins_over_flat_kwarg():
    team = Team(members=[_member()], session_id="flat-id", session_settings=SessionSettings(session_id="grouped-id"))
    assert team.session_id == "grouped-id"


def test_settings_value_wins_even_when_it_equals_the_flat_default():
    team = Team(members=[_member()], retries=3, retry_settings=RetrySettings(retries=0))
    assert team.retries == 0
    team = Team(
        members=[_member()],
        determine_input_for_members=False,
        delegation_settings=DelegationSettings(determine_input_for_members=True),
    )
    assert team.determine_input_for_members is True
    team = Team(
        members=[_member()],
        stream_member_events=False,
        delegation_settings=DelegationSettings(stream_member_events=True),
    )
    assert team.stream_member_events is True


def test_flat_kwarg_used_when_settings_field_unset():
    team = Team(members=[_member()], session_id="flat-id", session_settings=SessionSettings(cache_session=True))
    assert team.session_id == "flat-id"
    assert team.cache_session is True


def test_agent_only_fields_are_ignored_by_team():
    with patch("agno.settings.log_warning") as mock_warning:
        team = Team(
            members=[_member()],
            context_settings=ContextSettings(build_context=False),
            output_settings=OutputSettings(structured_outputs=True),
            history_settings=HistorySettings(read_tool_call_history=True),
        )
    # No such attributes leak onto Team
    assert "build_context" not in team.__dict__
    assert "structured_outputs" not in team.__dict__
    assert "read_tool_call_history" not in team.__dict__
    # Each ignored field is warned about
    warnings = " ".join(str(call) for call in mock_warning.call_args_list)
    assert "build_context" in warnings
    assert "structured_outputs" in warnings
    assert "read_tool_call_history" in warnings


# =============================================================================
# Warnings
# =============================================================================


def test_conflict_warning_fires_when_values_differ():
    with patch("agno.settings.log_warning") as mock_warning:
        Team(members=[_member()], session_id="flat-id", session_settings=SessionSettings(session_id="grouped-id"))
    assert any("session_id" in str(call) for call in mock_warning.call_args_list)


def test_no_warning_when_values_agree():
    with patch("agno.settings.log_warning") as mock_warning:
        Team(
            members=[_member()],
            enable_agentic_knowledge_filters=True,
            knowledge_settings=KnowledgeSettings(enable_agentic_knowledge_filters=True),
        )
    assert mock_warning.call_count == 0


def test_no_warning_when_only_settings_set():
    with patch("agno.settings.log_warning") as mock_warning:
        Team(members=[_member()], delegation_settings=DelegationSettings(max_iterations=5))
    assert mock_warning.call_count == 0


# =============================================================================
# Parity: settings fields must not drift from Team.__init__ parameters
# =============================================================================


def test_settings_fields_match_team_init_params():
    init_params = set(signature(Team.__init__).parameters) - {"self"}
    for settings_cls in TEAM_SETTINGS_CLASSES:
        for f in fields(settings_cls):
            if f.name in TEAM_PARITY_EXCEPTIONS:
                continue
            assert f.name in init_params, f"{settings_cls.__name__}.{f.name} is not a Team.__init__ param"


def test_settings_flat_defaults_match_team_init_defaults():
    init_params = signature(Team.__init__).parameters
    for settings_cls in TEAM_SETTINGS_CLASSES:
        for f in fields(settings_cls):
            if f.name not in init_params:
                continue
            assert f.default is None, f"{settings_cls.__name__}.{f.name} must default to None (unset)"
            # Team's flat default differs from Agent's here; the resolve call passes flat_default=False
            if f.name == "enable_agentic_knowledge_filters":
                continue
            flat_default = f.metadata.get("flat_default")
            init_default = init_params[f.name].default
            assert flat_default == init_default, (
                f"{settings_cls.__name__}.{f.name} flat_default {flat_default!r} != Team default {init_default!r}"
            )


def test_every_settings_field_is_covered_by_a_case():
    covered = {cls: set() for cls in TEAM_SETTINGS_CLASSES}
    for _, (settings_cls, values) in TEAM_GROUP_CASES.items():
        covered[settings_cls].update(values)
    for _, (settings_cls, make_values) in TEAM_OBJECT_CASES.items():
        covered[settings_cls].update(make_values())
    for settings_cls in TEAM_SETTINGS_CLASSES:
        for f in fields(settings_cls):
            assert f.name in covered[settings_cls] or f.name in TEAM_COVERAGE_EXCEPTIONS, (
                f"{settings_cls.__name__}.{f.name} is not exercised by any test case"
            )


def test_group_kwargs_exist_on_team_init():
    init_params = set(signature(Team.__init__).parameters)
    for group_kwarg in list(TEAM_GROUP_CASES) + ["model_settings"]:
        assert group_kwarg in init_params
    # Culture is Agent-only and must not be a Team kwarg
    assert "culture_settings" not in init_params


# =============================================================================
# Serialization and copying stay flat
# =============================================================================


def test_to_dict_stays_flat_with_grouped_construction():
    team = Team(
        members=[_member()],
        id="team-1",
        session_settings=SessionSettings(session_id="session-456", cache_session=True),
        context_settings=ContextSettings(markdown=True),
    )
    config = team.to_dict()
    assert config["session_id"] == "session-456"
    assert config["markdown"] is True
    assert "session_settings" not in config
    assert "context_settings" not in config


def test_deep_copy_preserves_grouped_values():
    team = Team(
        members=[_member()],
        id="team-1",
        session_settings=SessionSettings(session_id="session-456"),
        delegation_settings=DelegationSettings(max_iterations=5),
    )
    copied = team.deep_copy()
    assert copied.session_id == "session-456"
    assert copied.max_iterations == 5
