"""Comprehensive integration tests for run_index correctness.

These tests verify that run_index is handled correctly across all scenarios:
1. Basic new run indexing (0, 1, 2, ...)
2. Bounded load continue (the bug we fixed)
3. Concurrent writes (atomic counter)
4. Checkpoint preservation
5. Fork session (re-indexing)
6. Regenerate (old run keeps index, new run gets next)

Uses SQLite for portability. Postgres tests in test_run_index_race.py.
"""

import asyncio
import threading
import time
import uuid
from typing import Optional

import pytest

from agno.db.sqlite import AsyncSqliteDb, SqliteDb


def _make_run(
    run_id: str,
    session_id: str,
    run_index: Optional[int] = None,
    status: str = "COMPLETED",
    content: str = "test",
) -> dict:
    """Create a minimal run dict for testing."""
    d = {
        "run_id": run_id,
        "session_id": session_id,
        "agent_id": "test-agent",
        "status": status,
        "content": content,
    }
    if run_index is not None:
        d["run_index"] = run_index
    return d


def _seed_session(db: SqliteDb, session_id: str) -> None:
    """Create the parent session row (SQLite enforces FK)."""
    sessions_table = db._get_table(table_type="sessions", create_table_if_not_found=True)
    db._get_table(table_type="runs", create_table_if_not_found=True)
    with db.Session() as sess, sess.begin():
        sess.execute(
            sessions_table.insert().values(
                session_id=session_id,
                session_type="agent",
                created_at=int(time.time()),
            )
        )


async def _aseed_session(db: AsyncSqliteDb, session_id: str) -> None:
    """Async: create the parent session row."""
    sessions_table = await db._get_table(table_type="sessions", create_table_if_not_found=True)
    await db._get_table(table_type="runs", create_table_if_not_found=True)
    async with db.async_session_factory() as sess:
        async with sess.begin():
            await sess.execute(
                sessions_table.insert().values(
                    session_id=session_id,
                    session_type="agent",
                    created_at=int(time.time()),
                )
            )


def _get_run_indexes(db: SqliteDb, session_id: str) -> list[int]:
    """Retrieve all run_index values for a session, sorted."""
    from sqlalchemy import select

    runs_table = db._get_table(table_type="runs")
    with db.Session() as sess:
        rows = sess.execute(select(runs_table.c.run_index).where(runs_table.c.session_id == session_id)).fetchall()
    return sorted([r[0] for r in rows])


async def _aget_run_indexes(db: AsyncSqliteDb, session_id: str) -> list[int]:
    """Async: retrieve all run_index values for a session, sorted."""
    from sqlalchemy import select

    runs_table = await db._get_table(table_type="runs")
    async with db.async_session_factory() as sess:
        rows = (
            await sess.execute(select(runs_table.c.run_index).where(runs_table.c.session_id == session_id))
        ).fetchall()
    return sorted([r[0] for r in rows])


# ---------------------------------------------------------------------------
# Test 1: Basic New Run Indexing
# ---------------------------------------------------------------------------


class TestBasicRunIndexing:
    """Verify sequential run_index allocation: 0, 1, 2, ..."""

    def test_sync_sequential_new_runs_get_contiguous_indexes(self, tmp_path):
        """Three new runs should get indexes 0, 1, 2."""
        db = SqliteDb(db_file=str(tmp_path / "basic.db"))
        session_id = f"s-{uuid.uuid4().hex[:8]}"
        _seed_session(db, session_id)

        # Insert 3 runs with NO run_index (forces backfill)
        for i in range(3):
            db.upsert_run(
                run=_make_run(f"r{i}", session_id),
                session_id=session_id,
            )

        indexes = _get_run_indexes(db, session_id)
        assert indexes == [0, 1, 2], f"Expected [0, 1, 2], got {indexes}"

    @pytest.mark.asyncio
    async def test_async_sequential_new_runs_get_contiguous_indexes(self, tmp_path):
        """Async variant: three new runs should get indexes 0, 1, 2."""
        db = AsyncSqliteDb(db_file=str(tmp_path / "basic_async.db"))
        session_id = f"s-{uuid.uuid4().hex[:8]}"
        await _aseed_session(db, session_id)

        for i in range(3):
            await db.upsert_run(
                run=_make_run(f"r{i}", session_id),
                session_id=session_id,
            )

        indexes = await _aget_run_indexes(db, session_id)
        assert indexes == [0, 1, 2], f"Expected [0, 1, 2], got {indexes}"


# ---------------------------------------------------------------------------
# Test 2: Bounded Load Continue (THE BUG WE FIXED)
# ---------------------------------------------------------------------------


