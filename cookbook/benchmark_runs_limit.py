"""Benchmark: Memory and time savings from runs_limit optimization.

Measures DB query time and memory for loading sessions with different runs_limit values.
"""

import gc
import time
import tracemalloc
from uuid import uuid4

from agno.db.postgres.postgres import PostgresDb
from agno.session.agent import AgentSession


def benchmark_get_session(db: PostgresDb, session_id: str, runs_limit: int | None) -> dict:
    """Benchmark a single get_session call."""
    gc.collect()
    tracemalloc.start()

    start_time = time.perf_counter()
    session = db.get_session(session_id, runs_limit=runs_limit)
    end_time = time.perf_counter()

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    num_runs = len(session.runs) if session and session.runs else 0

    return {
        "runs_limit": runs_limit,
        "runs_loaded": num_runs,
        "time_ms": (end_time - start_time) * 1000,
        "memory_peak_kb": peak / 1024,
    }


def create_test_session(db: PostgresDb, num_runs: int) -> str:
    """Create a session with N runs."""
    session_id = f"bench-{uuid4()}"
    agent_id = "bench-agent"

    # Create session using proper API
    session = AgentSession(session_id=session_id, agent_id=agent_id)
    db.upsert_session(session)

    # Insert runs using save_run
    filler = "Lorem ipsum dolor sit amet consectetur. " * 30
    for i in range(num_runs):
        run_data = {
            "run_id": str(uuid4()),
            "session_id": session_id,
            "agent_id": agent_id,
            "status": "completed",
            "content": f"Run {i}: {filler}",
            "messages": [
                {"role": "user", "content": f"User message {i} with content"},
                {"role": "assistant", "content": f"Response {i}: {filler}"},
            ],
        }
        db.save_run(run_data, run_index=i)

    return session_id


def run_benchmark():
    """Run the benchmark."""
    print("Benchmark: runs_limit optimization\n")

    db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5432/ai")

    test_sizes = [50, 200, 500]
    runs_limits = [None, 3, 10, 50]

    results = []

    for num_runs in test_sizes:
        print(f"Creating session with {num_runs} runs...")
        session_id = create_test_session(db, num_runs)

        for limit in runs_limits:
            r = benchmark_get_session(db, session_id, limit)
            r["total_runs"] = num_runs
            results.append(r)
            print(f"  limit={str(limit or 'None'):>4}: {r['runs_loaded']:>3} runs, {r['time_ms']:>6.1f}ms, {r['memory_peak_kb']:>6.0f}KB")

        db.delete_session(session_id)
        print()

    # Summary
    print("=" * 70)
    print("SAVINGS vs FULL LOAD")
    print("=" * 70)

    for num_runs in test_sizes:
        baseline = next(r for r in results if r['total_runs'] == num_runs and r['runs_limit'] is None)
        print(f"\nSession with {num_runs} runs (baseline: {baseline['time_ms']:.1f}ms, {baseline['memory_peak_kb']:.0f}KB):")

        for r in results:
            if r['total_runs'] == num_runs and r['runs_limit'] is not None:
                time_pct = (1 - r['time_ms'] / baseline['time_ms']) * 100 if baseline['time_ms'] > 0 else 0
                mem_pct = (1 - r['memory_peak_kb'] / baseline['memory_peak_kb']) * 100 if baseline['memory_peak_kb'] > 0 else 0
                print(f"  limit={r['runs_limit']:>3}: {time_pct:>5.1f}% faster, {mem_pct:>5.1f}% less memory")


if __name__ == "__main__":
    run_benchmark()
