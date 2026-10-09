"""Continue a ClaudeAgent run from an earlier step.

Each tool result in a stored run is a checkpoint. continue_run forks the Claude SDK
transcript at that point, so the model only remembers what happened up to it. Files
the agent changed after the checkpoint are not rewound.
"""

import asyncio
import tempfile
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.os.checkpoints import list_run_checkpoints
from agno.run.base import RunStatus


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
        run = await agent.arun(
            "Run `echo alpha` with Bash. After it finishes, run `echo beta` in a separate Bash call. "
            "Then reply with just DONE.",
            session_id="continue-demo",
        )
        assert run.status == RunStatus.completed, run.content

        print("Checkpoints:")
        for checkpoint in list_run_checkpoints(run):
            print(
                f"  {checkpoint['message_index']}: {checkpoint['reason']} {checkpoint['message_preview']}"
            )

        first_step = next(
            i
            for i, message in enumerate(run.messages or [], start=1)
            if message.role == "tool"
        )
        branch = await agent.acontinue_run(
            run_id=run.run_id,
            session_id="continue-demo",
            continue_from=first_step,
            fork=True,
            input="List every echo command you have run in this conversation, nothing else.",
        )
        print(f"Branch from step {first_step}: {branch.content}")
        assert "beta" not in (branch.content or ""), branch.content

        replay = await agent.acontinue_run(
            run_id=run.run_id,
            session_id="continue-demo",
            continue_from="last_user",
            fork=True,
        )
        print(f"Replayed turn: {replay.content}")
        assert replay.forked_from_run_id == run.run_id


if __name__ == "__main__":
    asyncio.run(main())
