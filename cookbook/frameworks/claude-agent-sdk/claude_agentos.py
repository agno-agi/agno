"""
ClaudeAgent: Serve the Shipping Reviewer
==========================================
Expose the file-reading agent through AgentOS with local SQLite run storage.

Start the server:
    python cookbook/frameworks/claude-agent-sdk/claude_agentos.py

Stream a run from your own client:
    curl -N http://127.0.0.1:7777/agents/claude-reviewer/runs \
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

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Configure Workspace and Storage
# ---------------------------------------------------------------------------
workspace = Path(__file__).resolve().parents[1] / "sample_project"
state_dir = Path(os.getenv("HARNESS_STATE_DIR", "tmp/harnesses/claude"))

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = ClaudeAgent(
    id="claude-reviewer",
    name="Claude Shipping Reviewer",
    db=SqliteDb(db_file=str(state_dir / "runs.db")),
    model="claude-sonnet-5-5",
    cwd=str(workspace),
    allowed_tools=["Read"],
    permission_mode="dontAsk",
    tools=["Read"],
    setting_sources=[],
    strict_mcp_config=True,
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
