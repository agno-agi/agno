"""Strict run creation and scoped run updates.

``upsert_run`` cannot tell "the framework is saving its own run again" from
"a caller handed us a run_id that already belongs to somebody else". Both
arrive as ``INSERT ... ON CONFLICT (run_id) DO UPDATE``, so a request that
supplies an id already in the runs table silently replaces the stored run,
across session and user boundaries.

This module splits the two intents:

* Creation is a strict insert. It reports a conflict instead of overwriting,
  so a run whose id is already taken is refused rather than landing on the
  stored run.
* Every later write is an update scoped to the run's own session, effective
  user and component. A lifecycle transition (pause, resume, background,
  terminal write) can only ever touch the row the run itself created.

The two together also close the window a preflight ``get_run`` check cannot:
two creations racing on the same fresh id both see no row, but only one
insert lands and the other is told ``CONFLICT``.

Adapters that do not implement the pair report ``UNSUPPORTED`` and keep the
legacy ``upsert_run`` path unchanged. ``supports_atomic_run_creation``
reports which behaviour a given db object provides, so an integration can
detect the guarantee at runtime instead of branching on a version string.
"""

import inspect
from enum import Enum
from typing import Any, Optional

from agno.utils.log import log_warning


class RunCreateOutcome(str, Enum):
    """Result of a strict run creation."""

    CREATED = "created"  # the row was inserted by this call
    CONFLICT = "conflict"  # the run_id is already taken. FINAL, never overwritten
    SESSION_MISSING = "session_missing"  # the run has no session row to attach to. FINAL
    UNSUPPORTED = "unsupported"  # adapter has no strict-insert primitive
    ERROR = "error"  # the primitive exists but the write failed


class RunUpdateOutcome(str, Enum):
    """Result of a scoped run update."""

    UPDATED = "updated"  # the row was patched
    MISSING = "missing"  # no row with this run_id; the caller may create it
    SCOPE_MISMATCH = "scope_mismatch"  # the row belongs to another session/user/component. FINAL
    UNSUPPORTED = "unsupported"  # adapter has no scoped-update primitive
    ERROR = "error"  # the primitive exists and did not answer. FINAL


__all__ = [
    "CREATE_NEEDED_UPDATE",
    "FALLBACK_ALLOWED_CREATE",
    "FALLBACK_ALLOWED_UPDATE",
    "FINAL_CREATE",
    "FINAL_UPDATE",
    "RunCreateOutcome",
    "RunUpdateOutcome",
    "apersist_run_scoped",
    "persist_run_scoped",
    "supports_atomic_run_creation",
]

# How each outcome is routed. Listed member by member rather than derived as
# a complement, so a member added later belongs to no set and the
# exhaustiveness test fails, instead of the new member defaulting into the
# branch that reaches the overwriting ``upsert_run``.
FALLBACK_ALLOWED_CREATE = frozenset({RunCreateOutcome.UNSUPPORTED})
FINAL_CREATE = frozenset(
    {
        RunCreateOutcome.CREATED,
        RunCreateOutcome.CONFLICT,
        RunCreateOutcome.SESSION_MISSING,
        RunCreateOutcome.ERROR,
    }
)
FALLBACK_ALLOWED_UPDATE = frozenset({RunUpdateOutcome.UNSUPPORTED})
CREATE_NEEDED_UPDATE = frozenset({RunUpdateOutcome.MISSING})
FINAL_UPDATE = frozenset({RunUpdateOutcome.UPDATED, RunUpdateOutcome.SCOPE_MISMATCH, RunUpdateOutcome.ERROR})


def supports_atomic_run_creation(db: Any) -> bool:
    """Whether ``db`` provides the strict-create / scoped-update pair.

    Runtime capability probe for downstream integrations. True means a
    conflicting caller-supplied run_id is rejected by the storage layer
    itself and later writes stay inside the run's own scope, so the caller
    needs no preflight read of its own to be safe. Reads the
    ``supports_atomic_run_creation`` attribute, which an adapter sets only
    once it implements both halves. See ``BaseDb.create_run``.
    """
    return bool(getattr(db, "supports_atomic_run_creation", False))


