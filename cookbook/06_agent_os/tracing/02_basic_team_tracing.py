from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team import Team
from agno.tools.hackernews import HackerNewsTools

# Set up database
db = SqliteDb(db_file="tmp/traces.db")

# Create agents - no need to set tracing on each one!
agent = Agent(
    name="HackerNews Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[HackerNewsTools()],
    instructions="You are a hacker news agent. Answer questions concisely.",
    markdown=True,
)

team = Team(
    name="HackerNews Team",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[agent],
    instructions="You are a hacker news team. Answer questions concisely using HackerNews Agent member",
    db=db,
)

# Setup AgentOS with tracing=True
# This automatically enables tracing for ALL agents and teams!
agent_os = AgentOS(
    description="Example app for tracing HackerNews",
    teams=[team],
    tracing=True,
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="02_basic_team_tracing:app", reload=True)
