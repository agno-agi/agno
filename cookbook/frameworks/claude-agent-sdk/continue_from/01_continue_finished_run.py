"""
Continue a finished ClaudeAgent run
===================================
A completed run can be continued with a follow-up instruction. The
continuation is a new run in the same session that carries the full Claude
conversation, so the model remembers the code it wrote and the decisions it
made in the source run.

Scenario: the first run writes a small Python module and runs it. The
continuation asks for a test file for "the function you just wrote" without
naming it, which only works if the model still has the source run's context.

Like native Agno agents, a finished run is never rewritten in place: the
continuation gets its own run_id and records where it came from in
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
        workspace = Path(workdir)
        agent = ClaudeAgent(
            id="continue-demo",
            model="claude-sonnet-4-6",
            db=SqliteDb(db_file=str(workspace / "runs.db")),
            cwd=workdir,
            # The SDK's default system prompt does not name the working directory, so tell
            # the model where to create files; Bash already runs there.
            system_prompt=f"Your working directory is {workdir}. Create and run files there.",
            allowed_tools=["Write", "Read", "Bash"],
            permission_mode="bypassPermissions",
            max_turns=8,
            max_budget_usd=0.5,
        )

        # 1. The source run: write a module and run it.
        source = await agent.arun(
            "Create slugify.py with a function slugify(text) that lowercases the text, replaces "
            "every run of non-alphanumeric characters with a single hyphen, and strips leading and "
            "trailing hyphens. Then run it with python3 to print slugify('Hello, World!') and reply "
            "with just the printed output.",
            session_id=SESSION_ID,
        )
        assert source.status == RunStatus.completed, source.content
        assert (workspace / "slugify.py").exists(), (
            "the source run should have written slugify.py"
        )
        print(f"Source run {source.run_id[:8]}: {source.content}")

        # 2. Continue it. continue_from defaults to "end": the follow-up is appended after
        #    the last message of the source run. The prompt never names the function or the
        #    file, so the model has to remember them from the source run.
        continued = await agent.acontinue_run(
            run_id=source.run_id,
            session_id=SESSION_ID,
            input="Write test_slugify.py with three plain assert statements covering the function "
            "you just wrote, including the example you ran, and a final print('ok'). Run it with "
            "python3 and reply with just what it printed.",
        )
        assert continued.status == RunStatus.completed, continued.content
        assert (workspace / "test_slugify.py").exists(), (
            "the continuation should have written the test file"
        )
        print(f"Continued run {continued.run_id[:8]}: {continued.content}")
        print(
            f"Workspace: {sorted(p.name for p in workspace.iterdir() if p.suffix == '.py')}"
        )

        # The continuation is a new run with lineage back to the source.
        assert continued.run_id != source.run_id
        assert continued.forked_from_run_id == source.run_id
        assert continued.forked_from_message_index == len(source.messages or [])

        # The source run is untouched and the session holds both runs.
        stored = await agent.aget_run_output(source.run_id, SESSION_ID)
        assert stored is not None and stored.content == source.content
        session = await agent.aget_session(SESSION_ID)
        print(f"Runs in session: {len(session.runs or [])}")
        for run in session.runs or []:
            lineage = (run.forked_from_run_id or "")[:8] or "-"
            tools = sum(1 for m in run.messages or [] if m.role == "tool")
            print(
                f"  {run.run_id[:8]} forked_from={lineage} tool_calls={tools} content={run.content!r}"
            )


if __name__ == "__main__":
    asyncio.run(main())
