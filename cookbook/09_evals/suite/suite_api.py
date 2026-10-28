"""Serve an agent and run grouped evaluations from AgentOS or the REST API.

Run: python cookbook/09_evals/suite/suite_api.py
Connect the frontend to http://localhost:7777 and choose Evaluations > Suites > New Suite.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.calculator import CalculatorTools

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
db = SqliteDb(id="suite-db", db_file="tmp/suite-api.db")
agent = Agent(
    id="math-tutor",
    name="Math Tutor",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[CalculatorTools()],
    instructions="Use the calculator tools for arithmetic.",
    db=db,
)
agent_os = AgentOS(agents=[agent], db=db)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Server
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app=app)
