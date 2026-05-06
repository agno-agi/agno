"""
Test script to reproduce the UniqueViolation race condition in upsert_trace.

This script demonstrates the race condition that occurs when multiple concurrent
calls to upsert_trace() attempt to insert the same trace_id.

The race condition window:
1. Task A: SELECT - finds no existing trace
2. Task B: SELECT - finds no existing trace (before A's INSERT commits)
3. Task A: INSERT - succeeds
4. Task B: INSERT - FAILS with UniqueViolation
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

import pytest
from sqlalchemy import select

from agno.db.postgres import AsyncPostgresDb
from agno.tracing.schemas import Trace


def create_test_trace(trace_id: str, name: str, task_id: int) -> Trace:
    """Create a test Trace object."""
    now = datetime.now(timezone.utc)
    return Trace(
        trace_id=trace_id,
        name=name,
        status="OK",
        start_time=now,
        end_time=now,
        duration_ms=100,
        total_spans=1,
        error_count=0,
        run_id=None,
        session_id=None,
        user_id=None,
        agent_id=f"agent-{task_id}",
        team_id=None,
        workflow_id=None,
        created_at=now,
    )


async def concurrent_create_trace(
    db: AsyncPostgresDb,
    trace: Trace,
    task_id: int,
    barrier: asyncio.Barrier,
) -> dict:
    """Run a single concurrent task that tries to create a trace using AsyncPostgresDb."""
    result = {"task_id": task_id, "success": False, "error": None}

    try:
        # Wait for all tasks to be ready
        print(f"  Task {task_id:2d}: Waiting at barrier...")
        await barrier.wait()

        # All tasks release simultaneously - RACE CONDITION WINDOW
        print(f"  Task {task_id:2d}: Calling db.upsert_trace()...")
        await db.upsert_trace(trace)

        result["success"] = True
        print(f"  Task {task_id:2d}: SUCCESS")

    except Exception as e:
        error_str = str(e)
        result["error"] = error_str

        # Check for the specific UniqueViolation error
        if "UniqueViolation" in error_str or "duplicate key" in error_str.lower():
            print(f"  Task {task_id:2d}: FAILED - UniqueViolation!")
            # Print the full error like the user's original error
            print(f"\n{'!' * 60}")
            print("FULL ERROR (same as user's original error):")
            print(f"{'!' * 60}")
            print(f"ERROR Error creating trace: {e}")
            print(f"{'!' * 60}\n")
        else:
            print(f"  Task {task_id:2d}: FAILED - {type(e).__name__}: {error_str[:100]}")

    return result


async def cleanup_trace(db: AsyncPostgresDb, trace_id: str):
    """Delete a specific trace from the table."""
    try:
        table = await db._get_table(table_type="traces", create_table_if_not_found=True)
        if table is not None:
            async with db.async_session_factory() as sess, sess.begin():
                from sqlalchemy import delete

                await sess.execute(delete(table).where(table.c.trace_id == trace_id))
    except Exception as e:
        print(f"Cleanup error (can be ignored): {e}")


def _make_trace(
    trace_id: str,
    *,
    session_id: Optional[str],
    user_id: Optional[str] = None,
    agent_id: Optional[str],
    team_id: Optional[str],
    workflow_id: Optional[str] = None,
    run_id: Optional[str] = None,
    name: str = "Test.run",
) -> Trace:
    """Build a Trace with explicit context for upsert tests."""
    now = datetime.now(timezone.utc)
    return Trace(
        trace_id=trace_id,
        name=name,
        status="OK",
        start_time=now,
        end_time=now,
        duration_ms=100,
        total_spans=1,
        error_count=0,
        run_id=run_id,
        session_id=session_id,
        user_id=user_id,
        agent_id=agent_id,
        team_id=team_id,
        workflow_id=workflow_id,
        created_at=now,
    )


@pytest.mark.asyncio
async def test_upsert_trace_preserves_existing_context(async_postgres_db_real):
    """A second upsert with a different session_id must NOT overwrite the existing one.

    Reproduces the bug where ON CONFLICT DO UPDATE used
    ``COALESCE(excluded.session_id, table.c.session_id)`` (incoming wins),
    silently rewriting an existing trace row's context whenever a second span
    export shared the same trace_id under a different session.
    """
    db = async_postgres_db_real
    trace_id = f"coalesce-test-{uuid.uuid4().hex[:8]}"

    first = _make_trace(
        trace_id,
        session_id="team_session",
        user_id="user_1",
        agent_id=None,
        team_id="team_x",
    )
    await db.upsert_trace(first)

    # Second export shares the trace_id but carries a different session_id
    # and a different agent_id (the original row had agent_id=None).
    second = _make_trace(
        trace_id,
        session_id="rating_session",
        user_id=None,
        agent_id="agent_rating",
        team_id=None,
    )
    await db.upsert_trace(second)

    table = await db._get_table(table_type="traces")
    assert table is not None
    async with db.async_session_factory() as sess:
        row = (await sess.execute(select(table).where(table.c.trace_id == trace_id))).fetchone()

    assert row is not None
    # Existing non-null context fields are preserved (incoming did NOT win).
    assert row.session_id == "team_session"
    assert row.team_id == "team_x"
    assert row.user_id == "user_1"
    # Field that was NULL on the first write gets filled by the incoming value.
    assert row.agent_id == "agent_rating"


async def run_race_test(db: AsyncPostgresDb, num_tasks: int = 10):
    """Run a single race condition test using AsyncPostgresDb.upsert_trace()."""
    # Use a unique trace_id for this test run
    trace_id = f"race-test-{uuid.uuid4().hex[:8]}"

    print(f"\n{'=' * 60}")
    print("RACE CONDITION TEST")
    print(f"{'=' * 60}")
    print(f"Trace ID: {trace_id}")
    print(f"Concurrent tasks: {num_tasks}")
    print(f"{'=' * 60}\n")

    # Create barrier for synchronization
    barrier = asyncio.Barrier(num_tasks)

    # Create traces - all with the same trace_id
    traces = [create_test_trace(trace_id, f"Agent.run-task-{i}", i) for i in range(num_tasks)]

    # Launch all tasks concurrently
    tasks = [asyncio.create_task(concurrent_create_trace(db, traces[i], i, barrier)) for i in range(num_tasks)]

    # Wait for all tasks
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Analyze results
    print(f"\n{'=' * 60}")
    print("RESULTS")
    print(f"{'=' * 60}")

    successes = sum(1 for r in results if not isinstance(r, Exception) and r["success"])
    failures = sum(1 for r in results if isinstance(r, Exception) or not r["success"])

    print(f"\nSuccesses: {successes}")
    print(f"Failures: {failures}")

    # Cleanup - commented out to see entries in database
    # await cleanup_trace(db, trace_id)


async def main():
    # Database configuration - same as cookbook example
    db_url = "postgresql+psycopg_async://ai:ai@localhost:5532/ai"

    print(f"Database URL: {db_url.split('@')[1] if '@' in db_url else db_url}")

    # Create AsyncPostgresDb instance (same pattern as cookbook)
    db = AsyncPostgresDb(
        db_url=db_url,
        db_schema="ai",
        traces_table="agno_traces_race_test",
    )

    try:
        # Pre-create/cache the table to avoid table creation race conditions
        # This ensures the table exists before concurrent tests start
        print("Initializing table...")
        await db._get_table(table_type="traces", create_table_if_not_found=True)
        print("Table ready.")

        # Run multiple attempts
        attempts = 5
        tasks_per_attempt = 15

        print(f"\n{'#' * 60}")
        print(f"RUNNING {attempts} ATTEMPTS WITH {tasks_per_attempt} CONCURRENT TASKS EACH")
        print(f"{'#' * 60}")

        for attempt in range(attempts):
            print(f"\n--- Attempt {attempt + 1}/{attempts} ---")
            await run_race_test(db, tasks_per_attempt)

        # Final summary
        print(f"\n{'#' * 60}")
        print("FINAL SUMMARY")
        print(f"{'#' * 60}")
        print(f"Total attempts: {attempts}")
        print(f"Tasks per attempt: {tasks_per_attempt}")
        print("\nNote: Check ERROR logs above for UniqueViolation errors.")
        print("If you see ERROR logs, the race condition exists and needs the upsert fix.")

    finally:
        # Cleanup: dispose of the engine
        if db.db_engine:
            await db.db_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
