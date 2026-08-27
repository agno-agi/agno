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

    Called after ``session.upsert_run(...)``: returns the 0-based index of the
    run that matches ``run.run_id``. Returns ``None`` when the run cannot be
    located (missing ``run_id``, no runs on the session, or ``run_id`` not
    present in ``session.runs``) — callers pass the result straight through to
    ``save_run``/``asave_run`` as ``run_index``, so ``None`` stores NULL rather
    than silently colliding with an unrelated run's position.
    """
    runs = session.runs or []
    if not runs:
        return None

    target_id = getattr(run, "run_id", None)
    if target_id is None and isinstance(run, dict):
        target_id = run.get("run_id")

    if target_id is None:
        return None

    for idx, existing in enumerate(runs):
        existing_id = existing.get("run_id") if isinstance(existing, dict) else getattr(existing, "run_id", None)
        if existing_id == target_id:
            return idx
    return None
