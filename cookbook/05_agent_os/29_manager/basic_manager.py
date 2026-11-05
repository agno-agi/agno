"""Serve an AgentOS with an OS manager.

Open the AgentOS UI, select OS Manager and ask it to run diagnostics.
This example needs only a model and a database. See manager_builds_agents.py
to add calculator tools and workflow functions to the build palette. The manager
model alone is enough to build basic agents. Platform Manager can consult Agno
docs by default; set access_docs=False on OSManager for an offline deployment.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/29_manager/basic_manager.py
"""

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, OSManager

agent_os = AgentOS(
    name="Manager demo",
    db=SqliteDb(db_file="tmp/manager.db"),
    manager=OSManager(model=OpenAIResponses(id="gpt-5.6-luna")),
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="basic_manager:app", reload=True)
