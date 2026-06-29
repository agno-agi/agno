"""Shared utilities for agent / team / workflow run loops."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Union

if TYPE_CHECKING:
    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput
    from agno.run.workflow import WorkflowRunOutput
    from agno.session.agent import AgentSession
    from agno.session.team import TeamSession
    from agno.session.workflow import WorkflowSession


def resolve_run_index(
    session: Union["AgentSession", "TeamSession", "WorkflowSession"],
    run: Union["RunOutput", "TeamRunOutput", "WorkflowRunOutput", Any],
) -> Optional[int]:
    """Find the position of ``run`` within ``session.runs``.

    Called after ``session.upsert_run(...)``. Returns the 0-based index of the
    run that matches ``run.run_id``. Falls back to ``len(runs) - 1`` if no match
    is found (defensive: upsert_run always places the run somewhere). Returns
    ``None`` if there are no runs.

    Used by the agent / team / workflow run loops to pass ``run_index`` to
    ``save_run`` / ``asave_run`` so the runs table row gets a meaningful index
    instead of NULL.
    """
    runs = session.runs or []
    if not runs:
        return None

    target_id = getattr(run, "run_id", None)
    if target_id is None and isinstance(run, dict):
        target_id = run.get("run_id")

    if target_id is not None:
        for idx, existing in enumerate(runs):
            existing_id = (
                existing.get("run_id") if isinstance(existing, dict) else getattr(existing, "run_id", None)
            )
            if existing_id == target_id:
                return idx
    return len(runs) - 1
