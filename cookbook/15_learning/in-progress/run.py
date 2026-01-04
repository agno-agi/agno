"""
Learning Machine Cookbook - AgentOS Entrypoint
===============================================
Run this file to start the AgentOS server with all pattern agents.

Usage:
    python cookbook/15_learning/run.py

Then visit https://os.agno.com and add http://localhost:7777 as an endpoint.
"""

from pathlib import Path

from agno.os import AgentOS
from db import db
from patterns.coding_assistant import coding_assistant
from patterns.onboarding_agent import onboarding_agent
from patterns.personal_assistant import personal_assistant
from patterns.research_agent import research_agent
from patterns.sales_agent import sales_agent

# Import pattern agents
from patterns.support_agent import support_agent
from patterns.team_knowledge_agent import team_knowledge_agent

# Import production agents
from production.gpu_poor_learning import gpu_poor_agent
from production.plan_and_learn import plan_and_learn_agent

# ============================================================================
# AgentOS Config
# ============================================================================
config_path = str(Path(__file__).parent.joinpath("config.yaml"))

# ============================================================================
# Create AgentOS
# ============================================================================
agent_os = AgentOS(
    id="learning-machine-cookbook",
    agents=[
        # Pattern agents
        support_agent,
        research_agent,
        coding_assistant,
        personal_assistant,
        sales_agent,
        team_knowledge_agent,
        onboarding_agent,
        # Production agents
        gpu_poor_agent,
        plan_and_learn_agent,
    ],
    config=config_path,
    tracing=True,
    tracing_db=db,
)
app = agent_os.get_app()

# ============================================================================
# Run AgentOS
# ============================================================================
if __name__ == "__main__":
    # Serves a FastAPI app exposed by AgentOS. Use reload=True for local dev.
    agent_os.serve(app="run:app", reload=True)
