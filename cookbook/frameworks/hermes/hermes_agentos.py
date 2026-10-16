"""Serve Hermes through AgentOS with SQLite storage for local development."""

import os
from pathlib import Path

from agno.agents.hermes import HermesAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

workspace = Path(__file__).resolve().parents[1] / "sample_project"
state_dir = Path(os.getenv("HARNESS_STATE_DIR", "tmp/harnesses/hermes"))
agent = HermesAgent(
    id="hermes-reviewer",
    name="Hermes Shipping Reviewer",
    model=os.getenv("HERMES_MODEL"),
    cwd=str(workspace),
    enabled_toolsets=["file"],
    instructions="Explain the shipping code. Do not modify files.",
    max_iterations=20,
    db=SqliteDb(db_file=str(state_dir / "runs.db")),
)
agent_os = AgentOS(agents=[agent])
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(
        app=app, host="127.0.0.1", port=int(os.getenv("PORT", "7777")), reload=False
    )
