"""
Example AgentOS app with a custom FastAPI app with basic routes.

You can also run this using the FastAPI cli (pip install fastapi["standard"]):
```
fastapi run custom_fastapi_app.py
```
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.tools.duckduckgo import DuckDuckGoTools
from fastapi import FastAPI

# Setup the database
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

web_research_agent = Agent(
    id="web-research-agent",
    name="Web Research Agent",
    model=Claude(id="claude-sonnet-4-0"),
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

# Custom FastAPI app
app: FastAPI = FastAPI(
    title="Custom FastAPI App",
    version="1.0.0",
)


# Add your own routes
@app.get("/customers")
async def get_customers():
    return [
        {
            "id": 1,
            "name": "John Doe",
            "email": "john.doe@example.com",
        },
        {
            "id": 2,
            "name": "Jane Doe",
            "email": "jane.doe@example.com",
        },
    ]


# Setup our AgentOS app by passing your FastAPI app in the app_config parameter
agent_os = AgentOS(
    description="Example app with custom routers",
    agents=[web_research_agent],
    base_app=app,
)

app = agent_os.get_app()


if __name__ == "__main__":
    """Run your AgentOS.

    With this setup:
    - API docs: http://localhost:7777/docs

    """
    agent_os.serve(app="custom_fastapi_app:app", reload=True)
