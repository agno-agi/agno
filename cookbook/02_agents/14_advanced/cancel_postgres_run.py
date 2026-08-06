"""
Multi-Process Run Cancellation with PostgreSQL
===============================================

Demonstrates the PRIMARY use case for PostgresRunCancellationManager:
cancelling an agent run from a COMPLETELY SEPARATE PROCESS.

The in-memory manager cannot solve this — its state exists only inside a
single OS process. When you deploy multiple API workers (gunicorn, uvicorn),
a cancel request may land on Worker B while the agent is running on Worker A.
PostgreSQL acts as the shared cancellation bus between all workers.

Scenario in this demo:
  Process A (AgentWorker) — creates its own manager, runs the agent
  Process B (Canceller)   — creates its own manager, same DB, cancels after a delay

Both managers have completely separate in-process caches and engine pools.
The only shared state is the ``t_run_cancel`` table in PostgreSQL.

Two variants are shown:
  sync_main()  — sync agent.run()  + sync   manager methods
  async_main() — async agent.arun() + async manager methods (realistic for ASGI workers)

Prerequisites:
    uv pip install psycopg[binary] sqlalchemy

    Set DATABASE_URL (psycopg async dialect):
        export DATABASE_URL=postgresql+psycopg_async://ai:ai@host:port/db

Usage:
    DATABASE_URL=postgresql+psycopg_async://ai:ai@localhost:5532/ai \\
        .venv/bin/python cookbook/02_agents/14_advanced/cancel_postgres_run.py
"""

import asyncio
import multiprocessing
import os
import time

# ---------------------------------------------------------------------------
# Database URLs
# ---------------------------------------------------------------------------

ASYNC_DB_URL = os.environ["DATABASE_URL"]
# Derive a sync URL from the async one (replace driver dialect suffix)
SYNC_DB_URL = (
    ASYNC_DB_URL.replace("+psycopg_async", "+psycopg")
    .replace("+asyncpg", "")
    .replace("+aiopg", "")
)


# ---------------------------------------------------------------------------
# Helper: build a fresh manager (called independently in each process)
# ---------------------------------------------------------------------------


def _build_manager():
    """Create a PostgresRunCancellationManager with both async and sync engines.

    Each OS process must build its own engines — SQLAlchemy connection pools
    are not safe to share across fork boundaries.
    """
    from agno.run.cancellation_management.postgres_cancellation_manager import (
        PostgresRunCancellationManager,
    )
    from sqlalchemy import create_engine
    from sqlalchemy.ext.asyncio import create_async_engine

    async_engine = create_async_engine(ASYNC_DB_URL, echo=False)
    sync_engine = create_engine(SYNC_DB_URL, echo=False)
    return PostgresRunCancellationManager(
        async_engine=async_engine,
        sync_engine=sync_engine,
    )


# ---------------------------------------------------------------------------
# Process A: run the agent
# ---------------------------------------------------------------------------


def worker_process(run_id_queue: multiprocessing.Queue) -> None:
    """Agent worker — simulates one gunicorn/uvicorn worker handling a request."""
    from agno.agent import Agent
    from agno.models.openai import OpenAIResponses
    from agno.run.agent import RunEvent
    from agno.run.cancel import set_cancellation_manager

    print("[Worker A] Starting — building its own Postgres manager...")
    manager = _build_manager()
    set_cancellation_manager(manager)

    agent = Agent(
        name="StoryAgent",
        model=OpenAIResponses(id="gpt-5.4"),
        description="An agent that writes long, detailed stories.",
    )

    run_id_sent = False
    for chunk in agent.run(
        "Write a very long story about a sailor who discovers a mysterious island. "
        "Include vivid descriptions of the landscape, mysterious creatures, "
        "and the sailor's inner thoughts. Aim for at least 2000 words.",
        stream=True,
    ):
        # Share run_id with the canceller process as soon as we have it
        if not run_id_sent and chunk.run_id:
            run_id_queue.put(chunk.run_id)
            print(f"\n[Worker A] Run started: {chunk.run_id}")
            run_id_sent = True

        if chunk.event == RunEvent.run_content and chunk.content:
            print(chunk.content, end="", flush=True)
        elif chunk.event == RunEvent.run_cancelled:
            print(f"\n[Worker A] Received cancellation signal for run {chunk.run_id}.")
            print("[Worker A] Stopping cleanly.")
            return

    print("\n[Worker A] Run completed without cancellation.")


