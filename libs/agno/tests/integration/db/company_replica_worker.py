"""Separate worker process for the Company checkpoint recovery regression."""

import asyncio
import json
import sys
from pathlib import Path

from agno.agent import Agent
from agno.company.execution import _call
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.job_queue import QueueConfig
from agno.models.response import ModelResponse
from agno.os import AgentOS, CompanyConfig
from agno.os.job_queue import QueueWorker, resolve_queue_store
from agno.run.cancel import aget_active_runs
from tests.integration.db.test_company_execution_parity import OfflineModel


async def main(config):
    calls = 0

    def checkpoint() -> str:
        """Record the tool side effect before the worker pauses."""
        Path(config["tool"]).write_text("executed once")
        return "checkpoint ready"

    class BlockingModel(OfflineModel):
        async def ainvoke(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return ModelResponse(
                    role="assistant",
                    tool_calls=[
                        {"id": "checkpoint1", "type": "function", "function": {"name": "checkpoint", "arguments": "{}"}}
                    ],
                )
            Path(config["started"]).write_text(json.dumps(await aget_active_runs()))
            for _ in range(3000):
                if Path(config["release"]).exists():
                    return self.invoke(*args, **kwargs)
                await asyncio.sleep(0.01)
            raise TimeoutError("Recovery did not release the worker")

    if config["db_file"]:
        cls = AsyncSqliteDb if config["async"] else SqliteDb
        db = cls(db_file=config["db_file"])
    else:
        cls = AsyncPostgresDb if config["async"] else PostgresDb
        db = cls(db_url=config["url"], db_schema=config["schema"])
    queue_db = PostgresDb(db_url=config["url"], db_schema=config["schema"])
    agent = Agent(
        id="writer", model=BlockingModel(), db=db, tools=[checkpoint], checkpoint="tool-batch", telemetry=False
    )
    queue = QueueConfig(durable=True, db=queue_db, max_attempts=2, retry_delay_seconds=0)
    os = AgentOS(db=db, agents=[agent], company=CompanyConfig(), queue=queue, telemetry=False)
    worker = QueueWorker(
        resolve_queue_store(queue, db), lambda kind, id, scope=None: agent, queue, authorization_app=os.get_app()
    )
    worker._company_db = db
    try:
        job = await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds)
        assert job is not None
        await worker._execute_claimed(job)
    finally:
        await _call(db, "close")
        queue_db.close()


if __name__ == "__main__":
    asyncio.run(main(json.loads(sys.argv[1])))
