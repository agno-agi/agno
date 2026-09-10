"""Run creation never overwrites, and lifecycle updates stay inside their owner.

``upsert_run`` writes creations and updates with the same statement, so a
caller-supplied ``run_id`` that already exists replaced the stored run, across
sessions and users. ``create_run`` is a strict insert that reports a conflict,
and ``update_run`` patches only a row whose session, effective user and
component identity match the write.

Covered here for the in-memory and SQLite adapters, sync and async. The
PostgreSQL twin lives in test_run_creation_isolation_postgres.py.
"""

import asyncio
import threading
import time
from typing import Any, Dict, List, Optional

import pytest

from agno.db.in_memory import InMemoryDb
from agno.db.run_writes import (
    CREATE_NEEDED_UPDATE,
    FALLBACK_ALLOWED_CREATE,
    FALLBACK_ALLOWED_UPDATE,
    FINAL_CREATE,
    FINAL_UPDATE,
    RunCreateOutcome,
    RunUpdateOutcome,
    apersist_run_scoped,
    persist_run_scoped,
    supports_atomic_run_creation,
)
from agno.db.sqlite import SqliteDb
from agno.db.sqlite.async_sqlite import AsyncSqliteDb
from agno.db.utils import is_foreign_key_violation, run_scope_allows
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session import AgentSession, TeamSession, WorkflowSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent_session(session_id: str = "s1", user_id: Optional[str] = None) -> AgentSession:
    return AgentSession(session_id=session_id, agent_id="a1", user_id=user_id, created_at=1)


def _team_session(session_id: str = "s1", user_id: Optional[str] = None) -> TeamSession:
    return TeamSession(session_id=session_id, team_id="t1", user_id=user_id, created_at=1)


def _agent_run(
    run_id: str, session_id: str = "s1", user_id: Optional[str] = None, content: Optional[str] = None
) -> RunOutput:
    return RunOutput(run_id=run_id, session_id=session_id, agent_id="a1", user_id=user_id, content=content)


def _team_run(
    run_id: str, session_id: str = "s1", user_id: Optional[str] = None, content: Optional[str] = None
) -> TeamRunOutput:
    return TeamRunOutput(run_id=run_id, session_id=session_id, team_id="t1", user_id=user_id, content=content)


