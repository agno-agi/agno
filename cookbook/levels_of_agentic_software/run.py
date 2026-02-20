"""
Agent OS - Web Interface for the 5 Levels of Agentic Software
===============================================================
This file starts an Agent OS server that provides a web interface for
the coding agent and coding team from this cookbook.

How to Use
----------
1. Start PostgreSQL (required for Level 5):
   ./cookbook/scripts/run_pgvector.sh

2. Start the server:
   python cookbook/levels_of_agentic_software/run.py

3. Visit https://os.agno.com in your browser

4. Add your local endpoint: http://localhost:7777

5. Select the coding agent or coding team and start chatting

Prerequisites
-------------
- PostgreSQL with PgVector running on port 5532
- OPENAI_API_KEY environment variable set
"""

from pathlib import Path

from agno.os import AgentOS
from level_4_team import coding_team
from level_5_api import coding_agent

# ---------------------------------------------------------------------------
# AgentOS Config
# ---------------------------------------------------------------------------
config_path = str(Path(__file__).parent.joinpath("config.yaml"))

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="Coding Agent OS",
    agents=[coding_agent],
    teams=[coding_team],
    config=config_path,
    tracing=True,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="run:app", reload=True)
