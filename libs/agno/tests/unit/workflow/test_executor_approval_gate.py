"""Workflow continue must honor @approval(type='required') before applying client HITL."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agno.workflow.workflow import _ensure_executor_approval_resolved


def test_ensure_executor_approval_resolved_runs_before_client_can_confirm():
    executor = SimpleNamespace(db=object())
    paused = SimpleNamespace(run_id="executor-run-1", tools=[], requirements=[])

    with patch(
        "agno.run.approval.check_and_apply_approval_resolution",
        side_effect=RuntimeError("Approval is still pending. Resolve the approval before continuing this run."),
    ) as mock_check:
        with pytest.raises(RuntimeError, match="still pending"):
            _ensure_executor_approval_resolved(executor, paused, "executor-run-1")
        mock_check.assert_called_once_with(executor.db, "executor-run-1", paused)


def test_ensure_executor_approval_resolved_noops_without_run_id():
    executor = SimpleNamespace(db=object())
    paused = SimpleNamespace(run_id=None)
    with patch("agno.run.approval.check_and_apply_approval_resolution") as mock_check:
        _ensure_executor_approval_resolved(executor, paused, None)
        mock_check.assert_not_called()
