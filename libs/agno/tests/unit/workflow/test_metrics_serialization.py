"""
Unit tests for WorkflowMetrics and StepMetrics serialization/deserialization."""

from agno.workflow.types import StepMetrics, WorkflowMetrics

# =============================================================================
# WorkflowMetrics.from_dict backward compatibility
# =============================================================================


def test_workflow_metrics_from_dict_missing_steps():
    """Older payloads may not include a "steps" key at all.

    This used to raise KeyError: 'steps'.
    """
    metrics = WorkflowMetrics.from_dict({"duration": 1.23})

    assert metrics.steps == {}
    assert metrics.duration == 1.23


def test_workflow_metrics_from_dict_empty():
    """A completely empty payload should not crash."""
    metrics = WorkflowMetrics.from_dict({})

    assert metrics.steps == {}
    assert metrics.duration is None


def test_workflow_metrics_from_dict_roundtrip():
    """A normally-serialized payload should deserialize with steps intact."""
    payload = {
        "steps": {
            "step_1": {
                "step_name": "step_1",
                "executor_type": "agent",
                "executor_name": "my_agent",
                "metrics": None,
            }
        },
        "duration": 2.5,
    }

    metrics = WorkflowMetrics.from_dict(payload)

    assert set(metrics.steps.keys()) == {"step_1"}
    assert metrics.steps["step_1"].step_name == "step_1"
    assert metrics.steps["step_1"].executor_type == "agent"
    assert metrics.steps["step_1"].executor_name == "my_agent"
    assert metrics.duration == 2.5


# =============================================================================
# StepMetrics.from_dict backward compatibility
# =============================================================================


def test_step_metrics_from_dict_missing_required_fields():
    """Older/partial step payloads may omit required fields.

    This used to raise KeyError on step_name/executor_type/executor_name.
    """
    step = StepMetrics.from_dict({})

    assert step.step_name == ""
    assert step.executor_type == ""
    assert step.executor_name == ""
    assert step.metrics is None


def test_step_metrics_from_dict_partial_fields():
    """A payload with only some fields present should fill the rest with defaults."""
    step = StepMetrics.from_dict({"step_name": "step_1"})

    assert step.step_name == "step_1"
    assert step.executor_type == ""
    assert step.executor_name == ""
