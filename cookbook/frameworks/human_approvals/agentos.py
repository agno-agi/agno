"""Test Claude and Codex approvals in AgentOS with Docker and local Postgres.

Build the image and start Postgres (once):
    .venv/bin/python cookbook/frameworks/sandbox/build_image.py --tag agno-sandbox:human-approvals
    ./cookbook/scripts/run_pgvector.sh

With your model credentials available, start AgentOS:
    .venv/bin/python cookbook/frameworks/human_approvals/agentos.py

Connect http://localhost:7777 in the AgentOS UI. Ask either agent to create
approval-test.txt, then approve or reject the request and choose Continue Run.
"""

from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.agents.codex import CodexAgent
from agno.db.postgres import PostgresDb
from agno.job_queue.config import QueueConfig
from agno.os import AgentOS
from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.docker import DockerSandbox

# ---------------------------------------------------------------------------
# Configure local Postgres and the Docker sandbox
# ---------------------------------------------------------------------------
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")
sandbox = DockerSandbox(
    image="agno-sandbox:human-approvals",
    namespace="human-approvals",
    network="isolated",
    checkpoints=FileCheckpointStore(Path("tmp/native-approval-checkpoints")),
)

# ---------------------------------------------------------------------------
# Create the agents
# ---------------------------------------------------------------------------
claude = ClaudeAgent(
    id="claude-approvals",
    name="Claude Approvals",
    model="claude-sonnet-4-6",
    db=db,
    sandbox=sandbox,
    permission_mode="default",
    approval_timeout=900,
)
codex = CodexAgent(
    id="codex-approvals",
    name="Codex Approvals",
    model="gpt-5.6-luna",
    db=db,
    sandbox=sandbox,
    sandbox_mode="read-only",
    approval_policy="on-request",
    approval_timeout=900,
)

# ---------------------------------------------------------------------------
# Create AgentOS with a Postgres-backed queue
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="native-approvals",
    agents=[claude, codex],
    db=db,
    queue=QueueConfig(durable=True, db=db),
    telemetry=False,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run the server and connect the AgentOS UI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app=app, host="127.0.0.1", port=7777, reload=False)
