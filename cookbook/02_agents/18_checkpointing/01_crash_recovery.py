"""Crash recovery with checkpoint="tool-batch".

This example **actually crashes** an in-flight run (SIGKILL of a worker
subprocess), then shows that ``/continue`` picks up from the last persisted
checkpoint.

Without ``checkpoint="tool-batch"`` a run only persists at terminal states
(COMPLETED, PAUSED, ERROR, CANCELLED). A worker that dies between tool batches
loses everything — the session row exists, but this ``run_id`` was never
recorded under it.

``checkpoint="tool-batch"`` writes after each tool batch (post-gather barrier)
with status RUNNING. If the process is killed between batch J and J+1, the DB
row contains everything through batch J, still marked RUNNING. ``/continue``
resumes a RUNNING run in place (same ``run_id``).

Why a subprocess + SIGKILL and not ``asyncio.Task.cancel()``: a cancel is
handled gracefully — the run is marked CANCELLED and re-persisted, and a
cancelled run is intentionally NOT continuable. A real crash (OOM-kill,
SIGKILL, power loss) runs no cleanup, so the last RUNNING checkpoint is what
survives. SIGKILL of a child process reproduces exactly that.

Flow:
1. A worker subprocess starts a run that calls slow tools (shared DB file).
2. The parent polls the DB until the first RUNNING checkpoint lands.
3. The parent SIGKILLs the worker — a true crash, no cleanup.
4. ``/continue`` resumes the RUNNING run and finishes the work.
"""

import asyncio
import os
import subprocess
import sys
import time

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.run.base import RunStatus

# Shared across parent + worker via env so both hit the same DB file.
DB_FILE = (
    os.environ.get("CRASH_DB") or f"tmp/checkpoint_crash_recovery_{int(time.time())}.db"
)
SESSION_ID = "crash-demo-session"


async def slow_search(query: str) -> str:
    """Mock search that takes ~1 second — gives us a window to interrupt."""
    await asyncio.sleep(1.0)
    return f"Top 3 results for '{query}': result-a, result-b, result-c"


async def slow_fetch_detail(item: str) -> str:
    """Mock detail fetch — another ~1 second."""
    await asyncio.sleep(1.0)
    return f"Detail for {item}: lorem ipsum dolor sit amet"


def build_agent() -> Agent:
    return Agent(
        name="research-agent",
        model=OpenAIResponses(id="gpt-5.4"),
        db=SqliteDb(session_table="checkpoint_demo", db_file=DB_FILE),
        checkpoint="tool-batch",
        tools=[slow_search, slow_fetch_detail],
        instructions=(
            "Use slow_search to find results, then call slow_fetch_detail on EACH "
            "result one at a time. Summarize what you learned at the end."
        ),
    )


async def _worker() -> None:
    """Runs inside the subprocess. Executes the run until SIGKILL'd mid-flight."""
    agent = build_agent()
    await agent.arun(
        input="Research the topic 'agno checkpointing'.", session_id=SESSION_ID
    )


async def main() -> None:
    # -------------------------------------------------------------------
    # 1. Launch a worker subprocess that shares this DB file.
    # -------------------------------------------------------------------
    print("=" * 70)
    print("STEP 1: Start the run in a worker subprocess, then SIGKILL it mid-flight")
    print("=" * 70)

    env = {**os.environ, "CRASH_DB": DB_FILE}
    worker = subprocess.Popen(
        [sys.executable, __file__, "--worker"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # -------------------------------------------------------------------
    # 2. Poll the DB until the first checkpoint lands (RUNNING + >=1 tool batch).
    #    This is robust — we wait for the actual checkpoint, not a fixed sleep.
    # -------------------------------------------------------------------
    reader = build_agent()
    crashed_run = None
    for _ in range(80):  # up to ~40s
        time.sleep(0.5)
        if worker.poll() is not None:
            break  # worker exited on its own (model finished before we caught it)
        session = reader.db.get_session(session_id=SESSION_ID, session_type="agent")
        if session and session.runs:
            run = session.runs[-1]
            if run.status == RunStatus.running and run.tools:
                crashed_run = run
                break

    # -------------------------------------------------------------------
    # 3. SIGKILL the worker — a true crash, no graceful cleanup.
    # -------------------------------------------------------------------
    print("\n>>> SIGKILL the worker subprocess (simulates an OOM-kill / hard crash)\n")
    worker.kill()
    worker.wait()

    if crashed_run is None:
        print("Did not catch a RUNNING checkpoint before the worker finished.")
        print("Re-run (the model occasionally answers without enough tool batches).")
        return

    # -------------------------------------------------------------------
    # 4. Inspect the DB — the partial state survived the crash.
    # -------------------------------------------------------------------
    print("=" * 70)
    print("STEP 2: Inspect the DB. The partial state survived the crash.")
    print("=" * 70)
    session = reader.db.get_session(session_id=SESSION_ID, session_type="agent")
    crashed_run = session.runs[-1]
    print(f"  run_id:                          {crashed_run.run_id}")
    print(f"  status:                          {crashed_run.status}")
    print(f"  tool batches in DB:              {len(crashed_run.tools or [])}")
    print(f"  message count:                   {len(crashed_run.messages or [])}")
    print(
        f"  last_checkpoint_at_message_idx:  {crashed_run.last_checkpoint_at_message_index}"
    )
    print()
    print("Status is RUNNING — the loop never reached terminal cleanup. For")
    print("/continue, RUNNING and ERROR are equivalent: both resume in place.")
    print()

    # -------------------------------------------------------------------
    # 5. Resume the crashed run via /continue (in place — same run_id).
    # -------------------------------------------------------------------
    print("=" * 70)
    print("STEP 3: /continue resumes from the last checkpoint")
    print("=" * 70)
    recovery_agent = build_agent()
    resumed = await recovery_agent.acontinue_run(
        run_id=crashed_run.run_id, session_id=SESSION_ID
    )
    print(
        f"  run_id:              {resumed.run_id}  (same as crashed run — in-place resume)"
    )
    print(f"  status:              {resumed.status}")
    print(f"  total tool batches:  {len(resumed.tools or [])}")
    print(f"  total messages:      {len(resumed.messages or [])}")
    print()
    print("Final answer:")
    print(resumed.content)


if __name__ == "__main__":
    if "--worker" in sys.argv:
        asyncio.run(_worker())
    else:
        asyncio.run(main())
