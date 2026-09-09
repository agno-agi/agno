"""Atomic run-status persistence.

``apersist_run_status`` patches status fields of one run inside its session,
using the DB adapter's atomic ``update_run_in_session`` primitive when
available (row-locked, attempt-fenced - see the Postgres adapters), and
falling back to the fresh-read + whole-session save mitigation otherwise.

This is the write path for status TRANSITIONS (RUNNING, CANCELLED, ERROR)
made outside a run's own execution: background task bodies, the queue
worker's sweep and error persists. A run's OWN saves are fenced too when
the run executes under the queue worker: ``apersist_worker_owned_run`` /
``persist_worker_owned_run`` intercept the per-run save helpers while the
worker's ownership registration is live, so a zombie attempt's writes are
refused by the primitive instead of clobbering through bare upsert_run.
"""

import asyncio
import inspect
from enum import Enum
from typing import Any, Dict, Optional


class RunPersistOutcome(str, Enum):
    """Typed result of the atomic run-persistence primitive
    (``update_run_in_session``) and of ``apersist_run_status``.

    The previous bool/None tri-state conflated three different "False"s -
    row missing, fence rejection, terminal-row refusal - and the fallback
    decision had to guess which one it got from the caller's
    ``expected_attempt``. Guessing wrong meant the unfenced whole-session
    fallback clobbering a COMPLETED/CANCELLED row. Each outcome now names
    itself; ``fallback_allowed`` no longer guesses.
    """

    UPDATED = "updated"  # the atomic primitive wrote the fields
    MISSING = "missing"  # session or run row not found - the fallback may create it
    STALE_ATTEMPT = "stale_attempt"  # fence rejected: a newer attempt owns the row. FINAL
    TERMINAL_REFUSED = "terminal_refused"  # a completed/cancelled row wins over this write. FINAL
    UNAVAILABLE = "unavailable"  # no atomic primitive - the unfenced fallback is the only write path


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
    content_if_absent: Optional[str] = None,
) -> RunPersistOutcome:
    """Persist run-status fields atomically when the adapter supports it.

    Returns a ``RunPersistOutcome``. Adapter exceptions PROPAGATE: a DB
    failure must surface as a failure, never collapse into an outcome that
    re-opens the unfenced fallback mid-outage (the fence and terminal guards
    exist precisely for writes that race at odd times). Callers with a retry
    loop (the queue worker's sweep) treat the raise as not-persisted and come
    back; producers log it loudly.

    Third-party adapters that still return the legacy bool are mapped to the
    old semantics: True -> UPDATED; False -> STALE_ATTEMPT when a fence was
    requested (fence rejections were final), MISSING otherwise (the row does
    not exist yet and the fallback may create it).
    """
    db = _get_db(component)
    if db is None:
        return RunPersistOutcome.UNAVAILABLE
    method = getattr(db, "update_run_in_session", None)
    if not callable(method):
        return RunPersistOutcome.UNAVAILABLE
    kwargs: Dict[str, Any] = dict(
        session_id=session_id,
        run_id=run_id,
        fields=fields,
        expected_attempt=expected_attempt,
        user_id=user_id,
    )
    if content_if_absent is not None:
        kwargs["content_if_absent"] = content_if_absent
    if inspect.iscoroutinefunction(method):
        result = await method(**kwargs)
    else:
        result = await asyncio.to_thread(method, **kwargs)
    if isinstance(result, RunPersistOutcome):
        return result
    # Legacy bool adapter (third-party): reproduce the historical decisions
    if result is True:
        return RunPersistOutcome.UPDATED
    if expected_attempt is not None:
        return RunPersistOutcome.STALE_ATTEMPT
    return RunPersistOutcome.MISSING


def fallback_allowed(result: RunPersistOutcome) -> bool:
    """Whether the unfenced whole-session fallback may run after the atomic
    primitive's outcome.

    Only MISSING (the fallback creates the row) and UNAVAILABLE (no atomic
    primitive - the fallback is the only write path, fenced callers included)
    allow it. STALE_ATTEMPT and TERMINAL_REFUSED are FINAL: retrying a
    fenced-out zombie or a write a completed/cancelled row refused through
    the unfenced save is exactly the clobber those guards exist to stop.
    """
    return result in (RunPersistOutcome.MISSING, RunPersistOutcome.UNAVAILABLE)


