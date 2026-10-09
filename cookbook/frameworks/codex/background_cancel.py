"""Serve an external agent with background execution and cancellation.

Run normally to serve AgentOS; pass --verify for a live background/cancel smoke test.
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from agno.agents.codex import CodexAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.run.agent import RunOutput
from agno.run.base import RunStatus

agent = CodexAgent(
    id="codex-background",
    name="codex Background",
    db=SqliteDb(db_file="tmp/codex-background.db"),
    model="gpt-5.6-luna",
    approval_mode="deny_all",
    sandbox="read-only",
)
agent_os = AgentOS(agents=[agent])
app = agent_os.get_app()


async def verify():
    with tempfile.TemporaryDirectory(prefix="agno-cancel-") as temp:
        agent.db = SqliteDb(db_file=str(Path(temp) / "runs.db"))
        agent.cwd = temp
        run_id = str(uuid4())
        cancelled = False
        result = None
        stream = agent.arun(
            "List every integer from 1 through 5000, spelling each one in English. Do not use tools; write the full list.",
            session_id=str(uuid4()),
            run_id=run_id,
            stream=True,
            background=True,
            yield_run_output=True,
        )
        async for item in stream:
            if isinstance(item, RunOutput):
                result = item
                continue
            for line in item.splitlines():
                if line.startswith("data: "):
                    event = json.loads(line[6:])
                    if (
                        event.get("event") == "RunContent"
                        and event.get("content")
                        and not cancelled
                    ):
                        await agent.acancel_run(run_id)
                        cancelled = True
        assert cancelled, "No content arrived to cancel mid-turn"
        assert result is not None and result.status == RunStatus.cancelled, result
        stored = await agent.aget_run_output(run_id, result.session_id)
        assert stored.status == RunStatus.cancelled
        print("PASS: interrupted a live SDK turn and persisted CANCELLED")


if __name__ == "__main__":
    if "--verify" in sys.argv:
        asyncio.run(asyncio.wait_for(verify(), timeout=120))
    else:
        agent_os.serve(app=app, reload=False)
