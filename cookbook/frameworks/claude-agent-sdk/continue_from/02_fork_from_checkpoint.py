"""
Fork a ClaudeAgent run from a checkpoint
========================================
Every tool result in a stored run is a checkpoint. Forking from one creates
a sibling run whose Claude conversation stops at that point: the model
remembers what happened up to the checkpoint and nothing after it.

Scenario: the source run analyses a CSV file in three Bash steps (count the
rows, sum a column, write a summary file). The fork branches after the first
step and asks the model, without tools, what it knows about the file. The
branch knows the row count and does not know the total, because that result
is not part of its conversation.

Files are not rewound: summary.txt written in step three stays on disk.

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

SALES_CSV = """region,amount
north,120
south,80
east,200
west,45
north,55
"""


async def main():
    with tempfile.TemporaryDirectory(prefix="agno-continue-") as workdir:
        workspace = Path(workdir)
        (workspace / "sales.csv").write_text(SALES_CSV)
        agent = ClaudeAgent(
            id="continue-demo",
            model="claude-sonnet-4-6",
            db=SqliteDb(db_file=str(workspace / "runs.db")),
            cwd=workdir,
            system_prompt=f"Your working directory is {workdir}. Use Bash for every step.",
            allowed_tools=["Bash"],
            permission_mode="bypassPermissions",
            max_turns=8,
            max_budget_usd=0.5,
        )

        # 1. A three-step tool run. One Bash call per step gives three checkpoints.
        run = await agent.arun(
            "sales.csv has a header row and an amount column. Do these steps in order, one Bash "
            "call each, waiting for each result before the next: "
            "(1) count the data rows with `tail -n +2 sales.csv | wc -l`; "
            "(2) sum the amount column with awk; "
            "(3) write both numbers to summary.txt. "
            "Then reply with just: rows=<n> total=<sum>.",
            session_id=SESSION_ID,
        )
        assert run.status == RunStatus.completed, run.content
        assert (workspace / "summary.txt").exists(), (
            "step three should have written summary.txt"
        )
        print(f"Source run: {run.content}")

        # 2. List the checkpoints: one per tool step and one at the end.
        #    message_index is the value to pass as continue_from.
        checkpoints = list_run_checkpoints(run)
        print("Checkpoints:")
        for checkpoint in checkpoints:
            print(
                f"  {checkpoint['message_index']}: {checkpoint['reason']} "
                f"({checkpoint['message_role']}) {checkpoint['message_preview']}"
            )

        # 3. Fork from the first checkpoint. With one call per step that is the row count.
        #    If Claude batched calls in parallel, the batch is one checkpoint and the branch
        #    keeps every result in it.
        first_step = checkpoints[0]["message_index"]
        kept_results = [
            m for m in (run.messages or [])[:first_step] if m.role == "tool"
        ]
        branch = await agent.acontinue_run(
            run_id=run.run_id,
            session_id=SESSION_ID,
            continue_from=first_step,
            fork=True,
            input="Do not run any tools. From this conversation only: how many data rows does "
            "sales.csv have, and what is the total of the amount column? If you have not "
            "computed one of them yet, say exactly 'not computed yet' for it.",
        )
        assert branch.status == RunStatus.completed, branch.content
        print(f"Branch from step {first_step}: {branch.content}")

        # The branch carries exactly the tool results up to the checkpoint and no new ones.
        branch_results = [m for m in (branch.messages or []) if m.role == "tool"]
        assert [m.tool_call_id for m in branch_results] == [
            m.tool_call_id for m in kept_results
        ]
        assert branch.forked_from_run_id == run.run_id
        assert branch.forked_from_message_index == first_step

        # The source run keeps all of its steps, and the file from step three is still there.
        stored = await agent.aget_run_output(run.run_id, SESSION_ID)
        assert stored is not None and len(stored.messages or []) == len(
            run.messages or []
        )
        print(f"Source run still has {len(stored.messages or [])} messages")
        print(
            f"summary.txt on disk: {(workspace / 'summary.txt').read_text().strip()!r}"
        )


if __name__ == "__main__":
    asyncio.run(main())