def _run_id_of(run: Any) -> Optional[str]:
    return run.get("run_id") if isinstance(run, dict) else getattr(run, "run_id", None)


def _coerce_create(result: Any) -> RunCreateOutcome:
    """Map an adapter's create result onto the typed outcome.

    A third-party adapter can return the bare string (the members are
    ``str``-valued), and an identity comparison against it would fall through
    to the overwriting ``upsert_run`` -- the exact clobber this module
    exists to stop. Anything unrecognised is an error, never a success.
    """
    if isinstance(result, RunCreateOutcome):
        return result
    try:
        return RunCreateOutcome(result)
    except ValueError:
        log_warning(f"Adapter returned an unrecognised run-creation result: {result!r}")
        return RunCreateOutcome.ERROR


def _coerce_update(result: Any) -> RunUpdateOutcome:
    """Map an adapter's update result onto the typed outcome.

    Unrecognised means ERROR, not UNSUPPORTED: UNSUPPORTED sends the caller
    to the overwriting ``upsert_run``, so reading a garbled answer that way
    would perform the clobber this module exists to stop.
    """
    if isinstance(result, RunUpdateOutcome):
        return result
    try:
        return RunUpdateOutcome(result)
    except ValueError:
        log_warning(f"Adapter returned an unrecognised run-update result: {result!r}")
        return RunUpdateOutcome.ERROR


def _create_is_final(outcome: RunCreateOutcome, run_id: Optional[str]) -> bool:
    """Whether a non-CREATED creation ends the write here.

    Only UNSUPPORTED hands the write back to the legacy ``upsert_run``; every
    other outcome means the strict insert answered, and its answer stands. The
    update side has the same rule, and letting the two disagree is how an
    error becomes an overwrite.
    """
    if outcome in FALLBACK_ALLOWED_CREATE:
        return False
    if outcome not in FINAL_CREATE:
        log_warning(f"Run {run_id} was not saved: the storage create answered an unrecognised outcome")
        return True
    if outcome is RunCreateOutcome.CONFLICT:
        log_warning(
            f"Refused run save: run {run_id} is already stored under a different session, user or component. "
            "The stored run was left unchanged."
        )
        return True
    if outcome is RunCreateOutcome.SESSION_MISSING:
        log_warning(f"Run {run_id} was not saved: there is no session row to attach it to")
        return True
    log_warning(f"Run {run_id} was not saved: the storage create answered {outcome.value}")
    return True


def _resolve_update(outcome: RunUpdateOutcome, run_id: Optional[str]) -> Optional[bool]:
    """Map a scoped-update outcome onto handled (True), create-needed (None)
    or not-ours-to-answer (False, the caller keeps its legacy save).

    Only the two sets that change the routing are read here: CREATE_NEEDED
    and FALLBACK_ALLOWED. Everything else is final, so a member added later
    without a decision falls through to final rather than to the overwriting
    save. FINAL_UPDATE exists to make that completeness assertable, and the
    exhaustiveness test is what enforces it.
    """
    if outcome in CREATE_NEEDED_UPDATE:
        return None
    if outcome in FALLBACK_ALLOWED_UPDATE:
        return False
    if outcome is RunUpdateOutcome.UPDATED:
        return True
    if outcome is RunUpdateOutcome.SCOPE_MISMATCH:
        # FINAL by design: the stored run belongs to another session, user or
        # component, and the whole point of scoping is that this write does
        # not reach it. Falling through to the unscoped upsert would perform
        # exactly the overwrite the scope refused.
        log_warning(
            f"Refused run save: run {run_id} is stored under a different session, user or component. "
            "The stored run was left unchanged."
        )
        return True
    # ERROR, and anything a future member might be: final either way, because
    # the only alternative is the overwriting save.
    log_warning(f"Run {run_id} was not saved: the storage update did not answer")
    return True


