"""Crash Recovery with checkpoint="steps".

This example **actually crashes** an in-flight run, then demonstrates that
``/continue`` picks up from the last persisted checkpoint.

Without ``checkpoint="steps"`` the run only persists at terminal states
(COMPLETED, PAUSED, ERROR, CANCELLED). A worker that dies between tool batches
loses everything — the session row exists, but this ``run_id`` was never
recorded under it.

``checkpoint="steps"`` writes after each tool batch (post-gather barrier).
If the process crashes between the J-th and (J+1)-th tool batch, the DB row
contains everything through turn J. ``/continue`` resumes from there.

We simulate the crash with ``asyncio.Task.cancel()``: previous synchronous
checkpoint writes have already landed in the DB, but the task dies before the
terminal cleanup. That mirrors what happens when a worker is OOM-killed,
SIGTERM'd, or hits an unhandled exception — DB state through the most recent
checkpoint survives.

Flow:
1. Start a run that calls multiple tools (each tool sleeps briefly).
2. Cancel the task mid-flight (after the first checkpoint, before terminal).
3. Read the DB directly to prove a partial row exists with status=RUNNING.
4. Call ``/continue`` to finish the work.

To see the contrast, you can toggle ``checkpoint="steps"`` to ``"runs"`` and
watch step 3 print "no run persisted" — without per-step writes, the crashed
run is unrecoverable.
"""

import asyncio
import time

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

# Use a unique DB file per run so the example is idempotent.
DB_FILE = f"tmp/checkpoint_crash_recovery_{int(time.time())}.db"


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
        db=SqliteDb(
            session_table="checkpoint_demo",
            db_file=DB_FILE,
        ),
        checkpoint="steps",
        tools=[slow_search, slow_fetch_detail],
        instructions=(
            "Use slow_search to find results, then call slow_fetch_detail on EACH "
            "result one at a time. Summarize what you learned at the end."
        ),
    )


async def main() -> None:
    agent = build_agent()
    session_id = "crash-demo-session"

    # -------------------------------------------------------------------
    # 1. Start the run as a cancellable task and let it run for a few seconds.
    # -------------------------------------------------------------------
    print("=" * 70)
    print("STEP 1: Start the run, then cancel it mid-flight to simulate a crash")
    print("=" * 70)

    run_task = asyncio.create_task(
        agent.arun(
            input="Research the topic 'agno checkpointing'.",
            session_id=session_id,
        )
    )

    # Wait long enough for the first tool batch to complete AND its checkpoint
    # to land in the DB, but not long enough for the run to finish.
    # Empirically: model API call ~1.5-2s, slow_search ~1s, checkpoint write
    # is fast — so by t=5s the first checkpoint is reliably persisted, and the
    # second batch (the parallel fetches) hasn't started yet.
    await asyncio.sleep(5.0)

    print("\n>>> Cancelling the in-flight run task (simulates a worker crash)\n")
    run_task.cancel()

    try:
        await run_task
    except asyncio.CancelledError:
        pass

    # -------------------------------------------------------------------
    # 2. Read the DB directly to prove the checkpointed state is persisted.
    # -------------------------------------------------------------------
    print("=" * 70)
    print("STEP 2: Inspect the DB. Was the partial state persisted?")
    print("=" * 70)

    # Fresh agent instance — same DB. This is what a new worker process would do
    # after the original one died.
    recovery_agent = build_agent()
    session = recovery_agent.db.get_session(session_id=session_id, session_type="agent")

    if not session or not session.runs:
        print("No runs persisted. With checkpoint='runs' (the default), this is")
        print("what you'd see — the crash lost the work entirely.")
        return

    crashed_run = session.runs[-1]
    print(f"  run_id:                          {crashed_run.run_id}")
    print(f"  status:                          {crashed_run.status}")
    print(f"  tool batches in DB:              {len(crashed_run.tools or [])}")
    print(f"  message count:                   {len(crashed_run.messages or [])}")
    print(
        f"  last_checkpoint_at_message_idx:  {crashed_run.last_checkpoint_at_message_index}"
    )
    print()
    print("Note: status is RUNNING (the checkpoint marks active runs that way).")
    print("In a real deployment a startup sweep could relabel stale RUNNING rows;")
    print("for /continue purposes, RUNNING + ERROR are equivalent — both resume.")
    print()

    # -------------------------------------------------------------------
    # 3. Resume the crashed run via /continue.
    # -------------------------------------------------------------------
    print("=" * 70)
    print("STEP 3: /continue resumes from the last checkpoint")
    print("=" * 70)

    resumed = await recovery_agent.acontinue_run(
        run_id=crashed_run.run_id,
        session_id=session_id,
    )

    print(f"  run_id:                          {resumed.run_id}  (same as crashed run)")
    print(f"  status:                          {resumed.status}")
    print(f"  total tool batches:              {len(resumed.tools or [])}")
    print(f"  total messages:                  {len(resumed.messages or [])}")
    print()
    print("Final answer:")
    print(resumed.content)


if __name__ == "__main__":
    asyncio.run(main())
