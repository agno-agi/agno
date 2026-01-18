"""Agno Demo - Showcasing the power of AI agents, teams, and workflows."""

from pathlib import Path

# ============================================================================
# Import Agents
# ============================================================================
from agents.agno_knowledge_agent import agno_knowledge_agent
from agents.agno_mcp_agent import agno_mcp_agent
from agents.code_executor_agent import code_executor_agent
from agents.data_analyst_agent import data_analyst_agent
from agents.deep_knowledge_agent import deep_knowledge_agent
from agents.devil_advocate_agent import devil_advocate_agent
from agents.finance_agent import finance_agent
from agents.image_analyst_agent import image_analyst_agent
from agents.planning_agent import planning_agent
from agents.report_writer_agent import report_writer_agent
from agents.research_agent import research_agent
from agents.self_learning_agent import self_learning_agent
from agents.self_learning_research_agent import self_learning_research_agent
from agents.sql.sql_agent import sql_agent
from agents.web_intelligence_agent import web_intelligence_agent
from agno.os import AgentOS

# ============================================================================
# Import Teams
# ============================================================================
from teams.due_diligence_team import due_diligence_team
from teams.finance_team import finance_team
from teams.investment_team import investment_team
from teams.research_report_team import research_report_team

# ============================================================================
# Import Workflows
# ============================================================================
from workflows.data_analysis_workflow import data_analysis_workflow
from workflows.deep_research_workflow import deep_research_workflow
from workflows.research_workflow import research_workflow
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
        planning_agent,  # Autonomous planning and execution
        devil_advocate_agent,  # Critical thinking and challenge
        image_analyst_agent,  # Multi-modal image analysis
        web_intelligence_agent,  # Website analysis and intelligence
        # === Research & Knowledge ===
        research_agent,
        deep_knowledge_agent,
        agno_knowledge_agent,
        agno_mcp_agent,
        self_learning_research_agent,
        self_learning_agent,
        # === Data & Code ===
        code_executor_agent,
        data_analyst_agent,
        # === Finance ===
        finance_agent,
        report_writer_agent,
        # === SQL ===
        sql_agent,
    ],
    teams=[
        due_diligence_team,  # Full due diligence with debate
        investment_team,  # Finance + Research + Report Writer
        research_report_team,  # Research + Knowledge + Report Writer
        finance_team,  # Finance + Research
    ],
    workflows=[
        startup_analyst_workflow,  # Complete due diligence pipeline
        deep_research_workflow,  # 4-phase research pipeline
        data_analysis_workflow,  # End-to-end data analysis
        research_workflow,  # Parallel research workflow
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