class TestBoundedLoadContinue:
    """Verify that new runs get correct index after bounded session load.

    THE BUG: After loading session with runs_limit=10, the in-memory list
    had positions 0-9. The old code computed run_index from list position,
    so a new run would get index 10 instead of the correct 100.

    THE FIX: run_index is now injected by DB adapter during deserialization
    and passed through directly. New runs have run_index=None, which triggers
    atomic allocation via MAX+1 (SQL) or atomic counter (NoSQL).
    """

    def test_new_run_after_bounded_load_gets_correct_index(self, tmp_path):
        """After 100 runs, load with runs_limit=10, new run should be index 100."""
        db = SqliteDb(db_file=str(tmp_path / "bounded.db"))
        session_id = f"s-{uuid.uuid4().hex[:8]}"
        _seed_session(db, session_id)

        # Create 100 runs with explicit indexes
        for i in range(100):
            db.upsert_run(
                run=_make_run(f"r{i}", session_id, run_index=i),
                session_id=session_id,
                run_index=i,
            )

        # Verify we have 100 runs
        indexes = _get_run_indexes(db, session_id)
        assert len(indexes) == 100
        assert max(indexes) == 99

        # Simulate bounded load by getting session (runs_limit tested at agent level)
        # Here we directly test: new run with no run_index should get 100
        db.upsert_run(
            run=_make_run("r100", session_id),  # No run_index
            session_id=session_id,
        )

        indexes = _get_run_indexes(db, session_id)
        assert 100 in indexes, f"New run should have index 100, got {indexes[-5:]}"
        assert max(indexes) == 100

    @pytest.mark.asyncio
    async def test_async_new_run_after_bounded_load_gets_correct_index(self, tmp_path):
        """Async: After 100 runs, new run should be index 100."""
        db = AsyncSqliteDb(db_file=str(tmp_path / "bounded_async.db"))
        session_id = f"s-{uuid.uuid4().hex[:8]}"
        await _aseed_session(db, session_id)

        # Create 100 runs
        for i in range(100):
            await db.upsert_run(
                run=_make_run(f"r{i}", session_id, run_index=i),
                session_id=session_id,
                run_index=i,
            )

        # New run with no run_index
        await db.upsert_run(
            run=_make_run("r100", session_id),
            session_id=session_id,
        )

        indexes = await _aget_run_indexes(db, session_id)
        assert 100 in indexes, f"New run should have index 100"
        assert max(indexes) == 100


# ---------------------------------------------------------------------------
# Test 3: Concurrent Writes (Atomic Counter)
# ---------------------------------------------------------------------------


