"""Serve a durable sandbox coding agent. See README for the required infrastructure."""

import os
from pathlib import Path

from agno.agents.base import BaseExternalAgent
from agno.agents.claude import ClaudeAgent
from agno.agents.codex import CodexAgent
from agno.db.postgres import PostgresDb
from agno.job_queue.config import QueueConfig, RedisCoordination
from agno.os import AgentOS
from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.docker import DockerSandbox


def create_agent_os() -> AgentOS:
    harness = os.environ.get("SANDBOX_HARNESS", "claude")
    if harness not in ("claude", "codex", "fixture"):
        raise ValueError("SANDBOX_HARNESS must be claude, codex or fixture")
    # The harness's model API key is forwarded from this process's environment.
    # Service Postgres/Redis settings never enter the sandbox.
    sandbox = DockerSandbox(
        os.environ["SANDBOX_RUNTIME_IMAGE"],
        namespace="agentos-sandbox-example",
        network="none" if harness == "fixture" else "isolated",
        # A host whose networks overlap the default range sets AGNO_SANDBOX_SUBNET to a free one.
        subnet=os.environ.get("AGNO_SANDBOX_SUBNET", "172.30.0.0/22"),
        checkpoints=FileCheckpointStore(
            Path(os.environ["SANDBOX_CHECKPOINT_DIRECTORY"])
        ),
        env={"AGNO_SANDBOX_TEST_RUNTIME": "1"} if harness == "fixture" else None,
    )
    agent: BaseExternalAgent
    if harness == "claude":
        agent = ClaudeAgent(id="coder", permission_mode="acceptEdits", sandbox=sandbox)
    elif harness == "codex":
        agent = CodexAgent(id="coder", sandbox_mode="workspace-write", sandbox=sandbox)
    else:
        from agno.sandbox.fixture import FixtureAgent

        agent = FixtureAgent(id="coder", sandbox=sandbox)
    db = PostgresDb(db_url=os.environ["SANDBOX_DATABASE_URL"])
    return AgentOS(
        id="sandbox-example",
        agents=[agent],
        db=db,
        queue=QueueConfig(
            durable=True,
            db=db,
            # Optional: adds live streams and resume from any replica.
            redis=RedisCoordination(
                url=os.environ["SANDBOX_REDIS_URL"],
                key_prefix="agentos-sandbox-example",
            )
            if os.environ.get("SANDBOX_REDIS_URL")
            else None,
            max_attempts=2,
            max_concurrency=4,
        ),
        telemetry=False,
    )


if __name__ == "__main__":
    agent_os = create_agent_os()
    agent_os.serve(
        app=agent_os.get_app(),
        port=int(os.environ.get("SANDBOX_PORT", "7777")),
        reload=False,
    )
