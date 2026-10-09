"""
Replay or rewrite a ClaudeAgent turn
====================================
Two ways to start over from a run without losing it:

- continue_from="last_user" with no input re-sends the original prompt. The
  model sees the same conversation as the first time and runs its tools again
  against the workspace as it is now.
- continue_from=0 with input starts a branch before the prompt, so the same
  run lineage gets a different prompt.

Scenario: the source run lists the markdown files in a folder. A second file
is added, then the turn is replayed: the replay's tool call sees both files.
The rewrite asks a different question about the same folder.

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


def tool_outputs(run) -> str:
    return "\n".join(str(m.content) for m in run.messages or [] if m.role == "tool")


async def main():
    with tempfile.TemporaryDirectory(prefix="agno-continue-") as workdir:
        notes = Path(workdir) / "notes"
        notes.mkdir()
        (notes / "roadmap.md").write_text(
            "# Roadmap\n\n- ship continue-from\n- ship sandboxes\n"
        )
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
            "List the markdown files in notes/ with `ls notes` and reply with just the file names, "
            "comma separated.",
            session_id=SESSION_ID,
        )
        assert run.status == RunStatus.completed, run.content
        assert "roadmap.md" in tool_outputs(run) and "retro.md" not in tool_outputs(run)
        print(f"Original answer: {run.content}")

        # The workspace changes after the first run.
        (notes / "retro.md").write_text("# Retro\n\n- what went well\n")

        # 1. Replay the same prompt. No input is given, so the stored user message is
        #    re-sent and the ls runs again, now seeing the new file.
        replay = await agent.acontinue_run(
            run_id=run.run_id,
            session_id=SESSION_ID,
            continue_from="last_user",
            fork=True,
        )
        assert replay.status == RunStatus.completed, replay.content
        assert replay.forked_from_run_id == run.run_id
        assert "retro.md" in tool_outputs(replay), (
            "the replayed tool call should see the new file"
        )
        print(f"Replayed answer: {replay.content}")

        # 2. Rewrite the prompt. continue_from=0 branches before the first message, so the
        #    new input replaces the original prompt in this branch.
        rewrite = await agent.acontinue_run(
            run_id=run.run_id,
            session_id=SESSION_ID,
            continue_from=0,
            fork=True,
            input="Count the bullet points across all files in notes/ with "
            "`grep -c '^- ' notes/*.md` and reply with the per-file counts.",
        )
        assert rewrite.status == RunStatus.completed, rewrite.content
        assert rewrite.forked_from_run_id == run.run_id
        assert rewrite.forked_from_message_index == 0
        print(f"Rewritten answer: {rewrite.content}")

        session = await agent.aget_session(SESSION_ID)
        print(f"Runs in session: {len(session.runs or [])}")


if __name__ == "__main__":
    asyncio.run(main())