# ---------------------------------------------------------------------------
# Process B: cancel the run
# ---------------------------------------------------------------------------


def canceller_process(run_id_queue: multiprocessing.Queue, delay: int = 4) -> None:
    """Canceller — simulates a DIFFERENT worker/service receiving a cancel API call."""
    print(f"[Canceller B] Will cancel after {delay}s. Waiting for run_id...")

    # Wait until Worker A puts the run_id in the queue
    run_id = None
    deadline = time.time() + 60
    while run_id is None and time.time() < deadline:
        try:
            run_id = run_id_queue.get(timeout=1)
        except Exception:
            pass

    if run_id is None:
        print("[Canceller B] Timed out waiting for run_id. Exiting.")
        return

    # Wait for the configured delay before cancelling
    elapsed = 0
    while elapsed < delay:
        time.sleep(1)
        elapsed += 1
        print(f"[Canceller B] {elapsed}/{delay}s elapsed, run_id={run_id}...")

    print(f"\n[Canceller B] Sending cancel signal via PostgreSQL for run {run_id}...")

    # Build a completely SEPARATE manager — different process, different cache,
    # different engine pool. Only the database is shared.
    manager = _build_manager()
    was_registered = manager.cancel_run(run_id)

    if was_registered:
        print(
            "[Canceller B] Cancellation written to DB. Worker A will detect it shortly."
        )
    else:
        print(f"[Canceller B] Run {run_id} was not found (may have already completed).")

    # Confirm the flag is visible from this independent process
    active = manager.get_active_runs()
    print(f"[Canceller B] Active runs seen from this process: {active}")


# ---------------------------------------------------------------------------
# Sync main
# ---------------------------------------------------------------------------


def sync_main() -> None:
    print("Building Postgres manager in main process to create the table...")
    manager = _build_manager()
    manager.create_table()
    print("t_run_cancel table is ready.")

    print()
    print("=" * 60)
    print("Sync multi-process cancellation demo")
    print("  Process A: runs the agent    (sync agent.run)")
    print("  Process B: cancels after 4s  (sync manager.cancel_run)")
    print("=" * 60)
    print()

    run_id_queue: multiprocessing.Queue = multiprocessing.Queue()

    worker = multiprocessing.Process(
        target=worker_process,
        args=(run_id_queue,),
        name="AgentWorker",
    )
    canceller = multiprocessing.Process(
        target=canceller_process,
        args=(run_id_queue, 4),
        name="Canceller",
    )

    worker.start()
    canceller.start()
    worker.join()
    canceller.join()

    print()
    print("=" * 60)
    print("Both processes finished.")
    active = manager.get_active_runs()
    if active:
        print(f"Stale runs still in DB: {active}")
    else:
        print("No stale runs in DB — cleanup was successful.")


# ---------------------------------------------------------------------------
# Async worker / canceller — realistic for ASGI (uvicorn/FastAPI) deployments
# ---------------------------------------------------------------------------


