"""
Save and Load External Agents
=============================

Demonstrates storing ClaudeAgent and CodexAgent as agent components and loading
them back, with a sandbox resolved from the registry.

Setup:
    ./cookbook/scripts/run_pgvector.sh
    pip install claude-agent-sdk openai-codex
    export ANTHROPIC_API_KEY=... OPENAI_API_KEY=...
"""

from agno.agent import get_agent_by_id
from agno.agents.claude import ClaudeAgent
from agno.agents.codex import CodexAgent
from agno.db.postgres import PostgresDb
from agno.registry import Registry
from agno.sandbox.docker import DockerSandbox

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# A sandbox holds a Docker client, a checkpoint store and credentials, so a
# stored config refers to it by id and the registry supplies the live object.
sandbox = DockerSandbox("agno-sandbox:local", id="docker-local", network="isolated")

# allow_host_external_agents lets AgentOS run stored agents that have no sandbox on this host;
# a stored config names the working directory, MCP servers and permission mode they run with.
registry = Registry(dbs=[db], sandboxes=[sandbox], allow_host_external_agents=True)

# ---------------------------------------------------------------------------
# Create External Agents
# ---------------------------------------------------------------------------
claude_coder = ClaudeAgent(
    id="claude-coder",
    name="Claude Coder",
    description="Reviews code with Claude Code",
    model="claude-sonnet-4-6",
    permission_mode="acceptEdits",
    allowed_tools=["Read", "Grep", "Glob"],
    max_turns=10,
    db=db,
)

codex_coder = CodexAgent(
    id="codex-coder",
    name="Codex Coder",
    description="Reviews code with Codex",
    sandbox_mode="read-only",
    reasoning_effort="medium",
    db=db,
)

# The sandbox is stored as {"id": "docker-local"}; its env and clients never reach the database.
sandboxed_coder = ClaudeAgent(
    id="sandboxed-coder",
    name="Sandboxed Coder",
    permission_mode="bypassPermissions",
    db=db,
    sandbox=sandbox,
)

# ---------------------------------------------------------------------------
# Run External Agent Save and Load Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    for agent in (claude_coder, codex_coder, sandboxed_coder):
        version = agent.save()
        print(f"Saved {agent.id} as version {version}")

    # get_agent_by_id rebuilds the adapter the stored config names.
    loaded = get_agent_by_id(db=db, id="claude-coder", registry=registry, strict=True)
    print(f"Loaded {type(loaded).__name__} {loaded.id} (sdk={loaded.sdk})")
    if loaded:
        loaded.print_response("List the files in the current directory.")

    # An adapter's own load() refuses a config stored for another adapter.
    codex = CodexAgent.load("codex-coder", db=db, registry=registry, strict=True)
    print(
        f"Loaded {type(codex).__name__} {codex.id} with sandbox_mode={codex.sandbox_mode}"
    )

    # The sandboxed agent comes back with the registry's sandbox and runs each turn in a container.
    sandboxed = get_agent_by_id(
        db=db, id="sandboxed-coder", registry=registry, strict=True
    )
    print(f"Loaded {sandboxed.id} with sandbox id {sandboxed.sandbox.id}")

    # Serve them with AgentOS by passing the same registry:
    #   AgentOS(db=db, registry=registry).serve()
    # GET /agents then lists the stored agents with metadata.sdk set.