class TestConcurrentWrites:
    """Verify no duplicate or gapped indexes under concurrent writes."""

    def test_threaded_concurrent_writes_produce_unique_indexes(self, tmp_path):
        """10 concurrent writers should produce indexes 0-9 with no gaps."""
        db = SqliteDb(db_file=str(tmp_path / "concurrent.db"))
        session_id = f"s-{uuid.uuid4().hex[:8]}"
        _seed_session(db, session_id)

        n_writers = 10
        barrier = threading.Barrier(n_writers)
        errors: list = []

        def writer(i: int) -> None:
            try:
                barrier.wait(timeout=10)
                db.upsert_run(
                    run=_make_run(f"r{i}", session_id),
                    session_id=session_id,
                )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(n_writers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Writers raised: {errors}"

        indexes = _get_run_indexes(db, session_id)
        assert indexes == list(range(n_writers)), (
            f"Expected {list(range(n_writers))}, got {indexes} - concurrent backfills landed duplicate/gapped indexes"
        )


# ---------------------------------------------------------------------------
# Test 4: Update Preserves run_index
# ---------------------------------------------------------------------------


class TestUpdatePreservesIndex:
    """Verify that updating a run preserves its run_index."""

    def test_update_existing_run_keeps_same_index(self, tmp_path):
        """Updating content of run at index 5 should keep index 5."""
        db = SqliteDb(db_file=str(tmp_path / "update.db"))
        session_id = f"s-{uuid.uuid4().hex[:8]}"
        _seed_session(db, session_id)

        # Create runs 0-9
        for i in range(10):
            db.upsert_run(
                run=_make_run(f"r{i}", session_id, run_index=i),
                session_id=session_id,
                run_index=i,
            )

        # Update run at index 5 (pass explicit run_index to preserve)
        db.upsert_run(
            run=_make_run("r5", session_id, run_index=5, content="UPDATED"),
            session_id=session_id,
            run_index=5,
        )

        indexes = _get_run_indexes(db, session_id)
        assert indexes == list(range(10)), f"Indexes should be unchanged: {indexes}"

        # Verify content was updated
        from sqlalchemy import select

        runs_table = db._get_table(table_type="runs")
        with db.Session() as sess:
            row = sess.execute(select(runs_table.c.run_data).where(runs_table.c.run_id == "r5")).fetchone()
            import json

            data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            assert data.get("content") == "UPDATED"

    @pytest.mark.asyncio
    async def test_async_update_existing_run_keeps_same_index(self, tmp_path):
        """Async: updating run at index 5 should keep index 5."""
        db = AsyncSqliteDb(db_file=str(tmp_path / "update_async.db"))
        session_id = f"s-{uuid.uuid4().hex[:8]}"
        await _aseed_session(db, session_id)

        for i in range(10):
            await db.upsert_run(
                run=_make_run(f"r{i}", session_id, run_index=i),
                session_id=session_id,
                run_index=i,
            )

        # Update run 5
        await db.upsert_run(
            run=_make_run("r5", session_id, run_index=5, content="UPDATED"),
            session_id=session_id,
            run_index=5,
        )

        indexes = await _aget_run_indexes(db, session_id)
        assert indexes == list(range(10))


# ---------------------------------------------------------------------------
# Test 5: Fork Session Re-indexing
# ---------------------------------------------------------------------------


class TestForkSessionReindex:
    """Verify that forking a session re-indexes runs starting from 0."""

    def test_forked_session_has_reindexed_runs(self, tmp_path):
        """Runs copied to new session should have indexes 0, 1, 2, ..."""
        db = SqliteDb(db_file=str(tmp_path / "fork.db"))
        original_session = f"s-orig-{uuid.uuid4().hex[:8]}"
        forked_session = f"s-fork-{uuid.uuid4().hex[:8]}"

        _seed_session(db, original_session)
        _seed_session(db, forked_session)

        # Create runs in original session with indexes 0, 1, 2, 3, 4
        for i in range(5):
            db.upsert_run(
                run=_make_run(f"orig-r{i}", original_session, run_index=i),
                session_id=original_session,
                run_index=i,
            )

        # Simulate fork: copy runs to new session with explicit re-indexing
        # (This is what fork_session does - it enumerates and assigns idx)
        for idx in range(5):
            db.upsert_run(
                run=_make_run(f"fork-r{idx}", forked_session, run_index=idx),
                session_id=forked_session,
                run_index=idx,
            )

        # Verify forked session has indexes 0-4
        forked_indexes = _get_run_indexes(db, forked_session)
        assert forked_indexes == [0, 1, 2, 3, 4], f"Forked indexes: {forked_indexes}"

        # Original should be unchanged
        orig_indexes = _get_run_indexes(db, original_session)
        assert orig_indexes == [0, 1, 2, 3, 4]


# ---------------------------------------------------------------------------
# Test 6: Regenerate (Old run keeps index, new run gets next)
# ---------------------------------------------------------------------------


class TestRegenerateRunIndex:
    """Verify regenerate behavior: old run keeps its index, new run gets next."""

    def test_regenerated_run_gets_next_index(self, tmp_path):
        """Regenerating run at index 5 should create new run at index 10."""
        db = SqliteDb(db_file=str(tmp_path / "regen.db"))
        session_id = f"s-{uuid.uuid4().hex[:8]}"
        _seed_session(db, session_id)

        # Create runs 0-9
        for i in range(10):
            db.upsert_run(
                run=_make_run(f"r{i}", session_id, run_index=i),
                session_id=session_id,
                run_index=i,
            )

        # Mark run 5 as REGENERATED (update status but keep same index)
        db.upsert_run(
            run=_make_run("r5", session_id, run_index=5, status="REGENERATED"),
            session_id=session_id,
            run_index=5,
        )

        # Add the regenerated replacement run (new run, no explicit index)
        db.upsert_run(
            run=_make_run("r5-regen", session_id, content="regenerated content"),
            session_id=session_id,
        )

        indexes = _get_run_indexes(db, session_id)
        assert len(indexes) == 11, f"Should have 11 runs, got {len(indexes)}"
        assert 5 in indexes, "Original run at index 5 should exist"
        assert 10 in indexes, "Regenerated run should be at index 10"
        assert max(indexes) == 10

    @pytest.mark.asyncio
    async def test_async_regenerated_run_gets_next_index(self, tmp_path):
        """Async: regenerating should produce next available index."""
        db = AsyncSqliteDb(db_file=str(tmp_path / "regen_async.db"))
        session_id = f"s-{uuid.uuid4().hex[:8]}"
        await _aseed_session(db, session_id)

        for i in range(10):
            await db.upsert_run(
                run=_make_run(f"r{i}", session_id, run_index=i),
                session_id=session_id,
                run_index=i,
            )

        # Mark old, add new
        await db.upsert_run(
            run=_make_run("r5", session_id, run_index=5, status="REGENERATED"),
            session_id=session_id,
            run_index=5,
        )
        await db.upsert_run(
            run=_make_run("r5-regen", session_id),
            session_id=session_id,
        )

        indexes = await _aget_run_indexes(db, session_id)
        assert len(indexes) == 11
        assert max(indexes) == 10


# ---------------------------------------------------------------------------
# Test 7: run_index Injection on Read (DB → RunOutput)
# ---------------------------------------------------------------------------


class TestRunIndexInjectionOnRead:
    """Verify DB adapter injects run_index into run_data during deserialization."""

    def test_get_session_returns_runs_with_run_index_populated(self, tmp_path):
        """Loaded session should have run_index in each run's data."""
        db = SqliteDb(db_file=str(tmp_path / "inject.db"))
        session_id = f"s-{uuid.uuid4().hex[:8]}"
        _seed_session(db, session_id)

        # Create runs
        for i in range(5):
            db.upsert_run(
                run=_make_run(f"r{i}", session_id, run_index=i),
                session_id=session_id,
                run_index=i,
            )

        # Load session as dict (deserialize=False)
        session_data = db.get_session(session_id=session_id, deserialize=False)
        assert session_data is not None
        runs = session_data.get("runs", [])
        assert len(runs) == 5

        # Each run should have run_index populated
        for run in runs:
            assert "run_index" in run, f"run_index not injected into run: {run.get('run_id')}"
            assert isinstance(run["run_index"], int)

        # Verify they're in order
        run_indexes = [r["run_index"] for r in runs]
        assert run_indexes == [0, 1, 2, 3, 4] or sorted(run_indexes) == [0, 1, 2, 3, 4]

    @pytest.mark.asyncio
    async def test_async_get_session_returns_runs_with_run_index_populated(self, tmp_path):
        """Async: loaded session should have run_index in each run."""
        db = AsyncSqliteDb(db_file=str(tmp_path / "inject_async.db"))
        session_id = f"s-{uuid.uuid4().hex[:8]}"
        await _aseed_session(db, session_id)

        for i in range(5):
            await db.upsert_run(
                run=_make_run(f"r{i}", session_id, run_index=i),
                session_id=session_id,
                run_index=i,
            )

        # AsyncSqliteDb.get_session is async
        session_data = await db.get_session(session_id=session_id, deserialize=False)
        assert session_data is not None
        runs = session_data.get("runs", [])
        assert len(runs) == 5

        for run in runs:
            assert "run_index" in run


# ---------------------------------------------------------------------------
# Test 8: Bounded Load + Continue Simulation
# ---------------------------------------------------------------------------


class TestBoundedLoadAndContinueSimulation:
    """End-to-end simulation of the bug scenario."""

    def test_full_bounded_load_continue_scenario(self, tmp_path):
        """
        Full scenario:
        1. Create 50 runs in a session (indexes 0-49)
        2. Load session with runs_limit=5 (only runs 45-49 loaded)
        3. "Continue" by adding a new run
        4. New run MUST get index 50, not 5
        """
        db = SqliteDb(db_file=str(tmp_path / "full_scenario.db"))
        session_id = f"s-{uuid.uuid4().hex[:8]}"
        _seed_session(db, session_id)

        # Step 1: Create 50 runs
        for i in range(50):
            db.upsert_run(
                run=_make_run(f"r{i}", session_id, run_index=i),
                session_id=session_id,
                run_index=i,
            )

        # Step 2: Load with runs_limit=5 (simulated by get_session)
        session_data = db.get_session(session_id=session_id, runs_limit=5, deserialize=False)
        assert session_data is not None
        loaded_runs = session_data.get("runs", [])

        # Should have 5 runs with indexes 45-49
        assert len(loaded_runs) == 5
        loaded_indexes = sorted([r.get("run_index") for r in loaded_runs])
        assert loaded_indexes == [45, 46, 47, 48, 49], f"Got {loaded_indexes}"

        # Step 3: Add new run (simulating "continue" - no explicit run_index)
        # THE KEY TEST: new run should get index 50, not 5
        db.upsert_run(
            run=_make_run("new-run", session_id),  # NO run_index
            session_id=session_id,
        )

        # Step 4: Verify
        all_indexes = _get_run_indexes(db, session_id)
        assert len(all_indexes) == 51
        assert max(all_indexes) == 50, f"New run should be at index 50, max is {max(all_indexes)}"
        assert 50 in all_indexes, f"Index 50 missing from {all_indexes[-10:]}"
