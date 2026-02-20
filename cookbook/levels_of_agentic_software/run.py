"""
Agent OS - Web Interface for the 5 Levels of Agentic Software
===============================================================
This file starts an Agent OS server that provides a web interface for
all 5 levels of agentic software from this cookbook.

All levels are available in the Agent OS UI. Level 5 is the most complete,
with production databases, learning, and tracing. Levels 1-4 are included
so you can compare the progression and test each stage interactively.

How to Use
----------
1. Start PostgreSQL (required for Level 5):
   ./cookbook/scripts/run_pgvector.sh

2. Start the server:
   python cookbook/levels_of_agentic_software/run.py

3. Visit https://os.agno.com in your browser

4. Add your local endpoint: http://localhost:7777

5. Select any agent or team and start chatting:
   - L1 Coding Agent: Stateless tool calling (no setup needed)
   - L2 Coding Agent: Knowledge + storage (ChromaDb + SQLite)
   - L3 Coding Agent: Memory + learning (learns from interactions)
   - L4 Coding Team: Multi-agent team (Coder/Reviewer/Tester)
   - L5 Coding Agent: Production system (PostgreSQL + PgVector + tracing)

Prerequisites
-------------
- PostgreSQL with PgVector running on port 5532 (for Level 5)
- OPENAI_API_KEY environment variable set
"""

from pathlib import Path

from agno.os import AgentOS
from level_1_tools import l1_coding_agent
from level_2_storage_knowledge import l2_coding_agent
from level_3_memory_learning import l3_coding_agent
from level_4_team import l4_coding_team
from level_5_api import l5_coding_agent

# ---------------------------------------------------------------------------
# AgentOS Config
# ---------------------------------------------------------------------------
config_path = str(Path(__file__).parent.joinpath("config.yaml"))

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
# All levels are registered so users can compare the progression.
# Level 5 is the most complete — start there for the full experience.
agent_os = AgentOS(
    id="Coding Agent OS",
    agents=[l1_coding_agent, l2_coding_agent, l3_coding_agent, l5_coding_agent],
    teams=[l4_coding_team],
    config=config_path,
    tracing=True,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="run:app", reload=True)
