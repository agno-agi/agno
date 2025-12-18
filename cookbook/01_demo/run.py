"""Minimal demo of the AgentOS."""

from pathlib import Path

from agents.agno_knowledge_agent import agno_knowledge_agent
from agents.agno_mcp_agent import agno_mcp_agent
from agents.deep_knowledge_agent import deep_knowledge_agent
from agents.finance_agent import finance_agent
from agents.memory_manager import memory_manager
from agents.reasoning_research_agent import reasoning_research_agent
from agents.research_agent import research_agent
from agents.self_learning_agent import self_learning_agent
from agents.self_learning_research_agent import self_learning_research_agent
from agents.sql.sql_agent import sql_agent
from agents.youtube_agent import youtube_agent
from agno.os import AgentOS
from teams.finance_team import finance_team
from workflows.research_workflow import research_workflow

# ============================================================================
# AgentOS Config
# ============================================================================
config_path = str(Path(__file__).parent.joinpath("config.yaml"))

# ============================================================================
# Create AgentOS
# ============================================================================
agent_os = AgentOS(
    agents=[
        agno_mcp_agent,
        agno_knowledge_agent,
        finance_agent,
        research_agent,
        reasoning_research_agent,
        deep_knowledge_agent,
        memory_manager,
        youtube_agent,
        sql_agent,
        self_learning_research_agent,
        self_learning_agent,
    ],
    teams=[finance_team],
    workflows=[research_workflow],
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