async def _async_worker(run_id_queue: multiprocessing.Queue) -> None:
    from agno.agent import Agent
    from agno.models.openai import OpenAIResponses
    from agno.run.agent import RunEvent
    from agno.run.cancel import set_cancellation_manager

    print("[Worker A] Starting async — building its own Postgres manager...")
    manager = _build_manager()
    set_cancellation_manager(manager)

    agent = Agent(
        name="StoryAgent",
        model=OpenAIResponses(id="gpt-5.4"),
        description="An agent that writes long, detailed stories.",
    )

    run_id_sent = False
    async for chunk in agent.arun(
        "Write a very long story about a sailor who discovers a mysterious island. "
        "Include vivid descriptions of the landscape, mysterious creatures, "
        "and the sailor's inner thoughts. Aim for at least 2000 words.",
        stream=True,
    ):
        if not run_id_sent and chunk.run_id:
            run_id_queue.put(chunk.run_id)
            print(f"\n[Worker A] Run started: {chunk.run_id}")
            run_id_sent = True

        if chunk.event == RunEvent.run_content and chunk.content:
            print(chunk.content, end="", flush=True)
        elif chunk.event == RunEvent.run_cancelled:
            print(f"\n[Worker A] Run {chunk.run_id} was cancelled (async).")
            return

    print("\n[Worker A] Run completed without cancellation.")


async def _async_canceller(run_id_queue: multiprocessing.Queue, delay: int = 4) -> None:
    print(f"[Canceller B] Will cancel after {delay}s. Waiting for run_id...")

    run_id = None
    deadline = time.time() + 60
    while run_id is None and time.time() < deadline:
        try:
            run_id = run_id_queue.get_nowait()
        except Exception:
            await asyncio.sleep(1)

    if run_id is None:
        print("[Canceller B] Timed out waiting for run_id. Exiting.")
        return

    for i in range(1, delay + 1):
        await asyncio.sleep(1)
        print(f"[Canceller B] {i}/{delay}s elapsed, run_id={run_id}...")

    print(f"\n[Canceller B] Sending async cancel signal for run {run_id}...")

    manager = _build_manager()
    was_registered = await manager.acancel_run(run_id)

    if was_registered:
        print("[Canceller B] Cancellation written to DB via acancel_run.")
    else:
        print(f"[Canceller B] Run {run_id} not found (may have completed).")

    active = await manager.aget_active_runs()
    print(f"[Canceller B] Active runs seen from this process: {active}")


def _async_worker_process(run_id_queue: multiprocessing.Queue) -> None:
    """Entry point for the worker subprocess (async version)."""
    asyncio.run(_async_worker(run_id_queue))


def _async_canceller_process(run_id_queue: multiprocessing.Queue, delay: int) -> None:
    """Entry point for the canceller subprocess (async version)."""
    asyncio.run(_async_canceller(run_id_queue, delay))


# ---------------------------------------------------------------------------
# Async main
# ---------------------------------------------------------------------------


def async_main() -> None:
    print("Building Postgres manager in main process to create the table...")
    manager = _build_manager()
    manager.create_table()
    print("t_run_cancel table is ready.")

    print()
    print("=" * 60)
    print("Async multi-process cancellation demo")
    print("  Process A: runs the agent    (async agent.arun)")
    print("  Process B: cancels after 4s  (async manager.acancel_run)")
    print("=" * 60)
    print()

    run_id_queue: multiprocessing.Queue = multiprocessing.Queue()

    worker = multiprocessing.Process(
        target=_async_worker_process,
        args=(run_id_queue,),
        name="AsyncAgentWorker",
    )
    canceller = multiprocessing.Process(
        target=_async_canceller_process,
        args=(run_id_queue, 4),
        name="AsyncCanceller",
    )

    worker.start()
    canceller.start()
    worker.join()
    canceller.join()

    print()
    print("=" * 60)
    print("Both async processes finished.")
    active = manager.get_active_runs()
    if active:
        print(f"Stale runs still in DB: {active}")
    else:
        print("No stale runs in DB — cleanup was successful.")


if __name__ == "__main__":
    # "spawn" avoids inheriting open DB connections from the parent process —
    # matches how gunicorn/uvicorn workers are launched.
    multiprocessing.set_start_method("spawn")

    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "sync"
    if mode == "async":
        async_main()
    else:
        sync_main()
