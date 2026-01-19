"""Agno Demo - Showcasing the power of AI agents, teams, and workflows."""

from pathlib import Path

# ============================================================================
# Import Agents
# ============================================================================
from agents.deep_knowledge_agent import deep_knowledge_agent
from agents.finance_agent import finance_agent
from agents.knowledge_agent import knowledge_agent
from agents.mcp_agent import mcp_agent
from agents.pal_agent import pal_agent
from agents.report_writer_agent import report_writer_agent
from agents.research_agent import research_agent
from agents.web_intelligence_agent import web_intelligence_agent
from agno.os import AgentOS

# ============================================================================
# Import Teams
# ============================================================================
from teams.due_diligence_team import due_diligence_team
from teams.investment_team import investment_team

# ============================================================================
# Import Workflows
# ============================================================================
from workflows.deep_research_workflow import deep_research_workflow
from workflows.startup_analyst_workflow import startup_analyst_workflow

# ============================================================================
# AgentOS Config
# ============================================================================
config_path = str(Path(__file__).parent.joinpath("config.yaml"))

# ============================================================================
# Create AgentOS
# ============================================================================
agent_os = AgentOS(
    agents=[
        # === Flagship Agents ===
        pal_agent,  # Plan and Learn - stateful planning
        research_agent,  # Professional research
        finance_agent,  # Financial analysis
        # === Knowledge & Intelligence ===
        deep_knowledge_agent,  # RAG with iterative reasoning
        web_intelligence_agent,  # Website analysis
        report_writer_agent,  # Report generation
        knowledge_agent,  # General RAG agent
        mcp_agent,  # General MCP agent
    ],
    teams=[
        investment_team,  # Finance + Research + Report Writer
        due_diligence_team,  # Full due diligence with debate
    ],
    workflows=[
        deep_research_workflow,  # 4-phase research pipeline
        startup_analyst_workflow,  # VC-style due diligence
    ],
    config=config_path,
    tracing=True,
)
app = agent_os.get_app()

# ============================================================================
# Run AgentOS
# ============================================================================
if __name__ == "__main__":
    # Serves a FastAPI app exposed by AgentOS. Use reload=True for local dev.
    agent_os.serve(app="run:app", reload=True)
