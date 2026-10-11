"""
Inspect checkpoints when Claude delegates to a subagent
=======================================================
A sales analyst subagent reads a CSV using Bash. Its internal tool results
remain visible in the run, but only the top-level Agent result is a replay
checkpoint. Fork from that result without re-running the analysis.

Requirements:
    pip install claude-agent-sdk
    Claude credentials configured for the SDK.

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/continue_from/07_subagent_checkpoints.py
"""

import asyncio
import tempfile
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.os.checkpoints import list_run_checkpoints
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from claude_agent_sdk import AgentDefinition

SESSION_ID = "subagent-checkpoints"


async def main():
    with tempfile.TemporaryDirectory(prefix="agno-subagent-") as workdir:
        workspace = Path(workdir)
        (workspace / "sales.csv").write_text(
            "region,amount\nnorth,120\nsouth,80\neast,200\n"
        )
        agent = ClaudeAgent(
            id="subagent-checkpoint-demo",
            model="claude-sonnet-4-6",
            db=SqliteDb(db_file=str(workspace / "runs.db")),
            cwd=workdir,
            system_prompt=f"Your working directory is {workdir}. Delegate CSV analysis to sales-analyst.",
            allowed_tools=["Agent", "Bash"],
            permission_mode="bypassPermissions",
            max_turns=6,
            max_budget_usd=1,
            options_kwargs={
                "tools": ["Agent", "Bash"],
                "agents": {
                    "sales-analyst": AgentDefinition(
                        description="Computes sales totals from CSV files.",
                        prompt=f"Your working directory is {workdir}. Use Bash to read sales.csv "
                        "and calculate the row count and sum of the amount column. Return both numbers.",
                        tools=["Bash"],
                        model="sonnet",
                    )
                },
            },
        )
        run = None
        async for event in agent.arun(
            "Use the sales-analyst subagent to analyze sales.csv. Do not run Bash yourself. "
            "Wait for the subagent and summarize its row count and total.",
            session_id=SESSION_ID,
            stream=True,
            yield_run_output=True,
        ):
            if isinstance(event, RunOutput):
                run = event
        assert run is not None and run.status == RunStatus.completed, run
        print(f"Source answer: {run.content}")

        checkpoints = list_run_checkpoints(run)
        checkpoint_indexes = {checkpoint["message_index"] for checkpoint in checkpoints}
        nested_results = []
        top_level_results = []
        for index, message in enumerate(run.messages or [], start=1):
            if message.role != "tool":
                continue
            recorded = bool((message.provider_data or {}).get("claude_sdk"))
            print(
                f"Tool result at message {index}: top_level={recorded}, checkpoint={index in checkpoint_indexes}"
            )
            if recorded:
                top_level_results.append(index)
            else:
                nested_results.append(index)
                assert index not in checkpoint_indexes, (
                    "subagent steps cannot be replayed independently"
                )
                assert message.checkpoint_status is None
        assert nested_results, (
            "the SDK must emit subagent tool messages to demonstrate filtering"
        )
        assert top_level_results, "the parent Agent tool must complete"
        checkpoint = next(
            item for item in checkpoints if item["message_index"] in top_level_results
        )
        print("Selected top-level checkpoint:", checkpoint)
        branch = await agent.acontinue_run(
            run_id=run.run_id,
            session_id=SESSION_ID,
            continue_from=checkpoint["message_index"],
            fork=True,
            input="Without using tools or delegating again, summarize the sales analyst's result already in context.",
        )
        assert branch.status == RunStatus.completed, branch.content
        assert branch.forked_from_run_id == run.run_id
        kept_ids = {
            message.tool_call_id
            for message in run.messages[: checkpoint["message_index"]]
            if message.role == "tool"
        }
        assert {tool.tool_call_id for tool in branch.tools or []} == kept_ids
        print(f"Branch answer: {branch.content}")
        print(
            "PASS: subagent steps were excluded; the parent checkpoint continued successfully"
        )


if __name__ == "__main__":
    asyncio.run(main())
