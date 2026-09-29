"""Shared utilities for agent / team / workflow run loops."""

from __future__ import annotations

from copy import copy
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Set, TypeVar, Union

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


def _fork_root_id(run: "HistoryRun", runs_by_id: Dict[str, "HistoryRun"]) -> Optional[str]:
    """Return the id of the first run in ``run``'s fork chain, or its own id when it is not a fork.

    When an ancestor is not loaded on the session, the chain stops at the missing id, which every
    run forked from it shares.
    """
    root_id = run.run_id
    current: Optional["HistoryRun"] = run
    visited: Set[str] = set()
    while current is not None and current.forked_from_run_id and current.run_id not in visited:
        if current.run_id is not None:
            visited.add(current.run_id)
        root_id = current.forked_from_run_id
        current = runs_by_id.get(root_id)
    return root_id


def drop_superseded_forks(runs: Sequence["HistoryRun"], all_runs: Sequence["HistoryRun"]) -> List["HistoryRun"]:
    """Keep only the latest run of each fork tree.

    A fork copies its source run's messages, so a source run and every fork of it share turns.
    Keeping only the latest of them makes those turns reach the model once. ``runs`` must be in
    chronological order; ``all_runs`` is used to resolve fork chains through runs that ``runs``
    no longer contains.
    """
    runs_by_id = {r.run_id: r for r in all_runs if r.run_id is not None}
    tree_keys = [_fork_root_id(r, runs_by_id) or f"__run_{index}" for index, r in enumerate(runs)]
    latest_index = {key: index for index, key in enumerate(tree_keys)}
    return [r for index, r in enumerate(runs) if latest_index[tree_keys[index]] == index]


def has_superseded_forks(runs: Sequence["HistoryRun"]) -> bool:
    """Whether a fork replaces another history run in ``runs``.

    Only top-level runs with a history status count, matching the rows a bounded
    "most recent N" history read returns.
    """
    from agno.run.base import HISTORY_SKIP_STATUSES

    history_runs = [r for r in runs if r.parent_run_id is None and r.status not in HISTORY_SKIP_STATUSES]
    return len(drop_superseded_forks(history_runs, runs)) < len(history_runs)


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
    root_id = _fork_root_id(run, runs_by_id)
    excluded = {r.run_id for r in session_runs if _fork_root_id(r, runs_by_id) == root_id}
    excluded.update(run_id for run_id in (run.run_id, root_id) if run_id is not None)
    history_session = copy(session)
    history_session.runs = [r for r in session_runs if r.run_id not in excluded]  # type: ignore[assignment]
    return history_session
