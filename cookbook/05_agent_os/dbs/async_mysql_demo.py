"""Example showing how to use AgentOS with a SQLite database"""

from agno.agent import Agent
from agno.db.mysql import AsyncMySQLDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team.team import Team

db_url = "mysql+asyncmy://ai:ai@localhost:3306/ai"

db = AsyncMySQLDb(
    id="mysql-demo",
    db_url=db_url,
    session_table="sessions",
    eval_table="eval_runs",
    memory_table="user_memories",
    metrics_table="metrics",
)


# Setup a basic agent and a basic team
basic_agent = Agent(
    name="Basic Agent",
    id="basic-agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)
team_agent = Team(
    id="basic-team",
    name="Team Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    members=[basic_agent],
)

agent_os = AgentOS(
    description="Example OS setup",
    agents=[basic_agent],
    teams=[team_agent],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="async_mysql_demo:app", reload=True)
