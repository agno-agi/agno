"""Crash recovery for a Team with checkpoint="tool-batch".

Team parity with ../../02_agents/18_checkpointing/01_crash_recovery.py.

A team persists its own run only at terminal states unless ``checkpoint`` is
raised. With ``checkpoint="tool-batch"`` the team writes after each team-level
tool batch (a delegation to a member IS a tool batch) with status RUNNING, so a
worker that dies mid-run leaves the last RUNNING checkpoint behind and
``/continue`` resumes it in place.

Why a subprocess + SIGKILL and not ``asyncio.Task.cancel()``: a cancel is
handled gracefully — the run is marked CANCELLED and re-persisted, and a
cancelled run is intentionally NOT continuable. A real crash runs no cleanup, so
the last RUNNING checkpoint is what survives. SIGKILL of a child reproduces that.

Flow:
1. A worker subprocess starts a team run that delegates to a member (shared DB).
2. The parent polls the DB until the first RUNNING checkpoint lands.
3. The parent SIGKILLs the worker — a true crash, no cleanup.
4. ``/continue`` resumes the RUNNING team run and finishes the work.
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
from agno.team import Team

DB_FILE = os.environ.get("CRASH_DB") or f"tmp/team_crash_recovery_{int(time.time())}.db"
SESSION_ID = "team-crash-demo-session"


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


async def _worker() -> None:
    """Runs inside the subprocess. Executes the team run until SIGKILL'd mid-flight."""
    team = build_team()
    await team.arun(
        input="Research the topic 'agno checkpointing'.", session_id=SESSION_ID
    )


async def main() -> None:
    # -------------------------------------------------------------------
    # 1. Launch a worker subprocess sharing this DB file.
    # -------------------------------------------------------------------
    print("=" * 70)
    print("STEP 1: Start the team run in a worker subprocess, then SIGKILL it")
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
    # -------------------------------------------------------------------
    reader = build_team()
    crashed_run = None
    for _ in range(80):  # up to ~40s
        time.sleep(0.5)
        if worker.poll() is not None:
            break
        session = reader.db.get_session(session_id=SESSION_ID, session_type="team")
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
    # 4. Inspect the DB — the partial team run survived the crash.
    # -------------------------------------------------------------------
    print("=" * 70)
    print("STEP 2: Inspect the DB. The partial team run survived the crash.")
    print("=" * 70)
    session = reader.db.get_session(session_id=SESSION_ID, session_type="team")
    crashed_run = session.runs[-1]
    print(f"  run_id:                          {crashed_run.run_id}")
    print(f"  status:                          {crashed_run.status}")
    print(f"  tool batches in DB:              {len(crashed_run.tools or [])}")
    print(f"  message count:                   {len(crashed_run.messages or [])}")
    print(
        f"  last_checkpoint_at_message_idx:  {crashed_run.last_checkpoint_at_message_index}"
    )
    print()
    print("Status is RUNNING — the team loop never reached terminal cleanup.")
    print("For /continue, RUNNING and ERROR are equivalent: both resume.")
    print()

    # -------------------------------------------------------------------
    # 5. Resume the crashed team run via /continue (in place — same run_id).
    # -------------------------------------------------------------------
    print("=" * 70)
    print("STEP 3: /continue resumes the team run from the last checkpoint")
    print("=" * 70)
    recovery_team = build_team()
    resumed = await recovery_team.acontinue_run(
        run_id=crashed_run.run_id, session_id=SESSION_ID
    )
    print(f"  run_id:              {resumed.run_id}  (same as crashed run)")
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
