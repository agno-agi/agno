"""
Continue a finished ClaudeAgent run
===================================
A completed run can be continued with a new instruction. The continuation
is a new run in the same session that carries the full Claude conversation,
so the model remembers everything from the source run.

Like native Agno agents, a finished run is never rewritten in place: the
continuation always gets its own run_id and records where it came from in
forked_from_run_id, whatever the fork argument is set to.

Requirements:
    pip install claude-agent-sdk
    A database with transcript storage (SQLite or PostgreSQL).

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/continue_from/01_continue_finished_run.py
"""

import asyncio
import tempfile
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.run.base import RunStatus

SESSION_ID = "continue-finished-run"


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

        # 1. A normal run.
        source = await agent.arun(
            "Reply with exactly the word ALPHA and nothing else.",
            session_id=SESSION_ID,
        )
        assert source.status == RunStatus.completed, source.content
        print(f"Source run {source.run_id[:8]}: {source.content}")

        # 2. Continue it. continue_from defaults to "end": the new instruction is
        #    appended after the last message of the source run.
        continued = await agent.acontinue_run(
            run_id=source.run_id,
            session_id=SESSION_ID,
            input="Which word did you reply with before? Answer with just that word.",
        )
        assert continued.status == RunStatus.completed, continued.content
        print(f"Continued run {continued.run_id[:8]}: {continued.content}")

        # The continuation is a new run with lineage back to the source.
        assert continued.run_id != source.run_id
        assert continued.forked_from_run_id == source.run_id
        assert continued.forked_from_message_index == len(source.messages or [])

        # The source run is untouched and the session now holds both runs.
        stored = await agent.aget_run_output(source.run_id, SESSION_ID)
        assert stored is not None and stored.content == source.content
        session = await agent.aget_session(SESSION_ID)
        print(f"Runs in session: {len(session.runs or [])}")
        for run in session.runs or []:
            lineage = (run.forked_from_run_id or "")[:8] or "-"
            print(f"  {run.run_id[:8]} forked_from={lineage} content={run.content!r}")


if __name__ == "__main__":
    asyncio.run(main())
