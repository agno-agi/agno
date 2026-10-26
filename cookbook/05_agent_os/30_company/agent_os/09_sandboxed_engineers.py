"""
Run Sandboxed Engineers in AgentOS
==================================

Serve the Claude and Codex engineers from ../09_sandboxed_engineers.py. A
Backlog Task to inspect a public repository is seeded; accept it for either
engineer and the run happens inside an isolated Docker sandbox.

Prerequisites: PostgreSQL, Redis, Docker, a sandbox runtime image with both SDKs,
ANTHROPIC_API_KEY for Claude or OPENAI_API_KEY for Codex, and a checkpoint directory.
Run: .venv/bin/python cookbook/05_agent_os/30_company/agent_os/09_sandboxed_engineers.py
Try: POST http://localhost:7777/company/tasks/{id}/transitions with
     {"target": "ready", "reason": "Approved repository inspection",
      "executor_type": "agent", "executor_id": "codex-engineer"}
     Then POST /company/tasks/{id}/runs and poll the Task until it is in review.
"""

from os import getenv
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.agents.codex import CodexAgent
from agno.company import CompanyManager
from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.os import AgentOS, CompanyConfig
from agno.sandbox import Repository
from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.docker import DockerSandbox

# ---------------------------------------------------------------------------
# Create Database and Sandbox settings
# ---------------------------------------------------------------------------

repository = Repository("https://github.com/octocat/Hello-World", branch="master")
db = PostgresDb(
    id="company-engineering-db",
    db_url=getenv("DATABASE_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"),
    db_schema="company_engineering",
)
image = getenv("SANDBOX_IMAGE", "agno-sandbox:local")
checkpoints = FileCheckpointStore(
    Path(getenv("SANDBOX_CHECKPOINTS", "tmp/company-checkpoints"))
)
instructions = "Inspect the checked-out repository, name a file you read and report its contents. Do not push or publish."

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="company-engineers",
    description="Claude and Codex execute Company Tasks in Docker sandboxes.",
    agents=[claude, codex],
    db=db,
    company=CompanyConfig(),
    queue=QueueConfig(
        durable=True, db=db, redis=getenv("REDIS_URL", "redis://localhost:6379/0")
    ),
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Seed demo records
# ---------------------------------------------------------------------------
def seed() -> None:
    manager = CompanyManager(db, registry=agent_os.registry)
    if manager.get("hello-world", include_deleted=True) is not None:
        return
    manager.create(id="hello-world", name="Hello World")
    manager.create_source(
        product_id="hello-world",
        type="git",
        reference=repository.url,
        config={"branch": repository.branch},
    )
    project = manager.create_project(
        product_id="hello-world", name="Repository inspection"
    )
    manager.create_task(
        product_id="hello-world",
        project_id=project["id"],
        title="Inspect README",
        brief="Read README and summarize its contents.",
    )


# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    seed()
    agent_os.serve(app=app)
