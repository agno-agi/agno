"""
Traces with AgentOS
Requirements:
    pip install agno opentelemetry-api opentelemetry-sdk openinference-instrumentation-agno
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from agno.tracing.setup import setup_tracing

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# Set up databases - each agent has its own db
db1 = SqliteDb(db_file="tmp/db1.db", id="db1")
db2 = SqliteDb(db_file="tmp/db2.db", id="db2")

# Dedicated traces database
tracing_db = SqliteDb(db_file="tmp/traces.db", id="traces")

setup_tracing(
    db=tracing_db, batch_processing=True, max_queue_size=1024, max_export_batch_size=256
)

agent = Agent(
    name="HackerNews Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[HackerNewsTools()],
    instructions="You are a hacker news agent. Answer questions concisely.",
    markdown=True,
    db=db1,
)

agent2 = Agent(
    name="Web Search Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[WebSearchTools()],
    instructions="You are a web search agent. Answer questions concisely.",
    markdown=True,
    db=db2,
)

# Setup our AgentOS app with dedicated db
# This ensures traces are written to and read from the same database
agent_os = AgentOS(
    description="Example app for tracing HackerNews",
    agents=[agent, agent2],
    db=tracing_db,  # Default database for the AgentOS (used for tracing)
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="06_tracing_with_multi_db_scenario:app", reload=True)
