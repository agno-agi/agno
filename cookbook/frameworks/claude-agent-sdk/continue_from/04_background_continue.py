"""
Continue a ClaudeAgent run in the background
============================================
A continuation can run in the background like any other run. acontinue_run
returns at once with a PENDING run output; the work finishes on its own and
the result is read back from the database.

A finished run is always continued as a new run, so the background job gets
a fresh run_id with forked_from_run_id pointing at the source.

Requirements:
    pip install claude-agent-sdk
    A database with transcript storage (SQLite or PostgreSQL).

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/continue_from/04_background_continue.py
"""

import asyncio
import tempfile
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.run.base import RunStatus

SESSION_ID = "background-continue"
TERMINAL = {RunStatus.completed, RunStatus.error, RunStatus.cancelled}


async def wait_for_run(agent: ClaudeAgent, run_id: str, timeout: float = 120.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        stored = await agent.aget_run_output(run_id, SESSION_ID)
        if stored is not None and stored.status in TERMINAL:
            return stored
        await asyncio.sleep(0.5)
    raise TimeoutError(f"run {run_id} did not finish in {timeout}s")


async def main():
    with tempfile.TemporaryDirectory(prefix="agno-continue-") as workdir:
        agent = ClaudeAgent(
            id="continue-demo",
            model="claude-sonnet-4-6",
            db=SqliteDb(db_file=str(Path(workdir) / "runs.db")),
            cwd=workdir,
            allowed_tools=[],
            max_turns=2,
            max_budget_usd=0.5,
        )

        source = await agent.arun(
            "Reply with exactly the word ALPHA and nothing else.",
            session_id=SESSION_ID,
        )
        assert source.status == RunStatus.completed, source.content
        print(f"Source run {source.run_id[:8]}: {source.content}")

        # Submit the continuation and return immediately.
        accepted = await agent.acontinue_run(
            run_id=source.run_id,
            session_id=SESSION_ID,
            input="Reply with the previous word followed by BETA, nothing else.",
            background=True,
        )
        print(f"Accepted run {accepted.run_id[:8]}: {accepted.status}")
        assert accepted.status == RunStatus.pending
        assert accepted.run_id != source.run_id

        # Poll the database for the result.
        finished = await wait_for_run(agent, accepted.run_id)
        print(
            f"Finished run {finished.run_id[:8]}: {finished.status} {finished.content!r}"
        )
        assert finished.status == RunStatus.completed, finished.content
        assert finished.forked_from_run_id == source.run_id


if __name__ == "__main__":
    asyncio.run(main())
