"""
Harness Permission Requests in the AgentOS Chat
===============================================
Claude Code and Codex ask before running a tool their native permission policy does not
allow. Each request pauses the run in the chat with a confirmation card, like an Agno
agent's confirmation tool. Confirm or reject it right there; the same Claude or Codex
process, still waiting, continues with that answer. Nothing is replayed.

Their multiple-choice questions to you pause the same way, as user feedback like Agno's
ask_user tool: pick an option, or type your own answer, and the harness reads it.

Both agents run in a Docker sandbox, through a durable queue on local Postgres.

Build the image and start Postgres (once):
    .venv/bin/python cookbook/frameworks/sandbox/build_image.py --tag agno-sandbox:human-in-the-loop
    ./cookbook/scripts/run_pgvector.sh

With your model credentials available, start AgentOS:
    .venv/bin/python cookbook/frameworks/human_in_the_loop/agentos.py

Connect http://localhost:7777 in the AgentOS UI. Ask either agent to create
confirm-test.txt, then confirm or reject the request in the chat. To try a question, ask:
"Ask me which color I prefer, Red or Blue, then tell me what I picked."
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
db = PostgresDb(
    id="human-in-the-loop-db", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
)
sandbox = DockerSandbox(
    image="agno-sandbox:human-in-the-loop",
    namespace="human-in-the-loop",
    network="isolated",
    checkpoints=FileCheckpointStore(Path("tmp/native-hitl-checkpoints")),
)

# ---------------------------------------------------------------------------
# Create the agents
# ---------------------------------------------------------------------------
# A native policy that can ask, plus a database, pauses the run for confirmation in the chat.
claude = ClaudeAgent(
    id="claude-confirm",
    name="Claude",
    model="claude-sonnet-4-6",
    db=db,
    sandbox=sandbox,
    permission_mode="default",
    hitl_timeout=900,
)
codex = CodexAgent(
    id="codex-confirm",
    name="Codex",
    model="gpt-5.6-luna",
    db=db,
    sandbox=sandbox,
    sandbox_mode="read-only",
    approval_policy="on-request",
    # Codex offers its question tool outside plan mode only behind this feature flag, and its
    # built-in instructions ask required questions in plain text, so ask it to use the tool.
    config={"features": {"default_mode_request_user_input": True}},
    instructions=(
        "When you need to ask the user a question, including a required one, call the "
        "request_user_input tool instead of asking in a message, so the chat can show the "
        "question with its options."
    ),
    hitl_timeout=900,
)

# ---------------------------------------------------------------------------
# Create AgentOS with a Postgres-backed queue
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="harness-human-in-the-loop",
    agents=[claude, codex],
    db=db,
    queue=QueueConfig(durable=True, db=db),
    telemetry=False,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app=app, host="127.0.0.1", port=7777, reload=False)
