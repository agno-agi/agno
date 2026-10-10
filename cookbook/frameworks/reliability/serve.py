"""One isolated Claude or Codex AgentOS replica for readiness verification.

Requires the dedicated Postgres/Redis services in compose.yaml. The controller
supplies provider, port, isolated workspace/SDK home and shared fixture ledger.
This local test server binds loopback and does not demonstrate tenant isolation.
"""

import os
import sys
from pathlib import Path

from agno.db.postgres import PostgresDb
from agno.os import AgentOS, QueueConfig
from ledger import instrument_sdk

# ---------------------------------------------------------------------------
# Configure the Replica
# ---------------------------------------------------------------------------
provider = os.environ["HARNESS_PROVIDER"]
instrument_sdk(provider)
workspace = Path(os.environ["HARNESS_WORKSPACE"])
workspace.mkdir(parents=True, exist_ok=True)
db = PostgresDb(
    db_url=os.environ["HARNESS_DATABASE_URL"],
    db_schema=os.environ["HARNESS_SCHEMA"],
)
server = {
    "command": sys.executable,
    "args": [str(Path(__file__).with_name("tools.py").resolve())],
    "env": {key: os.environ[key] for key in ("HARNESS_LEDGER", "HARNESS_REPLICA")},
}

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
if provider == "claude":
    from agno.agents.claude import ClaudeAgent

    agent = ClaudeAgent(
        id="readiness-claude",
        model="claude-sonnet-5-5",
        db=db,
        cwd=str(workspace),
        tools=[],
        allowed_tools=["mcp__fixture__checkpoint"],
        permission_mode="dontAsk",
        mcp_servers={"fixture": server},
        setting_sources=[],
        strict_mcp_config=True,
    )
else:
    from agno.agents.codex import CodexAgent

    # Explicit authorization applies only to this local synthetic receipt tool.
    server["tools"] = {"checkpoint": {"approval_mode": "approve"}}
    server["required"] = True

    agent = CodexAgent(
        id="readiness-codex",
        model="gpt-5.6-luna",
        reasoning_effort="low",
        db=db,
        cwd=str(workspace),
        sandbox="read-only",
        approval_mode="deny_all",
        mcp_servers={"fixture": server},
    )
agent_os = AgentOS(
    agents=[agent],
    db=db,
    queue=QueueConfig(
        durable=True,
        redis=os.environ["HARNESS_REDIS_URL"],
        max_concurrency=int(os.getenv("HARNESS_CONCURRENCY", "4")),
        max_attempts=int(os.getenv("HARNESS_MAX_ATTEMPTS", "1")),
        retry_delay_seconds=1,
        timeout_seconds=150,
        lock_grace_seconds=12,
        stop_timeout_seconds=5,
        poll_interval=0.25,
    ),
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run the Replica
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(
        app=app, host="127.0.0.1", port=int(os.environ["PORT"]), reload=False
    )
