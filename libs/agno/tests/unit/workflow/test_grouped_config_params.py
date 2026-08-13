"""Unit tests for grouped config parameters on Workflow (history, session, storage)."""

from unittest.mock import patch

import pytest

from agno.config import HistoryConfig, SessionConfig, StorageConfig
from agno.workflow import Workflow


def test_constructor_is_keyword_only():
    with pytest.raises(TypeError):
        Workflow("some-id")  # type: ignore[misc]


def test_flat_params_unchanged():
    workflow = Workflow(name="w", add_workflow_history_to_steps=True, num_history_runs=5)
    assert workflow.add_workflow_history_to_steps is True
    assert workflow.num_history_runs == 5


def test_history_config_resolves_to_flat_attributes():
    workflow = Workflow(name="w", history=HistoryConfig(num_runs=7))
    assert workflow.add_workflow_history_to_steps is True
    assert workflow.num_history_runs == 7


def test_history_bool_only_flips_master_switch():
    workflow = Workflow(name="w", history=True, num_history_runs=9)
    assert workflow.add_workflow_history_to_steps is True
    assert workflow.num_history_runs == 9


def test_history_config_wins_over_flat_params_with_warning():
    with patch("agno.config.log_warning") as mock_warning:
        workflow = Workflow(name="w", history=HistoryConfig(num_runs=4), num_history_runs=8)
    assert workflow.num_history_runs == 4
    assert any("num_history_runs" in str(call) for call in mock_warning.call_args_list)


def test_history_unsupported_fields_warn_on_workflow():
    with patch("agno.config.log_warning") as mock_warning:
        Workflow(name="w", history=HistoryConfig(read_chat_history=True))
    assert any("read_chat_history" in str(call) for call in mock_warning.call_args_list)


def test_session_config_resolves_to_flat_attributes():
    workflow = Workflow(name="w", session=SessionConfig(id="ws", state={"a": 1}, cache=True, overwrite_db_state=True))
    assert workflow.session_id == "ws"
    assert workflow.session_state == {"a": 1}
    assert workflow.cache_session is True
    assert workflow.overwrite_db_session_state is True


def test_session_unset_config_fields_keep_flat_values():
    workflow = Workflow(name="w", session=SessionConfig(id="ws2"), session_state={"b": 2})
    assert workflow.session_id == "ws2"
    assert workflow.session_state == {"b": 2}


def test_session_unsupported_fields_warn_on_workflow():
    with patch("agno.config.log_warning") as mock_warning:
        Workflow(name="w", session=SessionConfig(summaries=True))
    assert any("summaries" in str(call) for call in mock_warning.call_args_list)


def test_storage_config_resolves_to_flat_attributes():
    workflow = Workflow(name="w", storage=StorageConfig(events=True, executor_outputs=False))
    assert workflow.store_events is True
    assert workflow.store_executor_outputs is False
    assert workflow.events_to_skip == []


def test_storage_unsupported_fields_warn_on_workflow():
    with patch("agno.config.log_warning") as mock_warning:
        Workflow(name="w", storage=StorageConfig(media=False))
    assert any("media" in str(call) for call in mock_warning.call_args_list)


def test_defaults_unchanged():
    workflow = Workflow(name="w")
    assert workflow.add_workflow_history_to_steps is False
    assert workflow.num_history_runs == 3
    assert workflow.debug_level == 1
    assert workflow.cache_session is False
    assert workflow.store_executor_outputs is True
    assert workflow.add_session_state_to_context is None
