"""Run creation and scoped updates on the PostgreSQL adapters.

Mirror of test_run_creation_isolation.py (in-memory + SQLite) against a live
Postgres (cookbook/scripts/run_pgvector.sh, port 5532), sync and async. The
concurrency cases matter most here: the winner is picked by the database's own
primary key, not by any check the process performs.

Each test runs in its own schema, dropped on teardown. The whole module skips
when psycopg is missing or the server is unreachable.
"""

import asyncio
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

import pytest

pytest.importorskip("psycopg")

from sqlalchemy import create_engine, text  # noqa: E402

from agno.db.postgres import PostgresDb  # noqa: E402
from agno.db.postgres.async_postgres import AsyncPostgresDb  # noqa: E402
from agno.db.run_writes import (  # noqa: E402
    RunCreateOutcome,
    RunUpdateOutcome,
    supports_atomic_run_creation,
)
from agno.run.agent import RunOutput  # noqa: E402
from agno.run.base import RunStatus  # noqa: E402
from agno.run.team import TeamRunOutput  # noqa: E402
from agno.session import AgentSession, TeamSession  # noqa: E402
from tests.unit.db.test_run_creation_isolation import OWNERSHIP_MATRIX, run_for_scope  # noqa: E402

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"

CONCURRENT_WRITERS = 8

# Every wait a concurrency case performs is bounded by this, so a writer that
# never arrives at the barrier or a statement that never returns fails the test
# instead of hanging the suite.
CONCURRENCY_TIMEOUT_SECONDS = 10.0


def _writer_barrier() -> threading.Barrier:
    return threading.Barrier(CONCURRENT_WRITERS, timeout=CONCURRENCY_TIMEOUT_SECONDS)


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

    threads = [threading.Thread(target=guarded, args=(i,), daemon=True) for i in range(CONCURRENT_WRITERS)]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + CONCURRENCY_TIMEOUT_SECONDS
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    still_running = [thread for thread in threads if thread.is_alive()]
    if still_running:
        raise AssertionError(
            f"{len(still_running)} of {CONCURRENT_WRITERS} writers were still running after "
            f"{CONCURRENCY_TIMEOUT_SECONDS}s"
        )
    if failures:
        raise AssertionError(f"{len(failures)} of {CONCURRENT_WRITERS} writers raised; first: {failures[0]!r}")


