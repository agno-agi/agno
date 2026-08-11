"""Unit tests for the grouped history parameter on Workflow."""

from unittest.mock import patch

from agno.config import HistoryConfig
from agno.workflow import Workflow


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
    mock_warning.assert_called_once()


def test_defaults_unchanged():
    workflow = Workflow(name="w")
    assert workflow.add_workflow_history_to_steps is False
    assert workflow.num_history_runs == 3
    assert workflow.debug_level == 1
    assert workflow.cache_session is False