def _payload(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The stored run itself, whichever row shape the adapter returns.

    SQL adapters return a runs-table row wrapping the run in ``run_data``; the
    in-memory adapter stores runs inline and returns the run dict directly.
    """
    if row is None:
        return {}
    return row.get("run_data") or row


def _stored_content(db: Any, run_id: str) -> Optional[str]:
    return _payload(db.get_run(run_id, deserialize=False)).get("content")


async def _astored_content(db: Any, run_id: str) -> Optional[str]:
    return _payload(await db.get_run(run_id, deserialize=False)).get("content")


def _stored_status(db: Any, run_id: str) -> Optional[str]:
    return _payload(db.get_run(run_id, deserialize=False)).get("status")


def _stored_index(db: Any, run_id: str) -> Optional[int]:
    return (db.get_run(run_id, deserialize=False) or {}).get("run_index")


def _stored_owner(db: Any, run_id: str, column: str) -> Optional[str]:
    """An identity column as stored, read the way the row shapes allow.

    ``get`` rather than indexing: the in-memory adapter leaves a column it has
    no value for out of the dict entirely, and a KeyError there would read as
    a test bug rather than as the None it means.
    """
    return (db.get_run(run_id, deserialize=False) or {}).get(column)


def _store_and_write(db: Any, run_id: str, content: str, session_id: str = "s1", user_id: Optional[str] = None):
    """Store a run and give it content, the way a real run does.

    A run's row is created by its first save and patched by every save after,
    so a test that needs stored content performs both.
    """
    from agno.db.base import SessionType

    if db.get_session(session_id=session_id, session_type=SessionType.AGENT, deserialize=False) is None:
        db.upsert_session(_agent_session(session_id, user_id=user_id))
    db.create_run(
        run=_agent_run(run_id, session_id=session_id, user_id=user_id),
        session_id=session_id,
        user_id=user_id,
    )
    db.update_run(
        run=_agent_run(run_id, session_id=session_id, user_id=user_id, content=content),
        session_id=session_id,
        user_id=user_id,
    )


def _drive_the_caller(db: Any, run: Any, session_id: str = "s1") -> None:
    """The per-run save as the framework itself performs it.

    ``persist_run_scoped`` never calls ``upsert_run``: returning False is what
    sends its caller to the overwriting save. So "the overwrite was not
    reached" is only assertable through a caller, and the agent save helper is
    the one every agent run goes through.
    """
    from types import SimpleNamespace

    from agno.agent._storage import upsert_run

    upsert_run(SimpleNamespace(db=db), run, session_id=session_id)  # type: ignore[arg-type]


@pytest.fixture(params=["in_memory", "sqlite"])
def db(request, tmp_path):
    if request.param == "in_memory":
        yield InMemoryDb()
        return
    database = SqliteDb(db_file=str(tmp_path / "runs.db"))
    yield database


@pytest.fixture
def async_db(tmp_path):
    return AsyncSqliteDb(db_file=str(tmp_path / "async_runs.db"))


# ---------------------------------------------------------------------------
# Capability
# ---------------------------------------------------------------------------


class TestCapability:
    def test_supported_adapters_advertise_atomic_creation(self, db):
        assert supports_atomic_run_creation(db) is True

    def test_async_sqlite_advertises_atomic_creation(self, async_db):
        assert supports_atomic_run_creation(async_db) is True

    def test_probe_is_false_for_an_object_without_the_pair(self):
        assert supports_atomic_run_creation(object()) is False

    def test_a_half_ported_adapter_keeps_the_legacy_save(self):
        """Advertising the guarantee is not implementing it.

        The probe reports what the adapter claims, because that is the flag a
        downstream integration branches on. The save path asks a second
        question -- are both halves callable -- and a half-ported adapter has
        to hand the write back rather than have the missing half raise
        mid-save.
        """

        class HalfPortedDb:
            supports_atomic_run_creation = True
            upsert_calls = 0

            def create_run(self, **kwargs):
                raise AssertionError("the pair is incomplete; the strict create must not be driven")

            def upsert_run(self, **kwargs):
                HalfPortedDb.upsert_calls += 1

        database = HalfPortedDb()

        assert supports_atomic_run_creation(database) is True
        assert persist_run_scoped(database, _agent_run("r1"), session_id="s1") is False

        # Handing the write back is only safe if the caller then writes it
        _drive_the_caller(database, _agent_run("r1"))
        assert HalfPortedDb.upsert_calls == 1


# ---------------------------------------------------------------------------
# Strict creation
# ---------------------------------------------------------------------------


class TestStrictCreation:
    def test_fresh_id_is_created(self, db):
        db.upsert_session(_agent_session())
        assert db.create_run(run=_agent_run("r1"), session_id="s1") is RunCreateOutcome.CREATED
        assert _stored_content(db, "r1") is None

    def test_taken_id_conflicts_and_leaves_the_stored_run_untouched(self, db):
        db.upsert_session(_agent_session())
        db.create_run(run=_agent_run("r1", content="original"), session_id="s1")

        outcome = db.create_run(run=_agent_run("r1", content="attacker"), session_id="s1")

        assert outcome is RunCreateOutcome.CONFLICT
        assert _stored_content(db, "r1") == "original"

    def test_taken_id_conflicts_across_sessions(self, db):
        db.upsert_session(_agent_session("victim", user_id="victim-user"))
        db.upsert_session(_agent_session("attacker", user_id="attacker-user"))
        db.create_run(
            run=_agent_run("r1", session_id="victim", content="original"), session_id="victim", user_id="victim-user"
        )

        outcome = db.create_run(
            run=_agent_run("r1", session_id="attacker", content="attacker"),
            session_id="attacker",
            user_id="attacker-user",
        )

        assert outcome is RunCreateOutcome.CONFLICT
        assert _stored_content(db, "r1") == "original"

    def test_creation_reports_a_missing_session(self, db):
        assert db.create_run(run=_agent_run("r1"), session_id="s1") is RunCreateOutcome.SESSION_MISSING

    def test_team_runs_get_the_same_refusal(self, db):
        db.upsert_session(_team_session())
        db.create_run(run=_team_run("r1", content="original"), session_id="s1")

        outcome = db.create_run(run=_team_run("r1", content="attacker"), session_id="s1")

        assert outcome is RunCreateOutcome.CONFLICT
        assert _stored_content(db, "r1") == "original"

    def test_distinct_ids_both_land(self, db):
        db.upsert_session(_agent_session())
        assert db.create_run(run=_agent_run("r1"), session_id="s1") is RunCreateOutcome.CREATED
        assert db.create_run(run=_agent_run("r2"), session_id="s1") is RunCreateOutcome.CREATED
        assert db.get_run("r1") is not None and db.get_run("r2") is not None

    def test_creation_assigns_increasing_run_indexes(self, db):
        db.upsert_session(_agent_session())
        db.create_run(run=_agent_run("r1"), session_id="s1")
        db.create_run(run=_agent_run("r2"), session_id="s1")

        assert _stored_index(db, "r2") > _stored_index(db, "r1")


class TestStrictCreationAsync:
    @pytest.mark.asyncio
    async def test_fresh_id_is_created(self, async_db):
        await async_db.upsert_session(_agent_session())
        assert await async_db.create_run(run=_agent_run("r1"), session_id="s1") is RunCreateOutcome.CREATED

    @pytest.mark.asyncio
    async def test_taken_id_conflicts_and_leaves_the_stored_run_untouched(self, async_db):
        await async_db.upsert_session(_agent_session())
        await async_db.create_run(run=_agent_run("r1", content="original"), session_id="s1")

        outcome = await async_db.create_run(run=_agent_run("r1", content="attacker"), session_id="s1")

        assert outcome is RunCreateOutcome.CONFLICT
        assert await _astored_content(async_db, "r1") == "original"

    @pytest.mark.asyncio
    async def test_taken_id_conflicts_across_users(self, async_db):
        await async_db.upsert_session(_agent_session("victim", user_id="victim-user"))
        await async_db.upsert_session(_agent_session("attacker", user_id="attacker-user"))
        await async_db.create_run(
            run=_agent_run("r1", session_id="victim", content="original"), session_id="victim", user_id="victim-user"
        )

        outcome = await async_db.create_run(
            run=_agent_run("r1", session_id="attacker", content="attacker"),
            session_id="attacker",
            user_id="attacker-user",
        )

        assert outcome is RunCreateOutcome.CONFLICT
        assert await _astored_content(async_db, "r1") == "original"

    @pytest.mark.asyncio
    async def test_creation_reports_a_missing_session(self, async_db):
        assert await async_db.create_run(run=_agent_run("r1"), session_id="s1") is RunCreateOutcome.SESSION_MISSING


# ---------------------------------------------------------------------------
# Concurrent creation
# ---------------------------------------------------------------------------


CONCURRENT_WRITERS = 8

# Every wait a concurrency case performs is bounded by this, so a writer that
# never arrives at the barrier or a write that never returns fails the test
# instead of hanging the suite.
THREAD_TIMEOUT_SECONDS = 10.0


def _run_threads(attempt: Any) -> None:
    """Run ``attempt`` on CONCURRENT_WRITERS threads and fail on any raise.

    A worker that raises would otherwise just be absent from the collected
    outcomes, and an assertion counting exactly one CREATED would pass while
    every other writer crashed.
    """
    failures: List[BaseException] = []
    failures_lock = threading.Lock()

    def guarded(index: int) -> None:
        try:
            attempt(index)
        except BaseException as error:
            with failures_lock:
                failures.append(error)

    # Daemon threads joined against one shared deadline: a stuck writer cannot
    # hold the interpreter open, and eight per-thread timeouts cannot add up to
    # eight times the wait a reader of this constant expects.
    threads = [threading.Thread(target=guarded, args=(i,), daemon=True) for i in range(CONCURRENT_WRITERS)]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + THREAD_TIMEOUT_SECONDS
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    still_running = [thread for thread in threads if thread.is_alive()]
    if still_running:
        raise AssertionError(
            f"{len(still_running)} of {CONCURRENT_WRITERS} writers were still running after {THREAD_TIMEOUT_SECONDS}s"
        )
    if failures:
        raise AssertionError(f"{len(failures)} of {CONCURRENT_WRITERS} writers raised; first: {failures[0]!r}")


class _SlowCheckInMemoryDb(InMemoryDb):
    """In-memory store whose run-existence check takes measurable time.

    ``calls`` lets the test assert the delay was actually applied: an
    implementation that stopped going through ``_locate_run`` would otherwise
    make the concurrency test pass for the wrong reason.
    """

    def __init__(self, delay: float):
        super().__init__()
        self._delay = delay
        self.calls = 0

    def _locate_run(self, run_id: str):
        located = super()._locate_run(run_id)
        self.calls += 1
        time.sleep(self._delay)
        return located


class TestConcurrentCreation:
    def test_barrier_started_creations_of_one_fresh_id_produce_one_winner(self, db):
        """The window a preflight read cannot close: every writer sees no row."""
        db.upsert_session(_agent_session())
        barrier = threading.Barrier(CONCURRENT_WRITERS, timeout=THREAD_TIMEOUT_SECONDS)
        outcomes: List[RunCreateOutcome] = []
        lock = threading.Lock()

        def attempt(index: int) -> None:
            run = _agent_run("contested", content=f"writer-{index}")
            barrier.wait()
            outcome = db.create_run(run=run, session_id="s1")
            with lock:
                outcomes.append(outcome)

        _run_threads(attempt)

        assert outcomes.count(RunCreateOutcome.CREATED) == 1
        assert outcomes.count(RunCreateOutcome.CONFLICT) == CONCURRENT_WRITERS - 1

    def test_the_winner_is_the_run_that_stays_stored(self, db):
        db.upsert_session(_agent_session())
        barrier = threading.Barrier(CONCURRENT_WRITERS, timeout=THREAD_TIMEOUT_SECONDS)
        winners: List[str] = []
        lock = threading.Lock()

        def attempt(index: int) -> None:
            content = f"writer-{index}"
            barrier.wait()
            if db.create_run(run=_agent_run("contested", content=content), session_id="s1") is RunCreateOutcome.CREATED:
                with lock:
                    winners.append(content)

        _run_threads(attempt)

        assert len(winners) == 1
        assert _stored_content(db, "contested") == winners[0]

    def test_a_slow_existence_check_still_yields_one_winner(self):
        """The lock, not the interpreter, is what makes the check-then-write safe.

        Runs inline in the in-memory store rather than in a database, so
        nothing outside the adapter serializes the writers. Delaying the
        existence check widens the window between "no row" and "row written"
        to something a scheduler will actually interleave; every writer then
        sees no row unless the write is held under the lock.
        """
        database = _SlowCheckInMemoryDb(delay=0.02)
        database.upsert_session(_agent_session())
        barrier = threading.Barrier(CONCURRENT_WRITERS, timeout=THREAD_TIMEOUT_SECONDS)
        outcomes: List[RunCreateOutcome] = []
        lock = threading.Lock()

        def attempt(index: int) -> None:
            run = _agent_run("contested", content=f"writer-{index}")
            barrier.wait()
            outcome = database.create_run(run=run, session_id="s1")
            with lock:
                outcomes.append(outcome)

        _run_threads(attempt)

        # One call is the healthy signature: the winner takes the delay, and
        # the writers behind it short-circuit on the ledger the lock let it
        # write. Zero would mean the delay never applied and the test proved
        # nothing; without the lock every writer reaches the check instead.
        assert database.calls >= 1, "the delayed check was bypassed; the test proves nothing"
        assert outcomes.count(RunCreateOutcome.CREATED) == 1
        assert outcomes.count(RunCreateOutcome.CONFLICT) == CONCURRENT_WRITERS - 1
        _, total = database.get_runs(session_id="s1", deserialize=False)
        assert total == 1


class TestConcurrentCreationAsync:
    @pytest.mark.asyncio
    async def test_barrier_started_creations_of_one_fresh_id_produce_one_winner(self, async_db):
        await async_db.upsert_session(_agent_session())
        started = asyncio.Event()

        async def attempt(index: int) -> RunCreateOutcome:
            await started.wait()
            return await async_db.create_run(run=_agent_run("contested", content=f"writer-{index}"), session_id="s1")

        tasks = [asyncio.create_task(attempt(i)) for i in range(CONCURRENT_WRITERS)]
        await asyncio.sleep(0)
        started.set()
        outcomes = await asyncio.gather(*tasks)

        assert list(outcomes).count(RunCreateOutcome.CREATED) == 1
        assert list(outcomes).count(RunCreateOutcome.CONFLICT) == CONCURRENT_WRITERS - 1


# ---------------------------------------------------------------------------
# Scoped lifecycle updates
# ---------------------------------------------------------------------------


class TestScopedUpdates:
    def test_the_owner_can_update(self, db):
        db.upsert_session(_agent_session(user_id="u1"))
        db.create_run(run=_agent_run("r1", user_id="u1"), session_id="s1", user_id="u1")

        outcome = db.update_run(run=_agent_run("r1", user_id="u1", content="turn one"), session_id="s1", user_id="u1")

        assert outcome is RunUpdateOutcome.UPDATED
        assert _stored_content(db, "r1") == "turn one"

    def test_an_anonymous_run_is_updatable_by_the_same_anonymous_caller(self, db):
        _store_and_write(db, "r1", "reserved")

        outcome = db.update_run(run=_agent_run("r1", content="turn one"), session_id="s1")

        assert outcome is RunUpdateOutcome.UPDATED
        assert _stored_content(db, "r1") == "turn one"

    def test_another_user_cannot_update(self, db):
        _store_and_write(db, "r1", "original", user_id="u1")

        outcome = db.update_run(run=_agent_run("r1", user_id="u2", content="attacker"), session_id="s1", user_id="u2")

        assert outcome is RunUpdateOutcome.SCOPE_MISMATCH
        assert _stored_content(db, "r1") == "original"

    def test_an_unowned_run_accepts_an_identified_writer(self, db):
        """The user is compared only when both sides know one.

        The framework reaches the save path from several places that resolve
        identity differently, and a strict comparison turns those
        disagreements into silently dropped runs. What stays refused is one
        named user reaching another named user's row.
        """
        _store_and_write(db, "r1", "original")

        outcome = db.update_run(run=_agent_run("r1", user_id="u2", content="turn one"), session_id="s1", user_id="u2")

        assert outcome is RunUpdateOutcome.UPDATED
        assert _stored_content(db, "r1") == "turn one"

    def test_a_writer_given_no_user_still_lands_when_the_run_knows_its_owner(self, db):
        """A run loaded from storage carries its owner even when the route does not."""
        _store_and_write(db, "r1", "original", user_id="u1")

        outcome = db.update_run(run=_agent_run("r1", user_id="u1", content="turn one"), session_id="s1")

        assert outcome is RunUpdateOutcome.UPDATED
        assert _stored_content(db, "r1") == "turn one"

    def test_a_writer_that_knows_no_user_is_not_refused(self, db):
        """A fact the writer does not know constrains nothing.

        The framework rebuilds a run from its id alone on some paths -- a
        cancellation caught with no run object in hand -- and requiring that
        unknown to be NULL would refuse the run's own final write. What stays
        refused is a writer presenting a DIFFERENT user; the session and the
        component the writer does know are still compared.
        """
        _store_and_write(db, "r1", "original", user_id="u1")

        outcome = db.update_run(run=_agent_run("r1", content="cancelled"), session_id="s1")

        assert outcome is RunUpdateOutcome.UPDATED
        assert _stored_content(db, "r1") == "cancelled"

    def test_a_run_rebuilt_from_its_id_alone_can_still_record_its_end(self, db):
        """The shape the cancellation path produces: only a run_id."""
        _store_and_write(db, "r1", "original", user_id="u1")
        bare = RunOutput(run_id="r1", content="cancelled")
        bare.status = RunStatus.cancelled

        outcome = db.update_run(run=bare, session_id="s1", user_id="u1")

        assert outcome is RunUpdateOutcome.UPDATED
        assert _stored_status(db, "r1") == RunStatus.cancelled.value

    def test_a_run_stored_unowned_is_saved_under_the_session_user(self, db):
        """The first save and the terminal save resolve identity differently.

        A run issued with no user_id on a session that has one creates its row
        unowned and is later saved with the session's user; the completed turn
        has to land, not be refused.
        """
        db.upsert_session(_agent_session(user_id="u1"))
        db.create_run(run=_agent_run("r1"), session_id="s1")

        outcome = db.update_run(run=_agent_run("r1", content="done"), session_id="s1", user_id="u1")

        assert outcome is RunUpdateOutcome.UPDATED
        assert _stored_content(db, "r1") == "done"

    def test_an_unowned_row_is_attributed_by_its_first_owner_write(self, db):
        """Creation can precede identity resolution; the column must catch up.

        Landing the write is not enough. A row left unowned stays adoptable by
        the next writer that names any user, so the owner has to be written
        onto it, and both backends have to write it.
        """
        db.upsert_session(_agent_session(user_id="u1"))
        db.create_run(run=_agent_run("r1"), session_id="s1")
        assert _stored_owner(db, "r1", "user_id") is None

        outcome = db.update_run(run=_agent_run("r1", content="done"), session_id="s1", user_id="u1")

        assert outcome is RunUpdateOutcome.UPDATED
        assert _stored_owner(db, "r1", "user_id") == "u1"

    def test_an_attributed_row_then_refuses_another_user(self, db):
        """What attribution buys: the second writer is out."""
        db.upsert_session(_agent_session(user_id="u1"))
        db.create_run(run=_agent_run("r1"), session_id="s1")
        db.update_run(run=_agent_run("r1", content="done"), session_id="s1", user_id="u1")

        outcome = db.update_run(run=_agent_run("r1", content="attacker"), session_id="s1", user_id="u2")

        assert outcome is RunUpdateOutcome.SCOPE_MISMATCH
        assert _stored_content(db, "r1") == "done"

    def test_a_component_less_row_is_attributed_by_the_first_write_that_names_one(self, db):
        """The component columns adopt the same way the user column does."""
        db.upsert_session(_agent_session())
        db.create_run(run=RunOutput(run_id="r1", session_id="s1"), session_id="s1")
        assert _stored_owner(db, "r1", "agent_id") is None

        outcome = db.update_run(run=_agent_run("r1", content="done"), session_id="s1")

        assert outcome is RunUpdateOutcome.UPDATED
        assert _stored_owner(db, "r1", "agent_id") == "a1"
        # And the row now belongs to that agent alone
        assert (
            db.update_run(run=_team_run("r1", content="attacker"), session_id="s1") is RunUpdateOutcome.SCOPE_MISMATCH
        )

    def test_a_resume_that_omits_the_user_still_lands(self, db):
        """AgentOS takes user_id as an optional form field on the continue route."""
        _store_and_write(db, "r1", "reserved", user_id="u1")
        paused = _agent_run("r1", user_id="u1", content="paused")
        paused.status = RunStatus.paused
        db.update_run(run=paused, session_id="s1", user_id="u1")

        # The route omits user_id; the run loaded from storage still carries it
        resumed = _agent_run("r1", user_id="u1", content="resumed")
        resumed.status = RunStatus.completed
        outcome = db.update_run(run=resumed, session_id="s1")

        assert outcome is RunUpdateOutcome.UPDATED
        assert _stored_content(db, "r1") == "resumed"

    def test_another_session_cannot_update(self, db):
        _store_and_write(db, "r1", "original")
        db.upsert_session(_agent_session("s2"))

        outcome = db.update_run(run=_agent_run("r1", session_id="s2", content="attacker"), session_id="s2")

        assert outcome is RunUpdateOutcome.SCOPE_MISMATCH
        assert _stored_content(db, "r1") == "original"

    def test_another_component_cannot_update(self, db):
        _store_and_write(db, "r1", "original")

        outcome = db.update_run(run=_team_run("r1", content="attacker"), session_id="s1")

        assert outcome is RunUpdateOutcome.SCOPE_MISMATCH
        assert _stored_content(db, "r1") == "original"

    def test_an_unknown_run_reports_missing(self, db):
        db.upsert_session(_agent_session())
        assert db.update_run(run=_agent_run("nope"), session_id="s1") is RunUpdateOutcome.MISSING

    def test_update_never_inserts(self, db):
        db.upsert_session(_agent_session())
        db.update_run(run=_agent_run("nope"), session_id="s1")
        assert db.get_run("nope") is None

    def test_update_preserves_the_run_index(self, db):
        db.upsert_session(_agent_session())
        db.create_run(run=_agent_run("r1"), session_id="s1")
        db.create_run(run=_agent_run("r2"), session_id="s1")
        first_index = _stored_index(db, "r1")

        db.update_run(run=_agent_run("r1", content="turn one"), session_id="s1")

        assert _stored_index(db, "r1") == first_index

    def test_terminal_writes_land_through_the_scoped_update(self, db):
        db.upsert_session(_agent_session(user_id="u1"))
        db.create_run(run=_agent_run("r1", user_id="u1"), session_id="s1", user_id="u1")
        final = _agent_run("r1", user_id="u1", content="done")
        final.status = RunStatus.completed

        assert db.update_run(run=final, session_id="s1", user_id="u1") is RunUpdateOutcome.UPDATED
        assert _stored_status(db, "r1") == RunStatus.completed.value


class TestScopedUpdatesAsync:
    @pytest.mark.asyncio
    async def test_the_owner_can_update(self, async_db):
        await async_db.upsert_session(_agent_session(user_id="u1"))
        await async_db.create_run(run=_agent_run("r1", user_id="u1"), session_id="s1", user_id="u1")

        outcome = await async_db.update_run(
            run=_agent_run("r1", user_id="u1", content="turn one"), session_id="s1", user_id="u1"
        )

        assert outcome is RunUpdateOutcome.UPDATED
        assert await _astored_content(async_db, "r1") == "turn one"

    @pytest.mark.asyncio
    async def test_another_user_cannot_update(self, async_db):
        await async_db.upsert_session(_agent_session(user_id="u1"))
        await async_db.create_run(run=_agent_run("r1", user_id="u1", content="original"), session_id="s1", user_id="u1")

        outcome = await async_db.update_run(
            run=_agent_run("r1", user_id="u2", content="attacker"), session_id="s1", user_id="u2"
        )

        assert outcome is RunUpdateOutcome.SCOPE_MISMATCH
        assert await _astored_content(async_db, "r1") == "original"

    @pytest.mark.asyncio
    async def test_another_session_cannot_update(self, async_db):
        await async_db.upsert_session(_agent_session())
        await async_db.upsert_session(_agent_session("s2"))
        await async_db.create_run(run=_agent_run("r1", content="original"), session_id="s1")

        outcome = await async_db.update_run(run=_agent_run("r1", session_id="s2", content="attacker"), session_id="s2")

        assert outcome is RunUpdateOutcome.SCOPE_MISMATCH
        assert await _astored_content(async_db, "r1") == "original"

    @pytest.mark.asyncio
    async def test_an_unknown_run_reports_missing(self, async_db):
        await async_db.upsert_session(_agent_session())
        assert await async_db.update_run(run=_agent_run("nope"), session_id="s1") is RunUpdateOutcome.MISSING


# ---------------------------------------------------------------------------
# Session insert-if-absent
# ---------------------------------------------------------------------------


class TestTheStoredRowIsTheRecord:
    """Ownership lives on the row, and a write reaches only its own session.

    The SQL adapters keep session and user in columns and scope every write by
    them. The in-memory adapter's run dict IS its row, so it has to carry the
    same facts: any second place to keep them is a place they can disagree,
    and the ownership check reads the row.
    """

    def test_the_owner_is_stamped_onto_the_stored_run(self, db):
        """The caller's user reaches the row even when the run does not carry it."""
        db.upsert_session(_agent_session(user_id="u1"))
        db.create_run(run=_agent_run("r1"), session_id="s1", user_id="u1")

        row = db.get_run("r1", deserialize=False)

        assert row["user_id"] == "u1"
        assert row["session_id"] == "s1"

    def test_a_write_cannot_reach_a_run_filed_under_another_session(self):
        """The SQL update carries session_id in its WHERE clause; so does this.

        A session imported carrying a run id that is already stored used to
        re-point the ownership record, and the write then landed on the other
        session's row. In-memory only: a SQL runs table cannot hold the same
        run_id twice, so only this adapter can reach the state at all.
        """
        db = InMemoryDb()
        db.upsert_session(_agent_session())
        db.create_run(run=_agent_run("r1", content="s1 content"), session_id="s1")
        db.upsert_session(
            AgentSession(
                session_id="s2",
                agent_id="a1",
                created_at=1,
                runs=[RunOutput(run_id="r1", session_id="s2", agent_id="a1", content="imported")],
            )
        )

        outcome = db.update_run(
            run=RunOutput(run_id="r1", session_id="s2", agent_id="a1", content="s2 content"), session_id="s2"
        )

        assert outcome is RunUpdateOutcome.UPDATED
        assert [row.get("content") for row in db.get_runs(session_id="s1", deserialize=False)[0]] == ["s1 content"]
        assert [row.get("content") for row in db.get_runs(session_id="s2", deserialize=False)[0]] == ["s2 content"]

    def test_a_run_stored_in_another_session_is_refused_not_missing(self, db):
        """Out of this write's reach is a refusal, not an invitation to create."""
        db.upsert_session(_agent_session())
        db.upsert_session(_agent_session("s2"))
        db.create_run(run=_agent_run("r1", content="original"), session_id="s1")

        outcome = db.update_run(run=RunOutput(run_id="r1", session_id="s2", agent_id="a1"), session_id="s2")

        assert outcome is RunUpdateOutcome.SCOPE_MISMATCH

    def test_a_stored_position_is_never_renumbered(self, db):
        """COALESCE(stored, incoming): the SQL update never moves a row."""
        db.upsert_session(_agent_session())
        db.create_run(run=_agent_run("r1"), session_id="s1")
        first = _stored_index(db, "r1")

        db.update_run(run=_agent_run("r1", content="later"), session_id="s1", run_index=99)

        assert _stored_index(db, "r1") == first


class TestAdapterContract:
    """What the pair owes callers beyond the happy path."""

    def test_a_string_result_is_read_as_the_outcome_it_names(self):
        """A third-party adapter can return the bare value.

        The outcome members are ``str``-valued, so an identity check against a
        returned "conflict" would fall through to the overwriting upsert. The
        sequence here is the create/update race: the update finds no row, the
        create loses to a concurrent writer, and the update is re-driven.
        """
        calls: List[str] = []

        class StringReturningDb:
            supports_atomic_run_creation = True
            upsert_called = False

            def update_run(self, **kwargs):
                calls.append("update")
                return "missing" if len(calls) == 1 else "updated"

            def create_run(self, **kwargs):
                calls.append("create")
                return "conflict"

            def upsert_run(self, **kwargs):
                StringReturningDb.upsert_called = True

        handled = persist_run_scoped(StringReturningDb(), _agent_run("r1"), session_id="s1")

        assert calls == ["update", "create", "update"]
        assert handled is True
        assert StringReturningDb.upsert_called is False

    def test_a_conflicting_create_re_drives_the_scoped_update(self):
        """The row a concurrent writer landed is still written under its scope."""
        seen: List[Dict[str, Any]] = []

        class RacingDb:
            supports_atomic_run_creation = True

            def update_run(self, **kwargs):
                seen.append(kwargs)
                return RunUpdateOutcome.MISSING if len(seen) == 1 else RunUpdateOutcome.SCOPE_MISMATCH

            def create_run(self, **kwargs):
                return RunCreateOutcome.CONFLICT

            def upsert_run(self, **kwargs):
                raise AssertionError("the legacy upsert must not run after a refused scope")

        assert persist_run_scoped(RacingDb(), _agent_run("r1"), session_id="s1") is True
        assert len(seen) == 2

    def test_an_unrecognised_update_result_never_falls_back_to_the_upsert(self):
        """UNSUPPORTED sends the caller to the overwriting upsert; a garbled
        answer must not be read as UNSUPPORTED."""

        class GarbledDb:
            supports_atomic_run_creation = True
            upsert_calls = 0

            def create_run(self, **kwargs):
                return RunCreateOutcome.CONFLICT

            def update_run(self, **kwargs):
                return "not-an-outcome"

            def upsert_run(self, **kwargs):
                GarbledDb.upsert_calls += 1

        database = GarbledDb()

        assert persist_run_scoped(database, _agent_run("r1", content="attacker"), session_id="s1") is True

        _drive_the_caller(database, _agent_run("r1", content="attacker"))
        assert GarbledDb.upsert_calls == 0

    def test_an_adapter_without_the_pair_hands_the_write_back(self):
        class UnportedDb:
            supports_atomic_run_creation = False

        assert persist_run_scoped(UnportedDb(), _agent_run("r1"), session_id="s1") is False

    def test_a_run_written_by_the_legacy_upsert_is_still_scoped(self, db):
        """upsert_run is the path unported callers and older code still use."""
        db.upsert_session(_agent_session(user_id="u1"))
        db.upsert_session(_agent_session("s2", user_id="u2"))
        db.upsert_run(
            run=_agent_run("r1", user_id="u1", content="original"), session_id="s1", user_id="u1", run_index=0
        )

        outcome = db.update_run(run=_agent_run("r1", user_id="u2", content="attacker"), session_id="s2", user_id="u2")

        assert outcome is RunUpdateOutcome.SCOPE_MISMATCH
        assert _stored_content(db, "r1") == "original"

    def test_a_deleted_run_does_not_hand_its_index_to_a_survivor(self, db):
        """Deleting the LAST run is the case a len()-based index survives.

        With three runs and the first deleted, len() gives the next run the
        index the third already holds; MAX+1 does not.
        """
        db.upsert_session(_agent_session())
        for run_id in ("r1", "r2", "r3"):
            db.create_run(run=_agent_run(run_id), session_id="s1")
        db.delete_run("r1")

        db.create_run(run=_agent_run("r4"), session_id="s1")

        assert _stored_index(db, "r4") not in (_stored_index(db, "r2"), _stored_index(db, "r3"))

    def test_a_deleted_run_frees_its_id(self, db):
        db.upsert_session(_agent_session())
        db.create_run(run=_agent_run("r1"), session_id="s1")
        db.delete_run("r1")

        assert db.create_run(run=_agent_run("r1"), session_id="s1") is RunCreateOutcome.CREATED

    def test_a_deleted_session_frees_the_ids_of_its_runs(self, db):
        db.upsert_session(_agent_session())
        db.create_run(run=_agent_run("r1"), session_id="s1")
        db.delete_session("s1")
        db.upsert_session(_agent_session("s2"))

        assert db.create_run(run=_agent_run("r1", session_id="s2"), session_id="s2") is RunCreateOutcome.CREATED


class TestAsyncPathsOffline:
    """The async twins, without needing a live PostgreSQL."""

    @pytest.mark.asyncio
    async def test_the_async_scoped_save_refuses_another_user(self, async_db):
        await async_db.upsert_session(_agent_session(user_id="u1"))
        await async_db.create_run(run=_agent_run("r1", user_id="u1", content="original"), session_id="s1", user_id="u1")

        handled = await apersist_run_scoped(
            async_db, _agent_run("r1", user_id="u2", content="attacker"), session_id="s1", user_id="u2"
        )

        assert handled is True
        assert await _astored_content(async_db, "r1") == "original"

    @pytest.mark.asyncio
    async def test_the_async_scoped_save_creates_a_run_that_was_never_reserved(self, async_db):
        await async_db.upsert_session(_agent_session())

        handled = await apersist_run_scoped(
            async_db, _agent_run("forked", content="forked"), session_id="s1", run_index=0
        )

        assert handled is True
        assert await _astored_content(async_db, "forked") == "forked"


# The ownership matrix. One row per (what the writer knows, what the row
# holds), so a writer whose identity resolves differently from the one that
# created the row is a table entry rather than a bug found a round later.
# stored -> incoming -> may the write land
OWNERSHIP_MATRIX = [
    # session
    ("same session", {"session_id": "s1"}, {"session_id": "s1"}, True),
    ("other session", {"session_id": "s1"}, {"session_id": "s2"}, False),
    # user
    ("same user", {"user_id": "u1"}, {"user_id": "u1"}, True),
    ("other user", {"user_id": "u1"}, {"user_id": "u2"}, False),
    ("unowned row, identified writer", {"user_id": None}, {"user_id": "u1"}, True),
    ("owned row, writer knows no user", {"user_id": "u1"}, {"user_id": None}, True),
    ("neither knows a user", {"user_id": None}, {"user_id": None}, True),
    # component
    ("same agent", {"agent_id": "a1"}, {"agent_id": "a1"}, True),
    ("other agent", {"agent_id": "a1"}, {"agent_id": "a2"}, False),
    ("team writing an agent row", {"agent_id": "a1"}, {"team_id": "t1"}, False),
    ("agent writing a team row", {"team_id": "t1"}, {"agent_id": "a1"}, False),
    ("same workflow", {"workflow_id": "w1"}, {"workflow_id": "w1"}, True),
    ("other workflow", {"workflow_id": "w1"}, {"workflow_id": "w2"}, False),
    ("workflow writing an agent row", {"agent_id": "a1"}, {"workflow_id": "w1"}, False),
    ("agent writing a workflow row", {"workflow_id": "w1"}, {"agent_id": "a1"}, False),
    ("writer knows no component", {"agent_id": "a1"}, {}, True),
    # The mirror of the unowned-user row, and adopted for the same reason.
    # Rows without a component id are real: a cancellation rebuilds a run
    # from its id alone, and a v3 migration brings rows across without one.
    # Refusing them locked those runs out of their own later saves.
    ("component-less row, writer knows one", {"agent_id": None}, {"agent_id": "a1"}, True),
    ("component-less row, workflow knows one", {"workflow_id": None}, {"workflow_id": "w1"}, True),
]


def _scope(**overrides):
    base = {"session_id": "s1", "user_id": None, "agent_id": None, "team_id": None, "workflow_id": None}
    base.update(overrides)
    return base


def _allowed_by_rule(stored, incoming, tmp_path):
    """The rule as the one Python function every non-SQL caller reaches."""
    return run_scope_allows(stored, incoming)


def _allowed_by_in_memory(stored, incoming, tmp_path):
    """The rule as the in-memory adapter applies it to its own rows."""
    return InMemoryDb._scope_matches(stored, incoming)


def _allowed_by_sql(stored, incoming, tmp_path):
    """The rule as the SQL predicate applies it, driven through a real update."""
    database = SqliteDb(db_file=str(tmp_path / "matrix.db"))
    for session_id in {stored["session_id"], incoming["session_id"]}:
        database.upsert_session(AgentSession(session_id=session_id, agent_id="a1", created_at=1))
    database.create_run(
        run=run_for_scope(stored, "r1", content="original"),
        session_id=stored["session_id"],
        user_id=stored["user_id"],
    )

    outcome = database.update_run(
        run=run_for_scope(incoming, "r1", content="written"),
        session_id=incoming["session_id"],
        user_id=incoming["user_id"],
    )

    return outcome is RunUpdateOutcome.UPDATED


# Three independent statements of the rule: the shared Python function that
# the reservation check reads through, the in-memory adapter's own predicate,
# and the SQL WHERE clause. Any of them drifting is a hole in exactly one
# backend, which is what makes them worth asserting separately. They take one
# signature so the table drives all three; only the SQL arm needs tmp_path.
OWNERSHIP_IMPLEMENTATIONS = [
    ("rule", _allowed_by_rule),
    ("in_memory", _allowed_by_in_memory),
    ("sql", _allowed_by_sql),
]


@pytest.mark.parametrize(
    "implementation",
    [impl for _, impl in OWNERSHIP_IMPLEMENTATIONS],
    ids=[name for name, _ in OWNERSHIP_IMPLEMENTATIONS],
)
@pytest.mark.parametrize("label,stored,incoming,allowed", OWNERSHIP_MATRIX, ids=[row[0] for row in OWNERSHIP_MATRIX])
def test_the_ownership_rule_is_one_table(label, stored, incoming, allowed, implementation, tmp_path):
    """One derivation, one rule, one place to change it.

    Every round of review has found a writer that resolved identity
    differently from the one that created the row. The rule lives in
    ``resolve_run_scope`` plus this table; a new writer is a row here, and
    every implementation of the rule answers the whole table the same way.
    """
    del label  # the row's label reaches the report as the parametrize id
    assert implementation(_scope(**stored), _scope(**incoming), tmp_path) is allowed


def run_for_scope(scope, run_id: str, content: str):
    """A run object presenting the identity a matrix row names.

    Public because the PostgreSQL twin drives the same table and each of the
    three component columns needs its own run class; a copy of this that knows
    only two silently turns those rows into component-less ones, which the
    rule then allows.
    """
    if scope["team_id"] is not None:
        return TeamRunOutput(
            run_id=run_id,
            session_id=scope["session_id"],
            team_id=scope["team_id"],
            user_id=scope["user_id"],
            content=content,
        )
    if scope["workflow_id"] is not None:
        return WorkflowRunOutput(
            run_id=run_id,
            session_id=scope["session_id"],
            workflow_id=scope["workflow_id"],
            user_id=scope["user_id"],
            content=content,
        )
    return RunOutput(
        run_id=run_id,
        session_id=scope["session_id"],
        agent_id=scope["agent_id"],
        user_id=scope["user_id"],
        content=content,
    )


class TestTheUpdateNeverMovesARow:
    """A scoped update writes content, never identity.

    The legacy ``upsert_run`` keeps the identity columns out of its conflict
    set on purpose. An update that rewrote them could move a stored row into
    a session or a type its owner never sees, and the owner is then locked
    out of its own run by the very scope that protects it.
    """

    def test_a_save_naming_a_foreign_session_does_not_move_the_row(self, db):
        db.upsert_session(_agent_session())
        db.upsert_session(_agent_session("s2"))
        db.create_run(run=_agent_run("r1", content="one"), session_id="s1")

        # The write is addressed at s1; the run object it carries says s2
        db.update_run(run=RunOutput(run_id="r1", session_id="s2", agent_id="a1", content="two"), session_id="s1")

        assert db.get_run("r1", deserialize=False)["session_id"] == "s1"
        assert db.update_run(run=_agent_run("r1", content="three"), session_id="s1") is RunUpdateOutcome.UPDATED

    def test_a_dict_shaped_save_does_not_relabel_the_run(self, db):
        """A dict with no component id would otherwise be read as a workflow."""
        db.upsert_session(_agent_session())
        db.create_run(run=_agent_run("r1", content="one"), session_id="s1")
        before = _run_type_of(db, "r1")

        db.update_run(run={"run_id": "r1", "content": "two"}, session_id="s1")

        assert _run_type_of(db, "r1") == before

    def test_a_team_shaped_save_does_not_relabel_an_agent_run(self, db):
        db.upsert_session(_agent_session())
        db.create_run(run=_agent_run("r1", content="one"), session_id="s1")
        before = _run_type_of(db, "r1")

        db.update_run(
            run=TeamRunOutput(run_id="r1", session_id="s1", team_id="t1", content="two"),
            session_id="s1",
        )

        assert _run_type_of(db, "r1") == before


def _run_type_of(db: Any, run_id: str) -> Optional[str]:
    """The class a reader actually gets back for a stored run.

    Not ``get_run_type`` on the row: that recovers the type from the
    component id, so it answers correctly even when the stored type column is
    wrong. What a caller sees is the deserialized class, so that is the
    assertion.
    """
    run = db.get_run(run_id)
    return None if run is None else type(run).__name__


class TestUnrecognisedAdapterAnswers:
    """A garbled answer must never be the one that reaches the overwrite.

    Both coercions turn an answer they cannot read into a FINAL outcome, so
    an adapter returning nonsense drops the write loudly instead of handing
    it to the unscoped save.
    """

    def test_an_unreadable_create_answer_is_not_a_success(self):
        """UNSUPPORTED is the only create answer that reaches the legacy save."""

        class GarbledCreateDb:
            supports_atomic_run_creation = True
            upsert_calls = 0

            def update_run(self, **kwargs):
                return RunUpdateOutcome.MISSING

            def create_run(self, **kwargs):
                return "not an outcome"

            def upsert_run(self, **kwargs):
                GarbledCreateDb.upsert_calls += 1

        database = GarbledCreateDb()

        assert persist_run_scoped(database, _agent_run("r1"), session_id="s1") is True

        _drive_the_caller(database, _agent_run("r1"))
        assert GarbledCreateDb.upsert_calls == 0

    def test_an_unreadable_update_answer_is_not_a_success(self):
        class GarbledUpdateDb:
            supports_atomic_run_creation = True

            def update_run(self, **kwargs):
                return object()

            def create_run(self, **kwargs):
                raise AssertionError("the update answer was final; the create must not run")

        assert persist_run_scoped(GarbledUpdateDb(), _agent_run("r1"), session_id="s1") is True

    def test_a_create_conflict_never_reaches_the_legacy_save(self):
        """The conflict is the refusal; falling through would overwrite."""

        class ConflictingDb:
            supports_atomic_run_creation = True
            upsert_calls = 0

            def update_run(self, **kwargs):
                return RunUpdateOutcome.MISSING

            def create_run(self, **kwargs):
                return RunCreateOutcome.CONFLICT

            def upsert_run(self, **kwargs):
                ConflictingDb.upsert_calls += 1

        database = ConflictingDb()

        assert persist_run_scoped(database, _agent_run("r1"), session_id="s1") is True

        _drive_the_caller(database, _agent_run("r1"))
        assert ConflictingDb.upsert_calls == 0


# How each outcome the pair can answer with is routed. Every row states the
# same three things: whether the save reports itself handled, whether the
# strict create was reached at all, and whether the write ended up at the
# overwriting ``upsert_run``. Only UNSUPPORTED may end up there.
# label -> update answers -> create answer -> handled, creates, overwrite
ROUTING_CASES = [
    (
        "the create finds no session row",
        [RunUpdateOutcome.MISSING],
        RunCreateOutcome.SESSION_MISSING,
        True,
        1,
        False,
    ),
    ("the create errors", [RunUpdateOutcome.MISSING], RunCreateOutcome.ERROR, True, 1, False),
    ("the create is unsupported", [RunUpdateOutcome.MISSING], RunCreateOutcome.UNSUPPORTED, False, 1, True),
    # The update answered, so the create is never asked. The placeholder
    # answer is CREATED so a routing that wrongly asked would report handled
    # and be caught by the flag as well as by the call count.
    ("the update is unsupported", [RunUpdateOutcome.UNSUPPORTED], RunCreateOutcome.CREATED, False, 0, True),
    ("the update errors", [RunUpdateOutcome.ERROR], RunCreateOutcome.CREATED, True, 0, False),
]

ROUTING_IDS = [row[0] for row in ROUTING_CASES]
ROUTING_ARGS = [row[1:] for row in ROUTING_CASES]


class _RoutingDb:
    """An adapter answering with the outcomes a routing case names.

    Counts every call, so "the create was never asked" and "the overwrite was
    never reached" are assertions rather than assumptions.
    """

    supports_atomic_run_creation = True

    def __init__(self, update_answers, create_answer):
        self._update_answers = list(update_answers)
        self._create_answer = create_answer
        self.update_calls = 0
        self.create_calls = 0
        self.upsert_calls = 0

    def update_run(self, **kwargs):
        self.update_calls += 1
        return self._update_answers[min(self.update_calls - 1, len(self._update_answers) - 1)]

    def create_run(self, **kwargs):
        self.create_calls += 1
        return self._create_answer

    def upsert_run(self, **kwargs):
        self.upsert_calls += 1


class TestOutcomeRouting:
    """Each outcome the pair can answer with, and where the write ends up.

    The refusals are the cases with teeth: SESSION_MISSING and ERROR mean the
    run was not stored, and reading either as "not ours to answer" hands the
    write to the unscoped save the module exists to keep it away from.
    """

    @pytest.mark.parametrize("update_answers,create_answer,handled,creates,overwrite", ROUTING_ARGS, ids=ROUTING_IDS)
    def test_the_save_reports_what_it_did(self, update_answers, create_answer, handled, creates, overwrite):
        del overwrite  # the caller-driven test below is what observes it
        database = _RoutingDb(update_answers, create_answer)

        assert persist_run_scoped(database, _agent_run("r1"), session_id="s1") is handled
        assert database.create_calls == creates
        # Only a CONFLICT re-drives the update, and no case here reports one
        assert database.update_calls == 1

    @pytest.mark.parametrize("update_answers,create_answer,handled,creates,overwrite", ROUTING_ARGS, ids=ROUTING_IDS)
    def test_only_unsupported_reaches_the_overwriting_save(
        self, update_answers, create_answer, handled, creates, overwrite
    ):
        del handled, creates
        database = _RoutingDb(update_answers, create_answer)

        _drive_the_caller(database, _agent_run("r1"))

        assert (database.upsert_calls == 1) is overwrite

    @pytest.mark.asyncio
    @pytest.mark.parametrize("update_answers,create_answer,handled,creates,overwrite", ROUTING_ARGS, ids=ROUTING_IDS)
    async def test_the_async_save_routes_them_the_same_way(
        self, update_answers, create_answer, handled, creates, overwrite
    ):
        """The async twin repeats the routing, so it can drift from it."""
        del overwrite
        database = _RoutingDb(update_answers, create_answer)

        assert await apersist_run_scoped(database, _agent_run("r1"), session_id="s1") is handled
        assert database.create_calls == creates


class TestForeignKeyClassification:
    """A missing session row has to be told apart from every other
    integrity failure, and drivers disagree about how they report it."""

    def test_the_standard_sqlstate_is_a_foreign_key(self):
        assert is_foreign_key_violation(_integrity_error(sqlstate="23503")) is True

    def test_a_non_foreign_key_sqlstate_is_not(self):
        assert is_foreign_key_violation(_integrity_error(sqlstate="23502", message="null value")) is False

    def test_a_family_sqlstate_still_reads_the_message(self):
        """MySQL reports 23000 for the whole integrity family."""
        assert (
            is_foreign_key_violation(_integrity_error(sqlstate="23000", message="FOREIGN KEY constraint fails")) is True
        )

    def test_no_sqlstate_falls_back_to_the_message(self):
        """SQLite exposes none."""
        assert is_foreign_key_violation(_integrity_error(message="FOREIGN KEY constraint failed")) is True
        assert is_foreign_key_violation(_integrity_error(message="NOT NULL constraint failed")) is False

    def test_an_error_with_no_driver_exception_is_not_one(self):
        assert is_foreign_key_violation(Exception("boom")) is False


def _integrity_error(sqlstate: Optional[str] = None, message: str = "constraint failed") -> Exception:
    """An IntegrityError shaped like the driver ones the check inspects."""

    class _Orig(Exception):
        pass

    orig = _Orig(message)
    if sqlstate is not None:
        orig.sqlstate = sqlstate  # type: ignore[attr-defined]
    error = Exception(message)
    error.orig = orig  # type: ignore[attr-defined]
    return error


class TestOutcomeClassification:
    """Every outcome is classified once, so none defaults to the overwrite."""

    def test_every_create_outcome_is_classified_exactly_once(self):
        """Both sets are written out, so a new member lands in neither."""
        assert FALLBACK_ALLOWED_CREATE | FINAL_CREATE == frozenset(RunCreateOutcome)
        assert len(FALLBACK_ALLOWED_CREATE) + len(FINAL_CREATE) == len(RunCreateOutcome)

    def test_every_update_outcome_is_classified_exactly_once(self):
        classified = [FALLBACK_ALLOWED_UPDATE, CREATE_NEEDED_UPDATE, FINAL_UPDATE]
        assert set().union(*classified) == frozenset(RunUpdateOutcome)
        assert sum(len(one) for one in classified) == len(RunUpdateOutcome)

    def test_only_unsupported_lets_a_creation_reach_the_legacy_save(self):
        """Any other create outcome reaching upsert_run is an overwrite."""
        assert FALLBACK_ALLOWED_CREATE == frozenset({RunCreateOutcome.UNSUPPORTED})


# The row fields both adapters are expected to agree on. Timestamps are left
# out because they are wall-clock, and run_type because the in-memory adapter
# derives it on read instead of storing it. Everything the scoped write sets
# or deliberately preserves is in.
_COMPARED_COLUMNS = (
    "run_id",
    "session_id",
    "user_id",
    "agent_id",
    "team_id",
    "workflow_id",
    "parent_run_id",
    "status",
    "run_index",
)


def _comparable_row(db: Any, run_id: str):
    row = db.get_run(run_id, deserialize=False)
    if row is None:
        return None
    return ({column: row.get(column) for column in _COMPARED_COLUMNS}, _payload(row).get("content"))


def _reads(db: Any):
    """What the read filters return, which is how the rows are actually seen.

    ``user_id`` is not among them: the in-memory adapter scopes run reads by
    the session's owner while the SQL adapters scope them by the run row's
    own, which predates the scoped write path and is not its to change.
    """
    # Every filter here selects at least one row of the sequence that drives
    # it; one that matches nothing compares two empty lists and asserts that
    # neither backend has any rows, which is not the claim.
    filters = [
        {"session_id": "s1"},
        {"session_id": "s2"},
        {"agent_id": "a1"},
        {"team_id": "t1"},
        {"status": RunStatus.running},
        {"session_id": "s1", "agent_id": "a1"},
        {"session_id": "s2", "team_id": "t1"},
    ]
    seen = []
    for one in filters:
        rows, total = db.get_runs(deserialize=False, **one)
        seen.append((tuple(sorted(one.items())), sorted(row["run_id"] for row in rows), total))
    return seen


class TestBackendsAgree:
    """The in-memory adapter hand-writes the SQL predicates; they must match.

    Each round of review found another way the twin diverged, so the two are
    driven through the same sequence and compared rather than described twice.
    """

    def test_the_same_sequence_produces_the_same_outcomes_and_rows(self, tmp_path):
        # A team run in the second session, so the reads compared below
        # actually select something through every filter they apply
        sequence = [
            ("create", "r1", "s1", "u1", "first", "agent"),
            ("update", "r1", "s1", "u1", "second", "agent"),
            ("update", "r1", "s1", "u2", "attacker", "agent"),
            ("update", "r1", "s2", "u1", "other session", "agent"),
            ("create", "r1", "s1", "u1", "again", "agent"),
            ("create", "r2", "s1", None, "anonymous", "agent"),
            ("update", "r2", "s1", "u1", "attributed", "agent"),
            ("update", "missing", "s1", "u1", "nothing", "agent"),
            ("create", "r3", "s2", None, "team run", "team"),
            ("update", "r3", "s2", None, "team turn", "team"),
            ("update", "r3", "s2", None, "agent reaching a team row", "agent"),
        ]
        results = {}
        for name, database in (
            ("memory", InMemoryDb()),
            ("sqlite", SqliteDb(db_file=str(tmp_path / "differential.db"))),
        ):
            for session_id in ("s1", "s2"):
                database.upsert_session(AgentSession(session_id=session_id, agent_id="a1", user_id=None, created_at=1))
            outcomes = []
            for op, run_id, session_id, user_id, content, kind in sequence:
                if kind == "team":
                    run: Any = TeamRunOutput(
                        run_id=run_id, session_id=session_id, team_id="t1", user_id=user_id, content=content
                    )
                else:
                    run = RunOutput(
                        run_id=run_id, session_id=session_id, agent_id="a1", user_id=user_id, content=content
                    )
                call = database.create_run if op == "create" else database.update_run
                outcomes.append((op, run_id, call(run=run, session_id=session_id, user_id=user_id).value))
            results[name] = (
                outcomes,
                [_comparable_row(database, rid) for rid in ("r1", "r2", "r3", "missing")],
                _reads(database),
            )

        # A filter that selects nothing would compare two empty lists and
        # assert only that neither backend has rows
        assert all(run_ids for _, run_ids, _ in results["memory"][2])
        assert results["memory"] == results["sqlite"]


class TestWorkflowRunsAreScopedToo:
    """Workflow runs go through the same save path as agents and teams.

    They make no reservation -- the ticket scopes that to Agent and Team --
    but their lifecycle writes must not be able to land on another session's
    run either.
    """

    def _workflow(self, db):
        from agno.workflow.workflow import Workflow

        return Workflow(name="w", id="w1", db=db, steps=[], telemetry=False)

    def test_a_workflow_run_cannot_overwrite_another_sessions_run(self, db):
        db.upsert_session(_agent_session("victim", user_id="victim-user"))
        db.upsert_session(WorkflowSession(session_id="attacker", workflow_id="w1", created_at=1))
        db.create_run(
            run=_agent_run("r1", session_id="victim", user_id="victim-user", content="original"),
            session_id="victim",
            user_id="victim-user",
        )
        workflow = self._workflow(db)
        colliding = WorkflowRunOutput(run_id="r1", session_id="attacker", workflow_id="w1", content="attacker")

        workflow.save_run(run=colliding, session_id="attacker", run_index=0)

        assert _stored_content(db, "r1") == "original"

    @pytest.mark.asyncio
    async def test_the_async_workflow_save_is_scoped_too(self, db):
        db.upsert_session(_agent_session("victim", user_id="victim-user"))
        db.upsert_session(WorkflowSession(session_id="attacker", workflow_id="w1", created_at=1))
        db.create_run(
            run=_agent_run("r1", session_id="victim", user_id="victim-user", content="original"),
            session_id="victim",
            user_id="victim-user",
        )
        workflow = self._workflow(db)
        colliding = WorkflowRunOutput(run_id="r1", session_id="attacker", workflow_id="w1", content="attacker")

        await workflow.asave_run(run=colliding, session_id="attacker", run_index=0)

        assert _stored_content(db, "r1") == "original"

    def test_a_workflow_run_of_its_own_still_saves(self, db):
        db.upsert_session(WorkflowSession(session_id="s1", workflow_id="w1", created_at=1))
        workflow = self._workflow(db)
        run = WorkflowRunOutput(run_id="own", session_id="s1", workflow_id="w1", content="written")

        workflow.save_run(run=run, session_id="s1", run_index=0)

        assert _stored_content(db, "own") == "written"
