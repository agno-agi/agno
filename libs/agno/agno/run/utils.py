"""Shared serialization helpers for run outputs.

The AgentOS MCP result layer and the Studio runner toolkit both build their
run-status and paused-requirement payloads from these helpers.
"""

from typing import Any, Dict, List, Optional


def run_status_string(run_output: Any) -> str:
    """The run's status as its string value, defaulting to COMPLETED."""
    status = getattr(run_output, "status", None)
    value = getattr(status, "value", status)
    return str(value) if value is not None else "COMPLETED"


def serialized_paused_requirements(run_output: Any) -> Optional[List[Dict[str, Any]]]:
    """Serialized unresolved requirements when the run is paused, else None."""
    if not getattr(run_output, "is_paused", False):
        return None
    # Agents/teams expose active_requirements; workflows expose active_step_requirements.
    requirements = (
        getattr(run_output, "active_requirements", None) or getattr(run_output, "active_step_requirements", None) or []
    )
    serialized: List[Dict[str, Any]] = []
    for requirement in requirements:
        if hasattr(requirement, "to_dict"):
            serialized.append(requirement.to_dict())
        elif isinstance(requirement, dict):
            serialized.append(requirement)
    return serialized or None
