"""Shared utilities for agent / team / workflow run loops."""

from __future__ import annotations

from copy import copy
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, TypeVar, Union

if TYPE_CHECKING:
    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput
    from agno.run.workflow import WorkflowRunOutput
    from agno.session.agent import AgentSession
    from agno.session.team import TeamSession
    from agno.session.workflow import WorkflowSession

    HistoryRun = Union[RunOutput, TeamRunOutput]

HistorySession = TypeVar("HistorySession", "AgentSession", "TeamSession")


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


def continue_history_session(session: HistorySession, run: Optional["HistoryRun"]) -> HistorySession:
    """Return a copy of ``session`` without the continued run's fork tree.

    The continued run's messages are its input, and every run in its fork tree (the runs it was
    forked from, forks of it, and sibling forks) carries a copy of the same turns, whatever their
    stored status. The original session and its runs are left untouched, including cached sessions.
    """
    if run is None:
        return session
    session_runs = list(session.runs or [])
    runs_by_id = {r.run_id: r for r in session_runs if r.run_id is not None}
    root_ids: Dict[str, Optional[str]] = {}

    def fork_root_id(start: "HistoryRun") -> Optional[str]:
        # Walk up forked_from_run_id to the first run of the chain; a missing ancestor ends the
        # chain at its id, which every run forked from it shares. Roots are cached per run so each
        # chain is walked once.
        chain: List[str] = []
        current: Optional["HistoryRun"] = start
        root_id = start.run_id
        while current is not None and current.run_id is not None:
            if current.run_id in root_ids:
                root_id = root_ids[current.run_id]
                break
            if current.run_id in chain:
                break
            chain.append(current.run_id)
            root_id = current.run_id
            if not current.forked_from_run_id:
                break
            root_id = current.forked_from_run_id
            current = runs_by_id.get(root_id)
        for run_id in chain:
            root_ids[run_id] = root_id
        return root_id

    root_id = fork_root_id(run)
    excluded: Set[Optional[str]] = {r.run_id for r in session_runs if fork_root_id(r) == root_id}
    excluded.update((run.run_id, root_id))
    excluded.discard(None)
    history_session = copy(session)
    history_session.runs = [r for r in session_runs if r.run_id not in excluded]  # type: ignore[assignment]
    return history_session