async def apersist_run_transition(
    component: Any,
    component_type: str,
    session_id: str,
    run_response: Any,
    user_id: Optional[str] = None,
    extra_fields: Optional[Dict[str, Any]] = None,
    expected_attempt: Optional[int] = None,
    full_run: bool = False,
) -> None:
    """Persist a run's status transition: atomic patch first, fallback second.

    The caller sets run_response.status before calling. Atomic path patches
    {status, **extra_fields} under the session row lock; the fallback re-reads
    the session and saves whole (the pre-primitive mitigation), used when the
    adapter lacks the primitive or the run row does not exist yet.
    """
    status = getattr(run_response, "status", None)
    if full_run:
        # Persist the ENTIRE serialized run atomically (row-locked, single-run
        # scoped): used by error paths that just flushed in-flight messages
        # onto the run - a status-only patch would drop the conversation that
        # led to the failure on adapters with the atomic primitive, while the
        # whole-session fallback kept it (Postgres losing data SQLite kept).
        fields = dict(run_response.to_dict())
        fields["status"] = getattr(status, "value", status)
    else:
        fields = {"status": getattr(status, "value", status)}
    if extra_fields:
        fields.update(extra_fields)

    run_id = getattr(run_response, "run_id", None)
    if run_id:
        result = await apersist_run_status(
            component, component_type, session_id, run_id, fields, user_id=user_id, expected_attempt=expected_attempt
        )
        if not fallback_allowed(result):
            return

    # Fallback: fresh-read + whole-session save (narrows, does not close, the
    # concurrent-write window - see module docstring). This path writes the whole run, so its
    # media is offloaded first.
    if component_type == "agent":
        from agno.agent._session import asave_run, asave_session
        from agno.agent._storage import aread_or_create_session
        from agno.utils.agent import abuild_offloaded_storage_copy

        session = await aread_or_create_session(component, session_id=session_id, user_id=user_id)
        storage_run = run_response
        if getattr(component, "media_storage", None) is not None and getattr(component, "store_media", False):
            storage_run = await abuild_offloaded_storage_copy(component, run_response, session_id) or run_response
        session.upsert_run(run=storage_run)
        # v3 substrate: asave_session writes ONLY the session row - the run
        # itself persists via the O(1) per-run save
        await asave_run(component, run=storage_run, session_id=session_id, user_id=user_id)
        await asave_session(component, session=session)
    elif component_type == "team":
        from agno.team._session import asave_run as team_asave_run
        from agno.team._session import asave_session as team_asave_session
        from agno.team._storage import _aread_or_create_session
        from agno.utils.agent import abuild_offloaded_storage_copy

        team_session = await _aread_or_create_session(component, session_id=session_id, user_id=user_id)
        storage_run = run_response
        if getattr(component, "media_storage", None) is not None and getattr(component, "store_media", False):
            storage_run = await abuild_offloaded_storage_copy(component, run_response, session_id) or run_response
        team_session.upsert_run(run_response=storage_run)
        await team_asave_run(component, run=storage_run, session_id=session_id, user_id=user_id)
        await team_asave_session(component, session=team_session)
    elif component_type == "workflow":
        # Read-only fetch first: _aload_or_create_session(session_state=None)
        # writes {} into session_data["session_state"], clobbering the live
        # state of a run whose only write is this error transition
        workflow_session = await component.aget_session(session_id=session_id)
        if workflow_session is None:
            workflow_session, _, _ = await component._aload_or_create_session(
                session_id=session_id, user_id=user_id, session_state=None
            )
        storage_run = run_response
        if getattr(component, "media_storage", None) is not None and getattr(component, "store_media", False):
            storage_run = await component._aoffload_run_media_copy(run_response, session_id)
        workflow_session.upsert_run(run=storage_run)
        # asave_* absorbs a sync DB; branching would take the sync media path, which raises on an async backend.
        await component.asave_run(run=storage_run, session_id=session_id, user_id=user_id)
        await component.asave_session(session=workflow_session)


def _coerce_outcome(result: Any, expected_attempt: Optional[int]) -> "RunPersistOutcome":
    """Map a legacy bool-returning third-party adapter onto the typed
    outcomes, using the same historical decisions as apersist_run_status."""
    if isinstance(result, RunPersistOutcome):
        return result
    if result is True:
        return RunPersistOutcome.UPDATED
    if expected_attempt is not None:
        return RunPersistOutcome.STALE_ATTEMPT
    return RunPersistOutcome.MISSING


async def _acall_update(method: Any, kwargs: Dict[str, Any]) -> Any:
    if inspect.iscoroutinefunction(method):
        return await method(**kwargs)
    return await asyncio.to_thread(method, **kwargs)


