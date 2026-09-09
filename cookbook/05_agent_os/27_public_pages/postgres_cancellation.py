"""Serve with cancellation shared by workers using the existing PostgreSQL DB.

Set PAGE_DEMO_DB_URL and OPENAI_API_KEY, then run:
    python postgres_cancellation.py
The example uses two Uvicorn workers and the public session/run ownership gate.
"""

from contextlib import asynccontextmanager
from os import getenv

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.job_queue import QueueConfig
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.public import PublicSurface
from agno.run.cancel import set_cancellation_manager
from agno.run.cancellation_management import PostgresRunCancellationManager

db = PostgresDb(
    db_url=getenv(
        "PAGE_DEMO_DB_URL",
        "postgresql+psycopg://ai:ai@localhost:5532/cancellation_demo",
    )
)
cancellation = PostgresRunCancellationManager(db, namespace="cancellation-demo")
set_cancellation_manager(cancellation)


@asynccontextmanager
async def lifespan(app):
    await cancellation.asetup()
    yield


agent = Agent(id="writer", model=OpenAIResponses(id="gpt-5.6-luna"), db=db)
agent_os = AgentOS(
    id="cancellation-demo",
    db=db,
    agents=[agent],
    public=PublicSurface(agents=[agent]),
    queue=QueueConfig(durable=True),
    lifespan=lifespan,
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(
        "postgres_cancellation:app",
        host="127.0.0.1",
        port=8000,
        workers=2,
        reload=False,
    )
