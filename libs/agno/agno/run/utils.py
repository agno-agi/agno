"""Shared helpers for run outputs.

The AgentOS MCP result layer and the Studio runner toolkit both build their
run-status and paused-requirement payloads from these helpers. The agent and
team continue dispatch and the AgentOS continue routes share the fork rule.
"""

from typing import Any, Dict, List, Optional, Union

from agno.run.base import RunStatus


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


def is_forking_continue(status: Union[RunStatus, str, None], *, fork: bool = False, regenerate: bool = False) -> bool:
    """Whether continuing a run executes under a new run id.

    An explicit fork or a regenerate always does, and a COMPLETED run auto-forks so its
    persisted row keeps a single model loop. The continue dispatch (agent + team), the
    background streamers and the AgentOS continue routes all decide from this, so none of
    them can predict a different run id than the one that executes.
    """
    return fork or regenerate or status == RunStatus.completed
