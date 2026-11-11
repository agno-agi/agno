"""Run a sandboxed engineer in a repository pinned on the session's first turn."""

from os import environ

from agno.agents.codex import CodexAgent
from agno.db.postgres import PostgresDb
from agno.sandbox import Repository
from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.docker import DockerSandbox

engineer = CodexAgent(
    id="product-engineer",
    name="Product Engineer",
    db=PostgresDb(db_url=environ["SANDBOX_DATABASE_URL"]),
    sandbox=DockerSandbox(
        image=environ["SANDBOX_IMAGE"],
        network="isolated",
        workspace_mb=1024,
        checkpoints=FileCheckpointStore(environ["SANDBOX_CHECKPOINTS"]),
    ),
    repository=Repository(
        url=environ["REPOSITORY_URL"], branch=environ.get("REPOSITORY_BRANCH", "main")
    ),
    sandbox_mode="workspace-write",
    instructions="Inspect the requested repository, run checks, and report actual results. Do not merge or deploy.",
)

if __name__ == "__main__":
    result = engineer.run(
        "Inspect this application and report what would be required to upgrade AgentOS.",
        session_id=environ["ENGINEER_SESSION_ID"],
    )
    print(result.content)
    print((result.metadata or {}).get("sandbox", {}).get("repository"))
