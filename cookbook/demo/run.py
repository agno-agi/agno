"""Minimal demo of the AgentOS."""

from pathlib import Path
from textwrap import dedent

from agno.os import AgentOS
from agno_knowledge_agent import agno_knowledge_agent
from agno_mcp_agent import agno_mcp_agent
from competitive_brief import competitive_brief
from finance_agent import finance_agent, reasoning_finance_agent
from finance_team import finance_team
from memory_agent import memory_manager
from research_agent import research_agent
from youtube_agent import youtube_agent

# ============================================================================
# AgentOS Config
# ============================================================================
config_path = str(Path(__file__).parent.joinpath("config.yaml"))

# ============================================================================
# Create AgentOS
# ============================================================================
agent_os = AgentOS(
    description=dedent("""\
        Demo AgentOS — a lightweight runtime wiring together demo agents and teams.
        Includes knowledge lookup (Agno docs), MCP-powered assistance, YouTube QA,
        market analysis, memory management, and web research — all in one process.
        """),
    agents=[
        finance_agent,
        reasoning_finance_agent,
        agno_knowledge_agent,
        agno_mcp_agent,
        memory_manager,
        research_agent,
        youtube_agent,
    ],
    teams=[
        finance_team,
    ],
    workflows=[
        competitive_brief,
    ],
    config=config_path,
)
app = agent_os.get_app()

# ============================================================================
# Run AgentOS
# ============================================================================
if __name__ == "__main__":
    # Serves a FastAPI app exposed by AgentOS. Use reload=True for local dev.
    agent_os.serve(app="run:app", reload=True)
