"""Execute a Company Task with either a sandboxed Claude or Codex engineer.

Prerequisites: PostgreSQL, Redis, Docker, a sandbox runtime image with both SDKs,
ANTHROPIC_API_KEY for Claude or OPENAI_API_KEY for Codex, and a checkpoint directory.
Run: .venv/bin/python cookbook/05_agent_os/30_company/09_sandboxed_engineers.py --executor codex
Try: Repeat with --executor claude. Use --config-only to inspect setup without model calls.
"""

import argparse
import json
import os
import time
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.agents.codex import CodexAgent
from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.os import AgentOS, CompanyConfig
from agno.sandbox import Repository
from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.docker import DockerSandbox
from fastapi.testclient import TestClient

repository = Repository("https://github.com/octocat/Hello-World", branch="master")
db = PostgresDb(
    db_url=os.getenv("DATABASE_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"),
    db_schema="company_engineering",
)
image = os.getenv("SANDBOX_IMAGE", "agno-sandbox:local")
checkpoints = FileCheckpointStore(
    Path(os.getenv("SANDBOX_CHECKPOINTS", "tmp/company-checkpoints"))
)
instructions = "Inspect the checked-out repository, name a file you read and report its contents. Do not push or publish."
claude = ClaudeAgent(
    id="claude-engineer",
    db=db,
    repository=repository,
    sandbox=DockerSandbox(
        image,
        namespace="company-claude",
        network="isolated",
        workspace_mb=2048,
        execution_timeout=1800,
        checkpoints=checkpoints,
    ),
    system_prompt=instructions,
)
codex = CodexAgent(
    id="codex-engineer",
    db=db,
    repository=repository,
    sandbox=DockerSandbox(
        image,
        namespace="company-codex",
        network="isolated",
        workspace_mb=2048,
        execution_timeout=1800,
        checkpoints=checkpoints,
    ),
    sandbox_mode="workspace-write",
    instructions=instructions,
)
agent_os = AgentOS(
    id="company-engineers",
    agents=[claude, codex],
    db=db,
    company=CompanyConfig(),
    queue=QueueConfig(
        durable=True, db=db, redis=os.getenv("REDIS_URL", "redis://localhost:6379/0")
    ),
    telemetry=False,
)


def run(executor: str) -> None:
    with TestClient(agent_os.get_app()) as client:
        product_response = client.post(
            "/company/products", json={"name": "Hello World"}
        )
        product_response.raise_for_status()
        product = product_response.json()
        source_response = client.post(
            "/company/sources",
            json={
                "product_id": product["id"],
                "type": "git",
                "reference": repository.url,
                "config": {"branch": repository.branch},
            },
        )
        source_response.raise_for_status()
        project_response = client.post(
            "/company/projects",
            json={"product_id": product["id"], "name": "Repository inspection"},
        )
        project_response.raise_for_status()
        task_response = client.post(
            "/company/tasks",
            json={
                "product_id": product["id"],
                "project_id": project_response.json()["id"],
                "title": "Inspect README",
                "brief": "Read README and summarize its contents.",
            },
        )
        task_response.raise_for_status()
        task = task_response.json()
        path = "/company/tasks/" + task["id"]
        accepted = client.post(
            path + "/transitions",
            json={
                "target": "ready",
                "reason": "Approved repository inspection",
                "executor_type": "agent",
                "executor_id": executor + "-engineer",
            },
        )
        accepted.raise_for_status()
        assert accepted.json()["sandboxed"] is True
        started = client.post(path + "/runs")
        started.raise_for_status()
        deadline = time.monotonic() + 1900
        while time.monotonic() < deadline:
            response = client.get(path)
            response.raise_for_status()
            task = response.json()
            if task.get("result"):
                break
            time.sleep(1)
        assert task["status"] == "in_review", task.get("result")
        print(task["result"]["content"])
        print(json.dumps(task["metadata"]["checkout"], indent=2))
        print("Task awaits human review")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executor", choices=("claude", "codex"), default="codex")
    parser.add_argument("--config-only", action="store_true")
    args = parser.parse_args()
    if args.config_only:
        print(
            "Configured Claude and Codex with a public repository, Docker and explicit checkpoints"
        )
    else:
        run(args.executor)
