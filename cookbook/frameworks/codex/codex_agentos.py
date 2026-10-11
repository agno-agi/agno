"""
CodexAgent: Serve the Shipping Reviewer
==========================================
Expose the file-reading agent through AgentOS with local SQLite run storage.

Start the server:
    python cookbook/frameworks/codex/codex_agentos.py

Stream a run from your own client:
    curl -N http://127.0.0.1:7777/agents/codex-reviewer/runs \
      -F 'message=Read shipping.py and explain the shipping fee rules.' \
      -F 'session_id=shipping-review' \
      -F 'stream=true'

Use stream=false for a JSON response. See README.md for more HTTP examples.
Inspect run IDs, streamed tool events and stored results. This local server has
no authentication; keep it bound to loopback. SQLite is for this local exercise only.
This does not establish durable queueing or multi-replica recovery.
"""

import os
from pathlib import Path

from agno.agents.codex import CodexAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Configure Workspace and Storage
# ---------------------------------------------------------------------------
workspace = Path(__file__).resolve().parents[1] / "sample_project"
state_dir = Path(os.getenv("HARNESS_STATE_DIR", "tmp/harnesses/codex"))

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = CodexAgent(
    id="codex-reviewer",
    name="Codex Shipping Reviewer",
    db=SqliteDb(db_file=str(state_dir / "runs.db")),
    model=os.getenv("CODEX_MODEL", "gpt-5.6-luna"),
    cwd=str(workspace),
    sandbox="read-only",
    approval_mode="deny_all",
    reasoning_effort="low",
)
agent_os = AgentOS(agents=[agent])
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(
        app=app, host="127.0.0.1", port=int(os.getenv("PORT", "7777")), reload=False
    )
