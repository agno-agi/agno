"""Crash recovery for a Team with checkpoint="tool-batch".

Team parity with ../../02_agents/18_checkpointing/01_crash_recovery.py.

A team persists its own run only at terminal states unless ``checkpoint`` is
raised. With ``checkpoint="tool-batch"`` the team writes after each team-level
tool batch (a delegation to a member IS a tool batch), so if the worker dies
mid-run the DB has everything through the last completed batch and ``/continue``
resumes from there.

We simulate the crash with ``asyncio.Task.cancel()``: the synchronous checkpoint
write from the first delegation has already landed, but the task dies before the
terminal cleanup — mirroring an OOM-kill / SIGTERM / unhandled exception.

Flow:
1. Start a team run that delegates to a member doing slow work.
2. Cancel the task mid-flight (after the first checkpoint, before terminal).
3. Read the DB directly to prove a partial team run exists with status=RUNNING.
4. Call ``/continue`` to finish the work (in place — same run_id).
"""

import asyncio
import time

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

# Unique DB file per run so the example is idempotent.
DB_FILE = f"tmp/team_crash_recovery_{int(time.time())}.db"


async def slow_search(query: str) -> str:
    """Mock search that takes ~1 second — gives us a window to interrupt."""
    await asyncio.sleep(1.0)
    return f"Top 3 results for '{query}': result-a, result-b, result-c"


async def slow_fetch_detail(item: str) -> str:
    """Mock detail fetch — another ~1 second."""
    await asyncio.sleep(1.0)
    return f"Detail for {item}: lorem ipsum dolor sit amet"


def build_team() -> Team:
    researcher = Agent(
        name="researcher",
        role="Researches a topic using slow_search and slow_fetch_detail.",
        model=OpenAIResponses(id="gpt-5.4"),
        tools=[slow_search, slow_fetch_detail],
        db=SqliteDb(session_table="team_checkpoint_demo", db_file=DB_FILE),
        instructions=(
            "Use slow_search to find results, then call slow_fetch_detail on EACH "
            "result one at a time. Report what you learned."
        ),
    )
    return Team(
        name="research-team",
        model=OpenAIResponses(id="gpt-5.4"),
        members=[researcher],
        db=SqliteDb(session_table="team_checkpoint_demo", db_file=DB_FILE),
        checkpoint="tool-batch",
        instructions="Delegate the research to the researcher, then summarize.",
    )


async def main() -> None:
    team = build_team()
    session_id = "team-crash-demo-session"

    # -------------------------------------------------------------------
    # 1. Start the run as a cancellable task, let it run a few seconds.
    # -------------------------------------------------------------------
    print("=" * 70)
    print("STEP 1: Start the team run, then cancel it mid-flight (simulated crash)")
    print("=" * 70)

    run_task = asyncio.create_task(
        team.arun(
            input="Research the topic 'agno checkpointing'.",
            session_id=session_id,
        )
    )

    # Long enough for the first delegation + its checkpoint to land, not long
    # enough for the whole run to finish.
    await asyncio.sleep(6.0)

    print("\n>>> Cancelling the in-flight team run (simulates a worker crash)\n")
    run_task.cancel()
    try:
        await run_task
    except asyncio.CancelledError:
        pass

    # -------------------------------------------------------------------
    # 2. Read the DB directly to prove the checkpointed state is persisted.
    # -------------------------------------------------------------------
    print("=" * 70)
    print("STEP 2: Inspect the DB. Was the partial team run persisted?")
    print("=" * 70)

    recovery_team = build_team()
    session = recovery_team.db.get_session(session_id=session_id, session_type="team")

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
    print("Note: status is RUNNING — the team's model loop never completed.")
    print("For /continue purposes, RUNNING and ERROR are equivalent: both resume.")
    print()

    # -------------------------------------------------------------------
    # 3. Resume the crashed team run via /continue (in place — same run_id).
    # -------------------------------------------------------------------
    print("=" * 70)
    print("STEP 3: /continue resumes the team run from the last checkpoint")
    print("=" * 70)

    resumed = await recovery_team.acontinue_run(
        run_id=crashed_run.run_id,
        session_id=session_id,
    )
    print(f"  run_id:              {resumed.run_id}  (same as crashed run)")
    print(f"  status:              {resumed.status}")
    print(f"  total tool batches:  {len(resumed.tools or [])}")
    print(f"  total messages:      {len(resumed.messages or [])}")
    print()
    print("Final answer:")
    print(resumed.content)


if __name__ == "__main__":
    asyncio.run(main())
