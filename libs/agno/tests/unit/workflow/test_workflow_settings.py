"""
Unit tests for grouped settings dataclasses on Workflow.

Tests cover:
- Grouped construction: Workflow(session_settings=SessionSettings(...)) sets the flat attributes
- Equivalence: grouped construction produces the same workflow as flat construction
- Precedence: a set settings field wins over the flat kwarg, even when its value
  equals the flat default; unset (None) settings fields fall back to the flat kwarg
- Warnings: the conflict warning fires only when both values are set and differ,
  and settings fields not supported by Workflow are ignored with a warning
- Parity: every supported settings field maps to a Workflow.__init__ parameter with
  a matching flat default, and every supported field is exercised by a test case
- Serialization: to_dict stays flat, from_dict and deep_copy round-trip unchanged
"""

from dataclasses import fields
from inspect import signature
from unittest.mock import patch

from agno.run.workflow import WorkflowRunEvent
from agno.session import SessionSummaryManager
from agno.settings import (
    DebugSettings,
    EventSettings,
    SessionSettings,
)
from agno.workflow.workflow import Workflow

WORKFLOW_SETTINGS_CLASSES = [
    SessionSettings,
    EventSettings,
    DebugSettings,
]


# Non-default values for every scalar settings field supported by Workflow.
# Object fields (events) are covered by WORKFLOW_OBJECT_CASES below.
WORKFLOW_GROUP_CASES = {
    "session_settings": (
        SessionSettings,
        {
            "session_id": "session-123",
            "session_state": {"key": "value"},
            "add_session_state_to_context": True,
            "overwrite_db_session_state": True,
            "cache_session": True,
        },
    ),
    "event_settings": (
        EventSettings,
        {
            "stream": True,
            "stream_events": True,
            "stream_executor_events": False,
            "store_events": True,
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
}

# Object values for the settings fields not covered by the scalar cases above.
# Factories so each test gets fresh instances.
WORKFLOW_OBJECT_CASES = {
    "event_settings": (EventSettings, lambda: {"events_to_skip": [WorkflowRunEvent.workflow_started]}),
}

# Settings fields that intentionally have no matching Workflow.__init__ parameter
WORKFLOW_PARITY_EXCEPTIONS = {
    "enable_agentic_state",
    "search_past_sessions",
    "num_past_sessions_to_search",
    "num_past_session_runs_in_search",
    "enable_session_summaries",
    "add_session_summary_to_context",
    "session_summary_manager",
}

# Settings fields intentionally not exercised by the cases above
WORKFLOW_COVERAGE_EXCEPTIONS = WORKFLOW_PARITY_EXCEPTIONS

# Workflow's flat defaults differ from Agent's here; the resolve calls pass these explicitly
WORKFLOW_DEFAULT_OVERRIDES = {"add_session_state_to_context": None, "stream_events": False}


# =============================================================================
# Grouped construction and equivalence
# =============================================================================


def test_grouped_construction_sets_flat_attributes():
    for group_kwarg, (settings_cls, values) in WORKFLOW_GROUP_CASES.items():
        workflow = Workflow(**{group_kwarg: settings_cls(**values)})
        for name, expected in values.items():
            assert getattr(workflow, name) == expected, f"{group_kwarg}.{name}"


def test_grouped_construction_matches_flat_construction():
    for group_kwarg, (settings_cls, values) in WORKFLOW_GROUP_CASES.items():
        grouped = Workflow(**{group_kwarg: settings_cls(**values)})
        flat = Workflow(**values)
        for name in values:
            assert getattr(grouped, name) == getattr(flat, name), f"{group_kwarg}.{name}"


def test_object_fields_match_flat_construction():
    for group_kwarg, (settings_cls, make_values) in WORKFLOW_OBJECT_CASES.items():
        values = make_values()
        grouped = Workflow(**{group_kwarg: settings_cls(**values)})
        flat = Workflow(**values)
        for name in values:
            assert getattr(grouped, name) == getattr(flat, name), f"{group_kwarg}.{name}"


def test_mutating_settings_after_construction_does_not_affect_workflow():
    settings = SessionSettings(session_id="before")
    workflow = Workflow(session_settings=settings)
    settings.session_id = "after"
    assert workflow.session_id == "before"


# =============================================================================
# Precedence and unsupported fields
# =============================================================================


def test_settings_object_wins_over_flat_kwarg():
    workflow = Workflow(session_id="flat-id", session_settings=SessionSettings(session_id="grouped-id"))
    assert workflow.session_id == "grouped-id"


def test_settings_value_wins_even_when_it_equals_the_flat_default():
    workflow = Workflow(store_events=True, event_settings=EventSettings(store_events=False))
    assert workflow.store_events is False
    workflow = Workflow(debug_mode=True, debug_settings=DebugSettings(debug_mode=False))
    assert workflow.debug_mode is False


def test_flat_kwarg_used_when_settings_field_unset():
    workflow = Workflow(session_id="flat-id", session_settings=SessionSettings(cache_session=True))
    assert workflow.session_id == "flat-id"
    assert workflow.cache_session is True


def test_unsupported_fields_are_ignored_by_workflow():
    with patch("agno.settings.log_warning") as mock_warning:
        workflow = Workflow(
            session_settings=SessionSettings(
                enable_session_summaries=True,
                session_summary_manager=SessionSummaryManager(),
            )
        )
    # No such attributes leak onto Workflow
    assert "enable_session_summaries" not in workflow.__dict__
    assert "session_summary_manager" not in workflow.__dict__
    # Each ignored field is warned about
    warnings = " ".join(str(call) for call in mock_warning.call_args_list)
    assert "enable_session_summaries" in warnings
    assert "session_summary_manager" in warnings


# =============================================================================
# Warnings
# =============================================================================


def test_conflict_warning_fires_when_values_differ():
    with patch("agno.settings.log_warning") as mock_warning:
        Workflow(session_id="flat-id", session_settings=SessionSettings(session_id="grouped-id"))
    assert any("session_id" in str(call) for call in mock_warning.call_args_list)


def test_no_warning_when_values_agree():
    with patch("agno.settings.log_warning") as mock_warning:
        Workflow(store_events=True, event_settings=EventSettings(store_events=True))
    assert mock_warning.call_count == 0


def test_no_warning_when_only_settings_set():
    with patch("agno.settings.log_warning") as mock_warning:
        Workflow(debug_settings=DebugSettings(debug_mode=True))
    assert mock_warning.call_count == 0


# =============================================================================
# Parity: supported settings fields must not drift from Workflow.__init__ parameters
# =============================================================================


def test_settings_fields_match_workflow_init_params():
    init_params = set(signature(Workflow.__init__).parameters) - {"self"}
    for settings_cls in WORKFLOW_SETTINGS_CLASSES:
        for f in fields(settings_cls):
            if f.name in WORKFLOW_PARITY_EXCEPTIONS:
                continue
            assert f.name in init_params, f"{settings_cls.__name__}.{f.name} is not a Workflow.__init__ param"


def test_settings_flat_defaults_match_workflow_init_defaults():
    init_params = signature(Workflow.__init__).parameters
    for settings_cls in WORKFLOW_SETTINGS_CLASSES:
        for f in fields(settings_cls):
            if f.name not in init_params:
                continue
            assert f.default is None, f"{settings_cls.__name__}.{f.name} must default to None (unset)"
            if f.name in WORKFLOW_DEFAULT_OVERRIDES:
                flat_default = WORKFLOW_DEFAULT_OVERRIDES[f.name]
            else:
                flat_default = f.metadata.get("flat_default")
            init_default = init_params[f.name].default
            assert flat_default == init_default, (
                f"{settings_cls.__name__}.{f.name} flat_default {flat_default!r} != Workflow default {init_default!r}"
            )


def test_every_supported_settings_field_is_covered_by_a_case():
    covered = {cls: set() for cls in WORKFLOW_SETTINGS_CLASSES}
    for _, (settings_cls, values) in WORKFLOW_GROUP_CASES.items():
        covered[settings_cls].update(values)
    for _, (settings_cls, make_values) in WORKFLOW_OBJECT_CASES.items():
        covered[settings_cls].update(make_values())
    for settings_cls in WORKFLOW_SETTINGS_CLASSES:
        for f in fields(settings_cls):
            assert f.name in covered[settings_cls] or f.name in WORKFLOW_COVERAGE_EXCEPTIONS, (
                f"{settings_cls.__name__}.{f.name} is not exercised by any test case"
            )


def test_group_kwargs_exist_on_workflow_init():
    init_params = set(signature(Workflow.__init__).parameters)
    for group_kwarg in WORKFLOW_GROUP_CASES:
        assert group_kwarg in init_params


# =============================================================================
# Serialization and copying stay flat
# =============================================================================


def test_to_dict_stays_flat_with_grouped_construction():
    workflow = Workflow(
        id="workflow-1",
        session_settings=SessionSettings(session_id="session-456"),
        event_settings=EventSettings(stream_events=True, store_events=True),
    )
    config = workflow.to_dict()
    assert config["session_id"] == "session-456"
    assert config["stream_events"] is True
    assert config["store_events"] is True
    assert "session_settings" not in config
    assert "event_settings" not in config


def test_from_dict_round_trip_after_grouped_construction():
    workflow = Workflow(id="workflow-1", session_settings=SessionSettings(session_id="session-456"))
    restored = Workflow.from_dict(workflow.to_dict())
    assert restored.session_id == "session-456"


def test_deep_copy_preserves_grouped_values():
    workflow = Workflow(
        id="workflow-1",
        session_settings=SessionSettings(session_id="session-456", cache_session=True),
        event_settings=EventSettings(stream_executor_events=False, store_events=True),
    )
    copied = workflow.deep_copy()
    assert copied.session_id == "session-456"
    assert copied.cache_session is True
    assert copied.stream_executor_events is False
    assert copied.store_events is True
