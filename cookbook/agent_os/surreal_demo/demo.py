""" This demo shows how to use AgentOS with SurrealDB as database

Run SurrealDB in a container before running this script

```
./cookbook/scripts/run_surrealdb.sh
```

or with

```
surreal start -u root -p root
```
"""

from agno.db.surrealdb import SurrealDb
from agno.os import AgentOS
from agents import get_memory_agent, get_web_search_agent
from teams import get_reasoning_finance_team
from workflows import get_content_creation_workflow

# Setup the SurrealDB database
SURREALDB_URL = "ws://localhost:8000"
SURREALDB_USER = "root"
SURREALDB_PASSWORD = "root"
SURREALDB_NAMESPACE = "agno"
SURREALDB_DATABASE = "agent_os_demo"

creds = {"username": SURREALDB_USER, "password": SURREALDB_PASSWORD}
db = SurrealDb(None, SURREALDB_URL, creds, SURREALDB_NAMESPACE, SURREALDB_DATABASE)


agent_os = AgentOS(
    agents=[get_memory_agent(db), get_web_search_agent(db)],
    teams=[get_reasoning_finance_team(db)],
    workflows=[get_content_creation_workflow(db)],
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="demo:app", reload=True)