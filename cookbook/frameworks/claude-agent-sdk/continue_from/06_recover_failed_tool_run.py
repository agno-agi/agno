"""
Recover after a tool succeeds but the Claude run fails
=====================================================
Record an invoice in a local audit log, then deliberately exhaust max_turns.
Continue from the failed run's end using its stored tool result. The invoice
must remain recorded exactly once: recovery must not repeat the write.

Use --stream to exercise the streaming failure path as well.

Requirements:
    pip install claude-agent-sdk
    Claude credentials configured for the SDK.

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/continue_from/06_recover_failed_tool_run.py
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/continue_from/06_recover_failed_tool_run.py --stream
"""

import argparse
import asyncio
import tempfile
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.os.checkpoints import list_run_checkpoints
from agno.run.agent import RunOutput
from agno.run.base import RunStatus

SESSION_ID = "recover-failed-tool-run"


async def main(stream: bool = False):
    with tempfile.TemporaryDirectory(prefix="agno-recovery-") as workdir:
        workspace = Path(workdir)
        (workspace / "record_invoice.py").write_text(
            "from pathlib import Path\n"
            "audit = Path('audit.log')\n"
            "with audit.open('a') as handle:\n"
            "    handle.write('invoice-1042 recorded\\n')\n"
            "print('Recorded invoice-1042; audit entries:', len(audit.read_text().splitlines()))\n"
        )
        agent = ClaudeAgent(
            id="failed-run-demo",
            model="claude-sonnet-4-6",
            db=SqliteDb(db_file=str(workspace / "runs.db")),
            cwd=workdir,
            system_prompt=f"Your working directory is {workdir}. Follow the requested command exactly.",
            allowed_tools=["Bash"],
            options_kwargs={"tools": ["Bash"]},
            permission_mode="bypassPermissions",
            max_turns=1,
            max_budget_usd=0.5,
        )
        prompt = "Run `python3 record_invoice.py` with Bash exactly once, then summarize its output."
        if stream:
            failed = None
            async for event in agent.arun(
                prompt, session_id=SESSION_ID, stream=True, yield_run_output=True
            ):
                if isinstance(event, RunOutput):
                    failed = event
                else:
                    print(f"Event: {event.event}")
            assert failed is not None
        else:
            failed = await agent.arun(prompt, session_id=SESSION_ID)

        assert failed.status == RunStatus.error, failed.content
        assert "max_turns" in str(failed.content), failed.content
        audit = workspace / "audit.log"
        assert audit.read_text().splitlines() == ["invoice-1042 recorded"]
        assert failed.tools and len(failed.tools) == 1
        assert "audit entries: 1" in str(failed.tools[0].result)
        assert failed.messages[-1].role == "tool"
        print(f"Failed run: {failed.run_id}")
        print(f"Error: {failed.content}")
        print(f"Preserved tool result: {failed.tools[0].result}")
        print("Recovery boundaries:", list_run_checkpoints(failed))

        # Increase the turn limit and resume after the completed tool result.
        # fork=True preserves the failed source run for inspection.
        agent.max_turns = 3
        recovered = await agent.acontinue_run(
            run_id=failed.run_id,
            session_id=SESSION_ID,
            continue_from="end",
            fork=True,
            input="Do not run any tools or repeat the invoice write. From the tool result already "
            "in this conversation, report which invoice was recorded and the audit entry count.",
        )
        assert recovered.status == RunStatus.completed, recovered.content
        assert recovered.forked_from_run_id == failed.run_id
        assert [tool.tool_call_id for tool in recovered.tools or []] == [
            tool.tool_call_id for tool in failed.tools
        ], "recovery must retain the completed call without executing another tool"
        assert audit.read_text().splitlines() == ["invoice-1042 recorded"]
        print(f"Recovered answer: {recovered.content}")
        print(
            "PASS: recovered from the stored result; the invoice was written only once"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stream", action="store_true")
    asyncio.run(main(stream=parser.parse_args().stream))
