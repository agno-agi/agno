"""
Code Review in a Container from Slack
=====================================

Serve a sandboxed CodexAgent in Slack. Every turn runs in its own Docker
container, and each command Codex asks about becomes an Approve / Deny card.

Prerequisites: SLACK_TOKEN, SLACK_SIGNING_SECRET, OPENAI_API_KEY, Docker, the sandbox runtime image, PostgreSQL (./cookbook/scripts/run_pgvector.sh)
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/sandbox_review.py
Try in Slack: Ask "Run git log -3 and review the latest commit for bugs."
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

import os
from pathlib import Path

from agno.agents.codex import CodexAgent
from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack
from agno.sandbox import Repository
from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.docker import DockerSandbox

# ---------------------------------------------------------------------------
# Create Sandboxed Review Slack AgentOS
# ---------------------------------------------------------------------------

db = PostgresDb(
    id="slack-sandbox-review-db",
    db_url=os.getenv(
        "AGNO_SANDBOX_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"
    ),
)

# With full access the reviewed code can read what is passed in: use a scoped, low-limit OPENAI_API_KEY and never pass a GitHub write token.
reviewer = CodexAgent(
    id="slack-sandbox-reviewer",
    name="Sandboxed Code Reviewer",
    db=db,
    model=os.getenv("CODEX_MODEL", "gpt-5.6-luna"),
    sandbox=DockerSandbox(
        os.getenv("AGNO_SANDBOX_IMAGE", "agno-sandbox:local"),
        network="isolated",
        # A host whose networks overlap the default range sets AGNO_SANDBOX_SUBNET to a free one.
        subnet=os.environ.get("AGNO_SANDBOX_SUBNET", "172.30.0.0/22"),
        memory_mb=1024,
        # This example runs on one host, so a local folder holds the checkpoints. With several replicas,
        # any replica may run the next turn: use a store every replica can read, such as S3CheckpointStore.
        checkpoints=FileCheckpointStore(
            Path.home() / ".agno" / "sandbox" / "checkpoints"
        ),
    ),
    repository=Repository(
        url=os.getenv(
            "REVIEW_REPOSITORY_URL", "https://github.com/octocat/Hello-World"
        ),
        branch=os.getenv("REVIEW_REPOSITORY_BRANCH", "master"),
    ),
    sandbox_mode="full-access",
    approval_policy="untrusted",
    hitl_timeout=900,
    instructions="Review the checked-out repository. Report concrete findings with file paths. Do not push.",
)

agent_os = AgentOS(
    id="slack-sandbox-review-os",
    description="AgentOS serving a sandboxed Codex reviewer in Slack with native approvals.",
    db=db,
    agents=[reviewer],
    queue=QueueConfig(durable=True, db=db),
    interfaces=[Slack(agent=reviewer)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Sandboxed Review Slack AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app, reload=False)
