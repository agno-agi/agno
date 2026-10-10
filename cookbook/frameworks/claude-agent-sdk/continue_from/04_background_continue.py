"""
Continue a ClaudeAgent run in the background, streamed
======================================================
A continuation can run in the background like any other run. With
background=True and stream=True the call returns an indexed event stream
that survives client disconnects: the run keeps going on the server, and a
client can reconnect to the same stream later through the AgentOS resume
endpoint. This is what the AgentOS UI uses for long-running agent turns.

Scenario: the source run writes a script but does not run it. The
continuation is submitted in the background and streamed: tool events and
content arrive as they happen, the final RunOutput is yielded last, and the
same result is then read back from the database.

A finished run is always continued as a new run, so the background job gets
a fresh run_id with forked_from_run_id pointing at the source.

Requirements:
    pip install claude-agent-sdk
    A database with transcript storage (SQLite or PostgreSQL).

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/continue_from/04_background_continue.py
"""

import asyncio
import json
import tempfile
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.run.agent import RunOutput
from agno.run.background import await_background_runs
from agno.run.base import RunStatus

SESSION_ID = "background-continue"


def sse_events(chunk: str):
    """Background streams yield SSE text; each data line is one JSON event."""
    for line in chunk.splitlines():
        if line.startswith("data: "):
            yield json.loads(line[6:])


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
            allowed_tools=["Write", "Bash"],
            permission_mode="bypassPermissions",
            max_turns=8,
            max_budget_usd=0.5,
        )

        source = await agent.arun(
            "Write fizzbuzz.py that prints FizzBuzz for 1 through 15, one value per line. "
            "Do not run it. Reply with just the file name.",
            session_id=SESSION_ID,
        )
        assert source.status == RunStatus.completed, source.content
        assert (workspace / "fizzbuzz.py").exists()
        print(f"Source run {source.run_id[:8]}: {source.content}")

        # Submit the continuation in the background and follow its event stream.
        # yield_run_output=True makes the final RunOutput the last item.
        stream = agent.acontinue_run(
            run_id=source.run_id,
            session_id=SESSION_ID,
            input="Now run the script you wrote with python3 and reply with just its last line.",
            background=True,
            stream=True,
            yield_run_output=True,
        )
        print("Streaming:")
        result = None
        seen = []
        async for item in stream:
            if isinstance(item, RunOutput):
                result = item
                continue
            for event in sse_events(item):
                kind = event.get("event")
                seen.append(kind)
                if kind == "RunStarted":
                    print(f"  {kind} run_id={event.get('run_id', '')[:8]}")
                elif kind == "ToolCallStarted":
                    tool = event.get("tool") or {}
                    print(
                        f"  {kind} {tool.get('tool_name')} {json.dumps(tool.get('tool_args'))[:80]}"
                    )
                elif kind == "ToolCallCompleted":
                    tool = event.get("tool") or {}
                    print(f"  {kind} {str(tool.get('result'))[:60]!r}")
                elif kind == "RunContent" and event.get("content"):
                    print(f"  {kind} {event['content']!r}")
                elif kind in ("RunCompleted", "RunError", "RunCancelled"):
                    print(f"  {kind}")

        assert result is not None, "the stream should end with the RunOutput"
        assert result.status == RunStatus.completed, result.content
        assert result.run_id != source.run_id
        assert result.forked_from_run_id == source.run_id
        assert "RunCompleted" in seen, seen
        print(f"Finished run {result.run_id[:8]}: {result.content!r}")

        # The same result is in the database for any client that reconnects later.
        stored = await agent.aget_run_output(result.run_id, SESSION_ID)
        assert stored is not None and stored.status == RunStatus.completed
        outputs = [str(m.content) for m in stored.messages or [] if m.role == "tool"]
        assert any("FizzBuzz" in output for output in outputs), (
            "the script should have been run"
        )
        print(
            f"Stored run {stored.run_id[:8]}: {stored.status} with {len(outputs)} tool results"
        )

        # The stream ends before the run marks its event stream complete. Let that finish
        # before the loop closes; a long-lived server does not need this.
        await await_background_runs()


if __name__ == "__main__":
    asyncio.run(main())