def _server_reachable() -> bool:
    engine = create_engine(DB_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def _postgres_server():
    if not _server_reachable():
        pytest.skip(f"Postgres server not reachable at {DB_URL}")


def _drop_schema(schema: str) -> None:
    engine = create_engine(DB_URL)
    try:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    finally:
        engine.dispose()


@pytest.fixture
def db(_postgres_server):
    schema = f"run_write_{uuid.uuid4().hex[:8]}"
    database = PostgresDb(db_url=DB_URL, db_schema=schema, id=f"run-write-{schema}")
    try:
        yield database
    finally:
        # The adapter's own pool holds connections into this schema; DROP
        # SCHEMA CASCADE blocks behind them, and every test would leak a pool.
        database.db_engine.dispose()
        _drop_schema(schema)


@pytest.fixture
async def async_db(_postgres_server):
    schema = f"run_write_async_{uuid.uuid4().hex[:8]}"
    database = AsyncPostgresDb(db_url=DB_URL, db_schema=schema, id=f"run-write-async-{schema}")
    try:
        yield database
    finally:
        await database.db_engine.dispose()
        _drop_schema(schema)


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


def _stored_content(db: Any, run_id: str) -> Optional[str]:
    row: Optional[Dict[str, Any]] = db.get_run(run_id, deserialize=False)
    return None if row is None else (row["run_data"] or {}).get("content")


async def _astored_content(db: Any, run_id: str) -> Optional[str]:
    row = await db.get_run(run_id, deserialize=False)
    return None if row is None else (row["run_data"] or {}).get("content")


def _stored_status(db: Any, run_id: str) -> Optional[str]:
    row: Optional[Dict[str, Any]] = db.get_run(run_id, deserialize=False)
    return None if row is None else (row["run_data"] or {}).get("status")


def _stored_index(db: Any, run_id: str) -> Optional[int]:
    row: Optional[Dict[str, Any]] = db.get_run(run_id, deserialize=False)
    return None if row is None else row["run_index"]


class TestPostgresStrictCreation:
    def test_adapter_advertises_atomic_creation(self, db):
        assert supports_atomic_run_creation(db) is True

    def test_fresh_id_is_created(self, db):
        db.upsert_session(_agent_session())
        assert db.create_run(run=_agent_run("r1"), session_id="s1") is RunCreateOutcome.CREATED

    def test_taken_id_conflicts_and_leaves_the_stored_run_untouched(self, db):
        db.upsert_session(_agent_session())
        db.create_run(run=_agent_run("r1", content="original"), session_id="s1")

        outcome = db.create_run(run=_agent_run("r1", content="attacker"), session_id="s1")

        assert outcome is RunCreateOutcome.CONFLICT
        assert _stored_content(db, "r1") == "original"

    def test_taken_id_conflicts_across_sessions_and_users(self, db):
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

    def test_creation_reports_a_missing_session_and_inserts_nothing(self, db):
        assert db.create_run(run=_agent_run("r1"), session_id="s1") is RunCreateOutcome.SESSION_MISSING
        assert db.get_run("r1") is None

    def test_team_runs_get_the_same_refusal(self, db):
        db.upsert_session(_team_session())
        db.create_run(run=_team_run("r1", content="original"), session_id="s1")

        assert db.create_run(run=_team_run("r1", content="attacker"), session_id="s1") is RunCreateOutcome.CONFLICT
        assert _stored_content(db, "r1") == "original"

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


class TestPostgresConcurrentCreation:
    def test_barrier_started_creations_of_one_fresh_id_produce_one_winner(self, db):
        db.upsert_session(_agent_session())
        barrier = _writer_barrier()
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
        barrier = _writer_barrier()
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

    def test_barrier_started_creations_of_distinct_ids_each_take_their_own_position(self, db):
        """Contention over the position, not over the id.

        Each writer creates an id of its own, so none of them conflict; what
        they contend for is the next run_index in the shared session. Two
        writers reading the same maximum would hand out the same position.
        """
        db.upsert_session(_agent_session())
        barrier = _writer_barrier()
        outcomes: List[RunCreateOutcome] = []
        lock = threading.Lock()

        def attempt(index: int) -> None:
            run = _agent_run(f"r{index}", content=f"writer-{index}")
            barrier.wait()
            outcome = db.create_run(run=run, session_id="s1")
            with lock:
                outcomes.append(outcome)

        _run_threads(attempt)

        assert outcomes.count(RunCreateOutcome.CREATED) == CONCURRENT_WRITERS
        positions = [_stored_index(db, f"r{index}") for index in range(CONCURRENT_WRITERS)]
        assert None not in positions
        assert sorted(positions) == list(range(CONCURRENT_WRITERS))


class TestPostgresScopedUpdates:
    def test_the_owner_can_update(self, db):
        db.upsert_session(_agent_session(user_id="u1"))
        db.create_run(run=_agent_run("r1", user_id="u1"), session_id="s1", user_id="u1")

        outcome = db.update_run(run=_agent_run("r1", user_id="u1", content="turn one"), session_id="s1", user_id="u1")

        assert outcome is RunUpdateOutcome.UPDATED
        assert _stored_content(db, "r1") == "turn one"

    def test_an_anonymous_run_is_updatable_by_the_same_anonymous_caller(self, db):
        db.upsert_session(_agent_session())
        db.create_run(run=_agent_run("r1"), session_id="s1")

        assert db.update_run(run=_agent_run("r1", content="turn one"), session_id="s1") is RunUpdateOutcome.UPDATED
        assert _stored_content(db, "r1") == "turn one"

    def test_another_user_cannot_update(self, db):
        db.upsert_session(_agent_session(user_id="u1"))
        db.create_run(run=_agent_run("r1", user_id="u1", content="original"), session_id="s1", user_id="u1")

        outcome = db.update_run(run=_agent_run("r1", user_id="u2", content="attacker"), session_id="s1", user_id="u2")

        assert outcome is RunUpdateOutcome.SCOPE_MISMATCH
        assert _stored_content(db, "r1") == "original"

    def test_an_unowned_run_accepts_an_identified_writer(self, db):
        db.upsert_session(_agent_session())
        db.create_run(run=_agent_run("r1", content="original"), session_id="s1")

        outcome = db.update_run(run=_agent_run("r1", user_id="u2", content="turn one"), session_id="s1", user_id="u2")

        assert outcome is RunUpdateOutcome.UPDATED
        assert _stored_content(db, "r1") == "turn one"

    def test_a_writer_given_no_user_still_lands_when_the_run_knows_its_owner(self, db):
        """NULL semantics differ per dialect, so both directions are checked here."""
        db.upsert_session(_agent_session(user_id="u1"))
        db.create_run(run=_agent_run("r1", user_id="u1", content="original"), session_id="s1", user_id="u1")

        outcome = db.update_run(run=_agent_run("r1", user_id="u1", content="turn one"), session_id="s1")

        assert outcome is RunUpdateOutcome.UPDATED
        assert _stored_content(db, "r1") == "turn one"

    def test_a_run_rebuilt_from_its_id_alone_can_still_record_its_end(self, db):
        """The shape the cancellation path produces: only a run_id."""
        db.upsert_session(_agent_session(user_id="u1"))
        db.create_run(run=_agent_run("r1", user_id="u1", content="original"), session_id="s1", user_id="u1")
        bare = RunOutput(run_id="r1", content="cancelled")
        bare.status = RunStatus.cancelled

        outcome = db.update_run(run=bare, session_id="s1", user_id="u1")

        assert outcome is RunUpdateOutcome.UPDATED
        assert _stored_content(db, "r1") == "cancelled"
        assert _stored_status(db, "r1") == RunStatus.cancelled.value

    def test_terminal_writes_land_through_the_scoped_update(self, db):
        db.upsert_session(_agent_session(user_id="u1"))
        db.create_run(run=_agent_run("r1", user_id="u1"), session_id="s1", user_id="u1")
        final = _agent_run("r1", user_id="u1", content="done")
        final.status = RunStatus.completed

        assert db.update_run(run=final, session_id="s1", user_id="u1") is RunUpdateOutcome.UPDATED
        assert _stored_status(db, "r1") == RunStatus.completed.value

    def test_update_preserves_the_run_index(self, db):
        db.upsert_session(_agent_session())
        db.create_run(run=_agent_run("r1"), session_id="s1")
        db.create_run(run=_agent_run("r2"), session_id="s1")
        first_index = _stored_index(db, "r1")

        db.update_run(run=_agent_run("r1", content="turn one"), session_id="s1")

        assert _stored_index(db, "r1") == first_index

    def test_a_stored_position_is_never_renumbered(self, db):
        """COALESCE(stored, incoming): the update never moves a row."""
        db.upsert_session(_agent_session())
        db.create_run(run=_agent_run("r1"), session_id="s1")
        first_index = _stored_index(db, "r1")

        db.update_run(run=_agent_run("r1", content="later"), session_id="s1", run_index=99)

        assert _stored_index(db, "r1") == first_index

    def test_an_unowned_row_is_attributed_by_its_first_owner_write(self, db):
        """Creation can precede identity resolution; the column must catch up."""
        db.upsert_session(_agent_session(user_id="u1"))
        db.create_run(run=_agent_run("r1"), session_id="s1")

        db.update_run(run=_agent_run("r1", content="done"), session_id="s1", user_id="u1")

        assert db.get_run("r1", deserialize=False)["user_id"] == "u1"

    def test_another_session_cannot_update(self, db):
        db.upsert_session(_agent_session())
        db.upsert_session(_agent_session("s2"))
        db.create_run(run=_agent_run("r1", content="original"), session_id="s1")

        outcome = db.update_run(run=_agent_run("r1", session_id="s2", content="attacker"), session_id="s2")

        assert outcome is RunUpdateOutcome.SCOPE_MISMATCH
        assert _stored_content(db, "r1") == "original"

    def test_another_component_cannot_update(self, db):
        db.upsert_session(_agent_session())
        db.create_run(run=_agent_run("r1", content="original"), session_id="s1")

        assert (
            db.update_run(run=_team_run("r1", content="attacker"), session_id="s1") is RunUpdateOutcome.SCOPE_MISMATCH
        )
        assert _stored_content(db, "r1") == "original"

    def test_an_unknown_run_reports_missing_and_inserts_nothing(self, db):
        db.upsert_session(_agent_session())

        assert db.update_run(run=_agent_run("nope"), session_id="s1") is RunUpdateOutcome.MISSING
        assert db.get_run("nope") is None


class TestAsyncPostgres:
    @pytest.mark.asyncio
    async def test_adapter_advertises_atomic_creation(self, async_db):
        assert supports_atomic_run_creation(async_db) is True

    @pytest.mark.asyncio
    async def test_taken_id_conflicts_and_leaves_the_stored_run_untouched(self, async_db):
        await async_db.upsert_session(_agent_session())
        await async_db.create_run(run=_agent_run("r1", content="original"), session_id="s1")

        outcome = await async_db.create_run(run=_agent_run("r1", content="attacker"), session_id="s1")

        assert outcome is RunCreateOutcome.CONFLICT
        assert await _astored_content(async_db, "r1") == "original"

    @pytest.mark.asyncio
    async def test_creation_reports_a_missing_session_and_inserts_nothing(self, async_db):
        assert await async_db.create_run(run=_agent_run("r1"), session_id="s1") is RunCreateOutcome.SESSION_MISSING
        assert await async_db.get_run("r1") is None

    @pytest.mark.asyncio
    async def test_fresh_id_is_created(self, async_db):
        await async_db.upsert_session(_agent_session())

        assert await async_db.create_run(run=_agent_run("r1"), session_id="s1") is RunCreateOutcome.CREATED
        assert await async_db.get_run("r1") is not None

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
        outcomes = list(await asyncio.wait_for(asyncio.gather(*tasks), CONCURRENCY_TIMEOUT_SECONDS))

        assert outcomes.count(RunCreateOutcome.CREATED) == 1
        assert outcomes.count(RunCreateOutcome.CONFLICT) == CONCURRENT_WRITERS - 1

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
    async def test_the_owner_can_update(self, async_db):
        await async_db.upsert_session(_agent_session(user_id="u1"))
        await async_db.create_run(run=_agent_run("r1", user_id="u1"), session_id="s1", user_id="u1")

        outcome = await async_db.update_run(
            run=_agent_run("r1", user_id="u1", content="turn one"), session_id="s1", user_id="u1"
        )

        assert outcome is RunUpdateOutcome.UPDATED
        assert await _astored_content(async_db, "r1") == "turn one"


# The ownership matrix is stated once, in the in-memory and SQLite suite, and
# read from there. Postgres is the dialect whose NULL comparisons can disagree
# with the others, so it answers the same table rather than a copy of it.
OWNERSHIP_IDS = [row[0] for row in OWNERSHIP_MATRIX]
OWNERSHIP_CASES = [row[1:] for row in OWNERSHIP_MATRIX]


def _scope(**overrides: Optional[str]) -> Dict[str, Optional[str]]:
    base: Dict[str, Optional[str]] = {
        "session_id": "s1",
        "user_id": None,
        "agent_id": None,
        "team_id": None,
        "workflow_id": None,
    }
    base.update(overrides)
    return base


class TestPostgresOwnershipMatrix:
    """One derivation of the rule, and Postgres answers the whole table.

    A writer whose identity resolves differently from the one that created the
    row is a row in this table rather than a bug found a round later.
    """

    @pytest.mark.parametrize("stored,incoming,allowed", OWNERSHIP_CASES, ids=OWNERSHIP_IDS)
    def test_the_scoped_update_lands_exactly_where_the_rule_allows(self, db, stored, incoming, allowed):
        stored_scope = _scope(**stored)
        incoming_scope = _scope(**incoming)
        for session_id in {stored_scope["session_id"], incoming_scope["session_id"]}:
            db.upsert_session(_agent_session(session_id))
        db.create_run(
            run=run_for_scope(stored_scope, "r1", "original"),
            session_id=stored_scope["session_id"],
            user_id=stored_scope["user_id"],
        )

        outcome = db.update_run(
            run=run_for_scope(incoming_scope, "r1", "written"),
            session_id=incoming_scope["session_id"],
            user_id=incoming_scope["user_id"],
        )

        assert (outcome is RunUpdateOutcome.UPDATED) is allowed
        assert _stored_content(db, "r1") == ("written" if allowed else "original")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("stored,incoming,allowed", OWNERSHIP_CASES, ids=OWNERSHIP_IDS)
    async def test_the_async_scoped_update_lands_exactly_where_the_rule_allows(
        self, async_db, stored, incoming, allowed
    ):
        stored_scope = _scope(**stored)
        incoming_scope = _scope(**incoming)
        for session_id in {stored_scope["session_id"], incoming_scope["session_id"]}:
            await async_db.upsert_session(_agent_session(session_id))
        await async_db.create_run(
            run=run_for_scope(stored_scope, "r1", "original"),
            session_id=stored_scope["session_id"],
            user_id=stored_scope["user_id"],
        )

        outcome = await async_db.update_run(
            run=run_for_scope(incoming_scope, "r1", "written"),
            session_id=incoming_scope["session_id"],
            user_id=incoming_scope["user_id"],
        )

        assert (outcome is RunUpdateOutcome.UPDATED) is allowed
        assert await _astored_content(async_db, "r1") == ("written" if allowed else "original")
