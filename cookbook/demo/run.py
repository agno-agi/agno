"""Minimal demo of the AgentOS."""

from agents.agno_assist import agno_assist
from agno.os import AgentOS
from teams.reasoning_finance_team import reasoning_finance_team

# Create the AgentOS
agent_os = AgentOS(
    description="Demo AgentOS",
    agents=[agno_assist],
    teams=[reasoning_finance_team],
)

# Get the FastAPI app for the AgentOS
app = agent_os.get_app()


if __name__ == "__main__":
    """Run our AgentOS.

    You can see the configuration and available apps at:
    http://localhost:7777/config
    """
    agent_os.serve(app="run:app", reload=True)
