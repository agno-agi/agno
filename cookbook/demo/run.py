"""Minimal demo of the AgentOS."""

from pathlib import Path

from agents.agno_assist import agno_assist
from agents.web_search import web_search_agent
from agno.os import AgentOS
from teams.multilingual_team import multilingual_team
from teams.reasoning_finance_team import reasoning_finance_team
from workflows.investment_workflow import investment_workflow
from workflows.research_workflow import research_workflow

# ************* AgentOS Config *************
config_path = str(Path(__file__).parent.joinpath("config.yaml"))
# *******************************

# ************* Create the AgentOS *************
agent_os = AgentOS(
    description="Demo AgentOS",
    agents=[agno_assist, web_search_agent],
    teams=[reasoning_finance_team, multilingual_team],
    workflows=[research_workflow, investment_workflow],
    config=config_path,
)
# Get the FastAPI app for the AgentOS
app = agent_os.get_app()
# *******************************

# Run the AgentOS
if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:7777/config
    """
    agent_os.serve(app="run:app", reload=True)
