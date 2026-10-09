"""
Fork a ClaudeAgent run from a checkpoint
========================================
Every tool result in a stored run is a checkpoint. Forking from one creates
a sibling run whose Claude conversation stops at that point, so the model
only remembers what happened up to the checkpoint. Everything after it is
left out of the branch, but files the agent changed are not rewound.

Requirements:
    pip install claude-agent-sdk
    A database with transcript storage (SQLite or PostgreSQL).

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/continue_from/02_fork_from_checkpoint.py
"""

import asyncio
import tempfile
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.os.checkpoints import list_run_checkpoints
from agno.run.base import RunStatus

SESSION_ID = "fork-from-checkpoint"


async def main():
    with tempfile.TemporaryDirectory(prefix="agno-continue-") as workdir:
        agent = ClaudeAgent(
            id="continue-demo",
            model="claude-sonnet-4-6",
            db=SqliteDb(db_file=str(Path(workdir) / "runs.db")),
            cwd=workdir,
            allowed_tools=["Bash"],
            permission_mode="bypassPermissions",
            max_turns=6,
            max_budget_usd=0.5,
        )

        # 1. A two-step tool run.
        run = await agent.arun(
            "Run `echo alpha` with Bash. After it finishes, run `echo beta` in a separate Bash call. "
            "Then reply with just DONE.",
            session_id=SESSION_ID,
        )
        assert run.status == RunStatus.completed, run.content

        # 2. List the checkpoints. There is one per tool step and one at the end.
        #    message_index is the value to pass as continue_from.
        checkpoints = list_run_checkpoints(run)
        print("Checkpoints:")
        for checkpoint in checkpoints:
            print(
                f"  {checkpoint['message_index']}: {checkpoint['reason']} "
                f"({checkpoint['message_role']}) {checkpoint['message_preview']}"
            )

        # 3. Fork from the first checkpoint. With sequential calls that is the first
        #    tool result. If Claude issued both commands in parallel, the batch is a
        #    single checkpoint and the branch keeps both results.
        first_step = checkpoints[0]["message_index"]
        kept_results = [
            m for m in (run.messages or [])[:first_step] if m.role == "tool"
        ]
        branch = await agent.acontinue_run(
            run_id=run.run_id,
            session_id=SESSION_ID,
            continue_from=first_step,
            fork=True,
            input="List every echo command you have run in this conversation, nothing else.",
        )
        assert branch.status == RunStatus.completed, branch.content
        print(f"Branch from step {first_step}: {branch.content}")

        # The branch carries exactly the tool results up to the checkpoint.
        branch_results = [m for m in (branch.messages or []) if m.role == "tool"]
        assert [m.tool_call_id for m in branch_results] == [
            m.tool_call_id for m in kept_results
        ]
        assert branch.forked_from_run_id == run.run_id
        assert branch.forked_from_message_index == first_step

        # The source run keeps all of its steps.
        stored = await agent.aget_run_output(run.run_id, SESSION_ID)
        assert stored is not None and len(stored.messages or []) == len(
            run.messages or []
        )
        print(f"Source run still has {len(stored.messages or [])} messages")


if __name__ == "__main__":
    asyncio.run(main())