def _conflict_is_final(resolved: Optional[bool], run_id: Optional[str]) -> bool:
    """Close out a create that reported CONFLICT.

    The row exists, so either the re-driven scoped update lands on it or this
    write has no business there. Both of the other answers are final too: an
    adapter that reports the pair UNSUPPORTED only after its own create said
    CONFLICT is contradicting itself, and "no row" means the id belongs to a
    run nobody this writer can name. Handing either to the unscoped save is
    the overwrite the whole module exists to refuse.
    """
    if resolved is True:
        return True
    log_warning(f"Run {run_id} was not saved: its id is taken by a run this write cannot reach")
    return True


def persist_run_scoped(
    db: Any,
    run: Any,
    session_id: str,
    user_id: Optional[str] = None,
    run_index: Optional[int] = None,
) -> bool:
    """Save a run through the scoped-update / strict-create pair.

    Returns True when this handled the write: applied, or finally refused
    because the row belongs to another owner. Returns False when the adapter
    does not advertise the scoped pair and the caller keeps the legacy
    ``upsert_run``.
    """
    if not supports_atomic_run_creation(db):
        return False
    update = getattr(db, "update_run", None) if db is not None else None
    create = getattr(db, "create_run", None) if db is not None else None
    if not callable(update) or not callable(create):
        return False
    if inspect.iscoroutinefunction(update) or inspect.iscoroutinefunction(create):
        # A ported adapter reached through the sync door still advertises the
        # guarantee, so the mismatch has to be visible rather than quietly
        # handing the write to the overwriting save
        log_warning(
            f"Run {_run_id_of(run)}: the scoped save was skipped because its storage only "
            "writes runs asynchronously, and this caller reached it synchronously"
        )
        return False

    run_id = _run_id_of(run)
    resolved = _resolve_update(
        _coerce_update(update(run=run, session_id=session_id, user_id=user_id, run_index=run_index)), run_id
    )
    if resolved is not None:
        return resolved

    created = _coerce_create(create(run=run, session_id=session_id, user_id=user_id, run_index=run_index))
    if created is RunCreateOutcome.CREATED:
        return True
    if created is not RunCreateOutcome.CONFLICT:
        return _create_is_final(created, run_id)
    # A concurrent writer landed the row between the update and the create;
    # re-drive the scoped update against whatever is there now.
    resolved = _resolve_update(
        _coerce_update(update(run=run, session_id=session_id, user_id=user_id, run_index=run_index)), run_id
    )
    return _conflict_is_final(resolved, run_id)


async def apersist_run_scoped(
    db: Any,
    run: Any,
    session_id: str,
    user_id: Optional[str] = None,
    run_index: Optional[int] = None,
) -> bool:
    """Async twin of :func:`persist_run_scoped`; also drives a sync adapter."""
    if not supports_atomic_run_creation(db):
        return False
    update = getattr(db, "update_run", None) if db is not None else None
    create = getattr(db, "create_run", None) if db is not None else None
    if not callable(update) or not callable(create):
        return False
    update_is_async = inspect.iscoroutinefunction(update)
    create_is_async = inspect.iscoroutinefunction(create)

    async def _update() -> RunUpdateOutcome:
        if update_is_async:
            return _coerce_update(await update(run=run, session_id=session_id, user_id=user_id, run_index=run_index))
        return _coerce_update(update(run=run, session_id=session_id, user_id=user_id, run_index=run_index))

    run_id = _run_id_of(run)
    resolved = _resolve_update(await _update(), run_id)
    if resolved is not None:
        return resolved

    if create_is_async:
        created = _coerce_create(await create(run=run, session_id=session_id, user_id=user_id, run_index=run_index))
    else:
        created = _coerce_create(create(run=run, session_id=session_id, user_id=user_id, run_index=run_index))
    if created is RunCreateOutcome.CREATED:
        return True
    if created is not RunCreateOutcome.CONFLICT:
        return _create_is_final(created, run_id)
    resolved = _resolve_update(await _update(), run_id)
    return _conflict_is_final(resolved, run_id)
