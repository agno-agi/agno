"""Atomic run-status persistence.

``apersist_run_status`` patches status fields of one run inside its session,
using the DB adapter's atomic ``update_run_in_session`` primitive when
available (row-locked, attempt-fenced - see the Postgres adapters), and
falling back to the fresh-read + whole-session save mitigation otherwise.

This is the write path for status TRANSITIONS (RUNNING, CANCELLED, ERROR)
made outside a run's own execution: background task bodies, the queue
worker's sweep and error persists. A run's own final save (inside arun's
cleanup) still writes the full session; fencing that path end-to-end is the
remaining scope documented in the design note.
"""

import asyncio
import inspect
from typing import Any, Dict, Optional

from agno.utils.log import log_debug


def _get_db(component: Any) -> Any:
    return getattr(component, "db", None)


async def apersist_run_status(
    component: Any,
    component_type: str,
    session_id: str,
    run_id: str,
    fields: Dict[str, Any],
    user_id: Optional[str] = None,
    expected_attempt: Optional[int] = None,
) -> Optional[bool]:
    """Persist run-status fields atomically when the adapter supports it.

    Tri-state result:
    - True: the atomic primitive wrote the fields.
    - False: the atomic primitive RAN and declined - the run row is missing,
      or (when ``expected_attempt`` was given) the attempt fence rejected this
      writer because a newer attempt owns the row. When a fence was requested,
      False is FINAL: falling back to an unfenced whole-session save would
      hand a fenced-out zombie exactly the clobber the fence exists to stop.
    - None: no atomic primitive available (no db, no method, or it raised) -
      the unfenced fallback is the only option and remains legitimate.
    """
    db = _get_db(component)
    if db is None:
        return None
    method = getattr(db, "update_run_in_session", None)
    if not callable(method):
        return None
    try:
        if inspect.iscoroutinefunction(method):
            return bool(
                await method(session_id=session_id, run_id=run_id, fields=fields, expected_attempt=expected_attempt)
            )
        return bool(
            await asyncio.to_thread(
                method, session_id=session_id, run_id=run_id, fields=fields, expected_attempt=expected_attempt
            )
        )
    except Exception as e:
        # Liveness over strictness: a transient DB error should not strand the
        # run in a non-terminal state, so the caller may fall back. The fence
        # bypass this opens needs a zombie AND a coincident DB failure.
        log_debug(f"Atomic run status persist failed, caller falls back: {e}")
        return None


def fallback_allowed(result: Optional[bool], expected_attempt: Optional[int]) -> bool:
    """Whether the unfenced fallback may run after an atomic-path result."""
    if result is True:
        return False
    if result is None:
        return True
    # result is False: the atomic path spoke. Without a fence that means the
    # run row does not exist yet (fallback creates it); with a fence it may
    # mean a newer attempt owns the row - never override a possible fence.
    return expected_attempt is None


async def apersist_run_transition(
    component: Any,
    component_type: str,
    session_id: str,
    run_response: Any,
    user_id: Optional[str] = None,
    extra_fields: Optional[Dict[str, Any]] = None,
    expected_attempt: Optional[int] = None,
) -> None:
    """Persist a run's status transition: atomic patch first, fallback second.

    The caller sets run_response.status before calling. Atomic path patches
    {status, **extra_fields} under the session row lock; the fallback re-reads
    the session and saves whole (the pre-primitive mitigation), used when the
    adapter lacks the primitive or the run row does not exist yet.
    """
    status = getattr(run_response, "status", None)
    fields: Dict[str, Any] = {"status": getattr(status, "value", status)}
    if extra_fields:
        fields.update(extra_fields)

    run_id = getattr(run_response, "run_id", None)
    if run_id:
        result = await apersist_run_status(
            component, component_type, session_id, run_id, fields, user_id=user_id, expected_attempt=expected_attempt
        )
        if not fallback_allowed(result, expected_attempt):
            return

    # Fallback: fresh-read + whole-session save (narrows, does not close, the
    # concurrent-write window - see module docstring)
    if component_type == "agent":
        from agno.agent._session import asave_session
        from agno.agent._storage import aread_or_create_session

        session = await aread_or_create_session(component, session_id=session_id, user_id=user_id)
        session.upsert_run(run=run_response)
        await asave_session(component, session=session)
    elif component_type == "team":
        from agno.team._session import asave_session as team_asave_session
        from agno.team._storage import _aread_or_create_session

        team_session = await _aread_or_create_session(component, session_id=session_id, user_id=user_id)
        team_session.upsert_run(run_response=run_response)
        await team_asave_session(component, session=team_session)
    elif component_type == "workflow":
        workflow_session, _ = await component._aload_or_create_session(
            session_id=session_id, user_id=user_id, session_state=None
        )
        workflow_session.upsert_run(run=run_response)
        if component._has_async_db():
            await component.asave_session(session=workflow_session)
        else:
            component.save_session(session=workflow_session)
