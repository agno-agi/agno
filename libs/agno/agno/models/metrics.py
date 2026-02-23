"""Backward-compatible re-exports from agno.metrics.

All metric classes now live in agno.metrics.  This shim keeps
``from agno.models.metrics import Metrics`` working everywhere.
"""

from agno.metrics import (  # noqa: F401
    BaseMetrics,
    MessageMetrics,
    Metrics,
    ModelMetrics,
    ModelType,
    RunMetrics,
    SessionMetrics,
    ToolCallMetrics,
    accumulate_eval_metrics,
    accumulate_model_metrics,
)

# Explicit re-export for type checkers
__all__ = [
    "BaseMetrics",
    "MessageMetrics",
    "Metrics",
    "ModelMetrics",
    "ModelType",
    "RunMetrics",
    "SessionMetrics",
    "ToolCallMetrics",
    "accumulate_eval_metrics",
    "accumulate_model_metrics",
]
