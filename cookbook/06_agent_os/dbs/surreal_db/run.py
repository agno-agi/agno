"""SurrealDB + AgentOS demo

Steps:
    1. Run SurrealDB in a container: `./cookbook/scripts/run_surrealdb.sh`
    2. Run the demo: `python cookbook/agent_os/dbs/surreal_db/run.py`
"""

from agents import agno_assist
from agno.os import AgentOS
from teams import reasoning_finance_team
from workflows import research_workflow

# ************* Create the AgentOS *************
agent_os = AgentOS(
    description="SurrealDB AgentOS",
    agents=[agno_assist],
    teams=[reasoning_finance_team],
    workflows=[research_workflow],
)
# Get the FastAPI app for the AgentOS
app = agent_os.get_app()
# *******************************

# ************* Run the AgentOS *************
if __name__ == "__main__":
    agent_os.serve(app="run:app", reload=True)
# *******************************
