"""
Replay or rewrite a ClaudeAgent turn
====================================
Two ways to start over from a run without losing it:

- continue_from="last_user" with no input re-sends the original prompt. The
  model sees the same conversation as the first time and produces a fresh answer.
- continue_from=0 with input starts a branch before the prompt, so the same run
  lineage gets a rewritten prompt.

Both create sibling runs with forked_from_run_id set; the source run is kept.

Requirements:
    pip install claude-agent-sdk
    A database with transcript storage (SQLite or PostgreSQL).

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/continue_from/03_replay_user_turn.py
"""

import asyncio
import tempfile
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.run.base import RunStatus

SESSION_ID = "replay-user-turn"


async def main():
    with tempfile.TemporaryDirectory(prefix="agno-continue-") as workdir:
        agent = ClaudeAgent(
            id="continue-demo",
            model="claude-sonnet-4-6",
            db=SqliteDb(db_file=str(Path(workdir) / "runs.db")),
            cwd=workdir,
            allowed_tools=["Bash"],
            permission_mode="bypassPermissions",
            max_turns=4,
            max_budget_usd=0.5,
        )

        run = await agent.arun(
            "Run `date +%s%N` with Bash and reply with just the number it printed.",
            session_id=SESSION_ID,
        )
        assert run.status == RunStatus.completed, run.content
        print(f"Original answer: {run.content}")

        # 1. Replay the same prompt. No input is given, so the stored user message
        #    is re-sent. The tool runs again, so the number differs.
        replay = await agent.acontinue_run(
            run_id=run.run_id,
            session_id=SESSION_ID,
            continue_from="last_user",
            fork=True,
        )
        assert replay.status == RunStatus.completed, replay.content
        assert replay.forked_from_run_id == run.run_id
        print(f"Replayed answer: {replay.content}")

        # 2. Rewrite the prompt. continue_from=0 branches before the first message,
        #    so the new input replaces the original prompt in this branch.
        rewrite = await agent.acontinue_run(
            run_id=run.run_id,
            session_id=SESSION_ID,
            continue_from=0,
            fork=True,
            input="Run `echo rewritten` with Bash and reply with just what it printed.",
        )
        assert rewrite.status == RunStatus.completed, rewrite.content
        assert rewrite.forked_from_run_id == run.run_id
        assert rewrite.forked_from_message_index == 0
        print(f"Rewritten answer: {rewrite.content}")

        session = await agent.aget_session(SESSION_ID)
        print(f"Runs in session: {len(session.runs or [])}")


if __name__ == "__main__":
    asyncio.run(main())
