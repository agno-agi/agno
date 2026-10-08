"""Deterministic process fixture for infrastructure tests; no model credentials."""

import asyncio
import json
import os
from pathlib import Path
from typing import Any, AsyncIterator

from agno.agents.base import BaseExternalAgent
from agno.db.postgres import PostgresDb
from agno.run.agent import RunContentEvent, RunOutputEvent
from agno.run.cancel import araise_if_cancelled
from agno.sandbox.runtime import create_runtime_app


class TestHarness(BaseExternalAgent):
    async def _arun_adapter(self, input: Any, **kwargs: Any) -> str:
        command = json.loads(input)
        for _ in range(int(command.get("delay", 0) * 10)):
            await araise_if_cancelled(kwargs["run_id"])
            await asyncio.sleep(0.1)
        target = Path("/workspace/result.txt")
        if "write" in command:
            target.write_text(command["write"])
        history = kwargs.get("history") or []
        return json.dumps(
            {
                "file": target.read_text() if target.exists() else None,
                "history_count": len(history),
            }
        )

    async def _arun_adapter_stream(
        self, input: Any, **kwargs: Any
    ) -> AsyncIterator[RunOutputEvent]:
        yield RunContentEvent(run_id=kwargs["run_id"], content="started\n")
        result = await self._arun_adapter(input, **kwargs)
        yield RunContentEvent(run_id=kwargs["run_id"], content=result)


if __name__ == "__main__":
    import uvicorn

    config = json.loads(os.environ["AGNO_RUNTIME_CONFIG"])
    config["token"] = os.environ["AGNO_RUNTIME_TOKEN"]
    db = PostgresDb(**config["database"])
    agent = TestHarness(id=config["binding"]["agent_id"], db=db)
    uvicorn.run(
        create_runtime_app(config, agent=agent, db=db), host="0.0.0.0", port=7777
    )
