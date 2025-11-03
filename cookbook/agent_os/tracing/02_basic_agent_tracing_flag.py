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

# Set up database
db = SqliteDb(db_file="tmp/traces.db")

agent = Agent(
    name="HackerNews Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[HackerNewsTools()],
    instructions="You are a hacker news agent. Answer questions concisely.",
    markdown=True,
    db=db,
    enable_tracing=True,
)

# Setup our AgentOS app
agent_os = AgentOS(
    description="Example app for tracing HackerNews",
    agents=[agent],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="02_basic_agent_tracing_flag:app", reload=True)
