"""Example showing how to use AgentOS with SurrealDB as database"""

r"""
Run SurrealDB in a container before running this script

```
docker run --rm --pull always -p 8000:8000 surrealdb/surrealdb:latest start --user root --pass root
```

or with

```
surreal start -u root -p root
```

Then:

1. Run: `pip install anthropic ddgs newspaper4k lxml_html_clean surrealdb agno` to install the dependencies
2. Run: `python cookbook/agent_os/dbs/surreal_demo.py` to run the demo
"""

from agno.agent import Agent
from agno.db.surrealdb import SurrealDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team.team import Team


# SurrealDB connection parameters
SURREALDB_URL = "ws://localhost:8000"
SURREALDB_USER = "root"
SURREALDB_PASSWORD = "root"
SURREALDB_NAMESPACE = "agno"
SURREALDB_DATABASE = "surrealdb_for_agent_os"

creds = {"username": SURREALDB_USER, "password": SURREALDB_PASSWORD}
db = SurrealDb(None, SURREALDB_URL, creds, SURREALDB_NAMESPACE, SURREALDB_DATABASE, session_table="agno_sessions_team")

# Agent Setup
agent = Agent(
    db=db,
    name="Basic Agent",
    id="basic-agent",
    model=OpenAIChat(id="gpt-4o"),
    add_history_to_context=True,
    num_history_runs=3,
)

# Team Setup
team = Team(
    db=db,
    id="basic-team",
    name="Team Agent",
    model=OpenAIChat(id="gpt-4o"),
    members=[agent],
    add_history_to_context=True,
    num_history_runs=3,
)

# AgentOS Setup
agent_os = AgentOS(
    description="Example OS setup",
    agents=[agent],
    teams=[team],
)

# Get the app
app = agent_os.get_app()

if __name__ == "__main__":
    # Serve the app
    agent_os.serve(app="postgres_demo:app", reload=True)
