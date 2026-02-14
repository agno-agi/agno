"""Backward-compatible re-exports from agno.metrics.

All metric classes now live in agno.metrics.  This shim keeps
``from agno.models.metrics import Metrics`` working everywhere.
"""

from agno.metrics import (  # noqa: F401
    MessageMetrics,
    Metrics,
    ModelMetrics,
    RunMetrics,
    SessionMetrics,
    SessionModelMetrics,
    ToolCallMetrics,
    accumulate_model_metrics,
)

# Explicit re-export for type checkers
__all__ = [
    "Metrics",
    "RunMetrics",
    "MessageMetrics",
    "ModelMetrics",
    "SessionMetrics",
    "SessionModelMetrics",
    "ToolCallMetrics",
    "accumulate_model_metrics",
]