async def apersist_worker_owned_run(
    db: Any,
    run: Any,
    session_id: str,
    user_id: Optional[str] = None,
) -> bool:
    """Fence a worker-owned run's save through the atomic primitive.

    The queue worker registers (worker_id, attempt) for exactly the span of
    each execution (agno.run.concurrency.worker_managed_execution). While
    that registration is live, every per-run DB save in this process for
    that run_id carries the attempt fence: a zombie attempt's write - a late
    terminal save OR a mid-run flush landing after a newer attempt claimed
    the row - is refused by the row-locked primitive instead of clobbering
    wholesale through bare ``upsert_run``. This closes the "run's own final
    save is unfenced" gap the module docstring describes.

    Returns True when the save was handled here: applied, or finally refused
    by the fence/terminal guard (refusals are dropped by design - retrying
    them unfenced is exactly the clobber the fence exists to stop). Returns
    False when the caller should fall through to the unfenced ``upsert_run``:
    the run is not worker-owned in this process, the adapter lacks the
    primitive (the unfenced-store startup warning covers that deployment),
    or neither the row nor its session exists yet.
    """
    from agno.run.concurrency import get_worker_ownership
    from agno.utils.log import log_warning

    run_id = getattr(run, "run_id", None)
    if run_id is None or db is None:
        return False
    ownership = get_worker_ownership(run_id)
    if ownership is None or not ownership.attempt:
        return False
    method = getattr(db, "update_run_in_session", None)
    if not callable(method):
        return False
    fields = dict(run.to_dict())
    kwargs: Dict[str, Any] = dict(
        session_id=session_id,
        run_id=run_id,
        fields=fields,
        expected_attempt=ownership.attempt,
        user_id=user_id,
    )
    outcome = _coerce_outcome(await _acall_update(method, kwargs), ownership.attempt)
    if outcome is RunPersistOutcome.MISSING:
        append = getattr(db, "append_run_to_session_if_absent", None)
        if not callable(append):
            return False
        run_dict = dict(fields)
        # Keep the fresh row fence-stamped: without the attempt on it, the
        # next fence compare passes vacuously against stored None
        run_dict["queue_attempt"] = ownership.attempt
        if inspect.iscoroutinefunction(append):
            appended = await append(session_id=session_id, run_dict=run_dict, user_id=user_id)
        else:
            appended = await asyncio.to_thread(append, session_id=session_id, run_dict=run_dict, user_id=user_id)
        if appended is None:
            return False  # no session row / no primitive: the legacy path decides
        if appended is True:
            return True
        # A concurrent writer landed the row between check and append:
        # re-drive the fenced update once against it
        outcome = _coerce_outcome(await _acall_update(method, kwargs), ownership.attempt)
        if outcome is RunPersistOutcome.MISSING:
            return False
    if outcome in (RunPersistOutcome.STALE_ATTEMPT, RunPersistOutcome.TERMINAL_REFUSED):
        log_warning(
            f"Dropped fenced-out run save: run {run_id} attempt {ownership.attempt} "
            f"({outcome.value}) - a newer attempt or a terminal row owns it"
        )
    return True


def persist_worker_owned_run(
    db: Any,
    run: Any,
    session_id: str,
    user_id: Optional[str] = None,
) -> bool:
    """Sync twin of ``apersist_worker_owned_run`` for the sync save helpers.

    Async-only adapters return False here (the sync-save-with-async-db guard
    raises upstream before this matters).
    """
    from agno.run.concurrency import get_worker_ownership
    from agno.utils.log import log_warning

    run_id = getattr(run, "run_id", None)
    if run_id is None or db is None:
        return False
    ownership = get_worker_ownership(run_id)
    if ownership is None or not ownership.attempt:
        return False
    method = getattr(db, "update_run_in_session", None)
    if not callable(method) or inspect.iscoroutinefunction(method):
        return False
    fields = dict(run.to_dict())
    kwargs: Dict[str, Any] = dict(
        session_id=session_id,
        run_id=run_id,
        fields=fields,
        expected_attempt=ownership.attempt,
        user_id=user_id,
    )
    outcome = _coerce_outcome(method(**kwargs), ownership.attempt)
    if outcome is RunPersistOutcome.MISSING:
        append = getattr(db, "append_run_to_session_if_absent", None)
        if not callable(append) or inspect.iscoroutinefunction(append):
            return False
        run_dict = dict(fields)
        run_dict["queue_attempt"] = ownership.attempt
        appended = append(session_id=session_id, run_dict=run_dict, user_id=user_id)
        if appended is None:
            return False
        if appended is True:
            return True
        outcome = _coerce_outcome(method(**kwargs), ownership.attempt)
        if outcome is RunPersistOutcome.MISSING:
            return False
    if outcome in (RunPersistOutcome.STALE_ATTEMPT, RunPersistOutcome.TERMINAL_REFUSED):
        log_warning(
            f"Dropped fenced-out run save: run {run_id} attempt {ownership.attempt} "
            f"({outcome.value}) - a newer attempt or a terminal row owns it"
        )
    return True
