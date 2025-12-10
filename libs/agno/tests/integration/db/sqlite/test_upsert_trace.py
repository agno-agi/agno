"""
Test script to reproduce the UniqueViolation race condition in upsert_trace (SYNC version).

This script demonstrates the race condition that occurs when multiple concurrent
calls to upsert_trace() attempt to insert the same trace_id using the synchronous
SqliteDb class.

The race condition window:
1. Thread A: SELECT - finds no existing trace
2. Thread B: SELECT - finds no existing trace (before A's INSERT commits)
3. Thread A: INSERT - succeeds
4. Thread B: INSERT - FAILS with IntegrityError (UNIQUE constraint failed)
"""

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Barrier

from agno.db.sqlite import SqliteDb
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


def concurrent_create_trace(
    db: SqliteDb,
    trace: Trace,
    task_id: int,
    barrier: Barrier,
) -> dict:
    """Run a single concurrent task that tries to create a trace using SqliteDb."""
    result = {"task_id": task_id, "success": False, "error": None}

    try:
        # Wait for all threads to be ready
        print(f"  Task {task_id:2d}: Waiting at barrier...")
        barrier.wait()

        # All threads release simultaneously - RACE CONDITION WINDOW
        print(f"  Task {task_id:2d}: Calling db.upsert_trace()...")
        db.upsert_trace(trace)

        result["success"] = True
        print(f"  Task {task_id:2d}: SUCCESS")

    except Exception as e:
        error_str = str(e)
        result["error"] = error_str

        # Check for the specific IntegrityError (SQLite's equivalent of UniqueViolation)
        if "UNIQUE constraint failed" in error_str or "IntegrityError" in error_str:
            print(f"  Task {task_id:2d}: FAILED - IntegrityError (UNIQUE constraint)!")
            # Print the full error
            print(f"\n{'!' * 60}")
            print("FULL ERROR:")
            print(f"{'!' * 60}")
            print(f"ERROR Error creating trace: {e}")
            print(f"{'!' * 60}\n")
        else:
            print(f"  Task {task_id:2d}: FAILED - {type(e).__name__}: {error_str[:100]}")

    return result


def cleanup_trace(db: SqliteDb, trace_id: str):
    """Delete a specific trace from the table."""
    try:
        table = db._get_table(table_type="traces", create_table_if_not_found=True)
        if table is not None:
            with db.session_factory() as sess, sess.begin():
                from sqlalchemy import delete

                sess.execute(delete(table).where(table.c.trace_id == trace_id))
    except Exception as e:
        print(f"Cleanup error (can be ignored): {e}")


def run_race_test(db: SqliteDb, num_tasks: int = 10):
    """Run a single race condition test using SqliteDb.upsert_trace()."""
    # Use a unique trace_id for this test run
    trace_id = f"race-test-{uuid.uuid4().hex[:8]}"

    print(f"\n{'=' * 60}")
    print("RACE CONDITION TEST (SYNC SQLITE)")
    print(f"{'=' * 60}")
    print(f"Trace ID: {trace_id}")
    print(f"Concurrent threads: {num_tasks}")
    print(f"{'=' * 60}\n")

    # Create barrier for synchronization
    barrier = Barrier(num_tasks)

    # Create traces - all with the same trace_id
    traces = [create_test_trace(trace_id, f"Agent.run-task-{i}", i) for i in range(num_tasks)]

    # Launch all tasks concurrently using ThreadPoolExecutor
    results = []
    with ThreadPoolExecutor(max_workers=num_tasks) as executor:
        futures = [executor.submit(concurrent_create_trace, db, traces[i], i, barrier) for i in range(num_tasks)]

        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                results.append({"task_id": -1, "success": False, "error": str(e)})

    # Analyze results
    print(f"\n{'=' * 60}")
    print("RESULTS")
    print(f"{'=' * 60}")

    successes = sum(1 for r in results if r["success"])
    failures = sum(1 for r in results if not r["success"])

    print(f"\nSuccesses: {successes}")
    print(f"Failures: {failures}")

    # Cleanup - commented out to see entries in database
    # cleanup_trace(db, trace_id)


def main():
    # Database configuration - SQLite file
    db_file = "tmp/race_test_sync.db"

    print(f"Database file: {db_file}")

    # Create SqliteDb instance
    db = SqliteDb(
        db_file=db_file,
        traces_table="agno_traces_race_test_sync",
    )

    try:
        # Pre-create/cache the table to avoid table creation race conditions
        # This ensures the table exists before concurrent tests start
        print("Initializing table...")
        db._get_table(table_type="traces", create_table_if_not_found=True)
        print("Table ready.")

        # Run multiple attempts
        attempts = 5
        tasks_per_attempt = 15

        print(f"\n{'#' * 60}")
        print(f"RUNNING {attempts} ATTEMPTS WITH {tasks_per_attempt} CONCURRENT THREADS EACH")
        print(f"{'#' * 60}")

        for attempt in range(attempts):
            print(f"\n--- Attempt {attempt + 1}/{attempts} ---")
            run_race_test(db, tasks_per_attempt)

        # Final summary
        print(f"\n{'#' * 60}")
        print("FINAL SUMMARY")
        print(f"{'#' * 60}")
        print(f"Total attempts: {attempts}")
        print(f"Tasks per attempt: {tasks_per_attempt}")
        print("\nNote: Check ERROR logs above for IntegrityError (UNIQUE constraint) errors.")
        print("If you see ERROR logs, the race condition exists and needs the upsert fix.")

    finally:
        # Cleanup: dispose of the engine
        if db.db_engine:
            db.db_engine.dispose()


if __name__ == "__main__":
    main()
