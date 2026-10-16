"""A second AgentOS service in its own process, for the sandbox integration tests.

Started with one JSON argument naming the tables, Redis prefix and checkpoint directory of the service under test, it
serves the same fixture agent on a real local port. It shares nothing in memory with the test process, so a run it
completes was reconstructed from what the database and Redis hold.
"""

import json
import sys

import redis
import redis.asyncio
import uvicorn

from agno.db.postgres import PostgresDb
from agno.job_queue.config import QueueConfig, RedisCoordination
from agno.os import AgentOS
from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.docker import DockerSandbox
from agno.sandbox.fixture import FixtureAgent


def main(config: dict) -> None:
    db = PostgresDb(db_url=config["db_url"], **config["tables"])
    provider = DockerSandbox(
        config["image"],
        namespace=config["prefix"],
        memory_mb=512,
        workspace_mb=32,
        env={"AGNO_SANDBOX_TEST_RUNTIME": "1"},
        checkpoints=FileCheckpointStore(config["checkpoints"]),
    )
    queue = QueueConfig(
        durable=True,
        db=db,
        redis=RedisCoordination(
            sync_client=redis.Redis.from_url(config["redis_url"]),
            async_client=redis.asyncio.Redis.from_url(config["redis_url"]),
            key_prefix=config["prefix"],
        ),
        poll_interval=0.05,
        max_attempts=2,
        retry_delay_seconds=0,
        stop_timeout_seconds=1,
        **config.get("queue", {}),
    )
    agents = [FixtureAgent(id="coder", sandbox=provider)]
    app = AgentOS(id=config["prefix"], agents=agents, db=db, queue=queue, telemetry=False).get_app()
    uvicorn.run(app, host="127.0.0.1", port=config["port"], log_level="warning")


if __name__ == "__main__":
    main(json.loads(sys.argv[1]))
