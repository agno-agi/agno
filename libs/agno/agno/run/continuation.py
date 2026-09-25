"""History and persistence shared by agent and team continuations."""

from copy import copy
from typing import Any, TypeVar

from agno.run.base import RunStatus
from agno.run.status_persist import RunPersistOutcome, _coerce_outcome, apersist_run_status, fallback_allowed
from agno.session import AgentSession, TeamSession

Session = TypeVar("Session", AgentSession, TeamSession)


def _history_session(session: Session, run: Any) -> Session:
    """Exclude the supplied transcript's run and fork ancestors before history limits.

    Keep the original session and its runs untouched, including cached sessions.
    The shallow copy also preserves custom session history implementations.
    """
    if run is None:
        return session
    runs_by_id = {r.run_id: r for r in session.runs or []}
    excluded = set()
    while run is not None and run.run_id not in excluded:
        excluded.add(run.run_id)
        source_id = run.forked_from_run_id
        if not source_id or source_id in excluded:
            break
        run = runs_by_id.get(source_id)
        if run is None:
            excluded.add(source_id)
    history_session = copy(session)
    history_session.runs = [r for r in session.runs or [] if r.run_id not in excluded]
    return history_session


def _owns_storage(component: Any, component_type: str) -> bool:
    """Embedded runs are stored by their parent, as in the normal save helpers."""
    parent_id = component.team_id if component_type == "agent" else component.parent_team_id
    return component.db is not None and parent_id is None and component.workflow_id is None


def _check_start_outcome(outcome: RunPersistOutcome, run: Any) -> None:
    if outcome in (RunPersistOutcome.STALE_ATTEMPT, RunPersistOutcome.TERMINAL_REFUSED):
        from agno.exceptions import RunNotContinuableError

        raise RunNotContinuableError(f"Cannot continue run {run.run_id}: database refused the RUNNING transition")


def _persist_continue_start(component: Any, component_type: str, run: Any, session: Any, run_context: Any) -> None:
    """Publish RUNNING before resumed work, preferring a status-only patch."""
    from agno.run.concurrency import get_worker_ownership

    if not _owns_storage(component, component_type):
        run.status = RunStatus.running
        return
    ownership = get_worker_ownership(run.run_id)
    attempt = ownership.attempt if ownership else None
    method = getattr(component.db, "update_run_in_session", None)
    outcome = RunPersistOutcome.UNAVAILABLE
    if callable(method):
        outcome = _coerce_outcome(
            method(
                session_id=session.session_id,
                run_id=run.run_id,
                fields={"status": RunStatus.running.value},
                user_id=run_context.user_id if run_context is not None else run.user_id,
                expected_attempt=attempt,
            ),
            attempt,
        )
    _check_start_outcome(outcome, run)
    run.status = RunStatus.running
    if fallback_allowed(outcome):
        # New forks need a complete first save, including their run index. Legacy
        # adapters without an atomic patch use the same storage-safe snapshot.
        if component_type == "agent":
            from agno.agent._run import persist_run_in_session

            persist_run_in_session(component, run, session, run_context)
        else:
            from agno.team._run import _persist_team_run_in_session

            _persist_team_run_in_session(component, run, session, run_context)


async def _apersist_continue_start(
    component: Any, component_type: str, run: Any, session: Any, run_context: Any
) -> None:
    """Async counterpart of :func:`_persist_continue_start`."""
    from agno.run.concurrency import get_worker_ownership

    if not _owns_storage(component, component_type):
        run.status = RunStatus.running
        return
    ownership = get_worker_ownership(run.run_id)
    outcome = await apersist_run_status(
        component,
        component_type,
        session.session_id,
        run.run_id,
        {"status": RunStatus.running.value},
        user_id=run_context.user_id if run_context is not None else run.user_id,
        expected_attempt=ownership.attempt if ownership else None,
    )
    _check_start_outcome(outcome, run)
    run.status = RunStatus.running
    if fallback_allowed(outcome):
        if component_type == "agent":
            from agno.agent._run import apersist_run_in_session

            await apersist_run_in_session(component, run, session, run_context)
        else:
            from agno.team._run import _apersist_team_run_in_session

            await _apersist_team_run_in_session(component, run, session, run_context)
