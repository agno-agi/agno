"""Agno Demo - Showcasing the power of Agno."""

from pathlib import Path

from agents.deep_knowledge_agent import deep_knowledge_agent
from agents.finance_agent import finance_agent
from agents.knowledge_agent import knowledge_agent
from agents.mcp_agent import mcp_agent
from agents.pal_agent import pal_agent
from agents.report_writer_agent import report_writer_agent
from agents.research_agent import research_agent
from agents.web_intelligence_agent import web_intelligence_agent
from agno.os import AgentOS
from teams.due_diligence_team import due_diligence_team
from teams.investment_team import investment_team
from workflows.deep_research_workflow import deep_research_workflow
from workflows.startup_analyst_workflow import startup_analyst_workflow

from db import demo_db

# ============================================================================
# AgentOS Config
# ============================================================================
config_path = str(Path(__file__).parent.joinpath("config.yaml"))

# ============================================================================
# Create AgentOS
# ============================================================================
agent_os = AgentOS(
    agents=[
        pal_agent,
        research_agent,
        finance_agent,
        deep_knowledge_agent,
        web_intelligence_agent,
        report_writer_agent,
        knowledge_agent,
        mcp_agent,
    ],
    teams=[
        investment_team,
        due_diligence_team,
    ],
    workflows=[
        deep_research_workflow,
        startup_analyst_workflow,
    ],
    config=config_path,
    tracing=True,
    db=demo_db,
)
app = agent_os.get_app()

# ============================================================================
# Run AgentOS
# ============================================================================
if __name__ == "__main__":
    # Serves a FastAPI app exposed by AgentOS. Use reload=True for local dev.
    agent_os.serve(app="run:app", reload=True)
