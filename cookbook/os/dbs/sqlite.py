"""Example showing how to use AgentOS with a SQLite database"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory import Memory
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.interfaces import Whatsapp
from agno.os.managers.session import SessionManager
from agno.team.team import Team

# Setup the SQLite database
db = SqliteDb(
    db_file="agno-os.db",
    session_table="sessions",
)

# Setup the memory
memory = Memory(db=db)

basic_agent = Agent(
    name="Basic Agent",
    agent_id="basic",
    model=OpenAIChat(id="gpt-4o"),
    memory=memory,
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_messages=True,
    num_history_runs=3,
    add_datetime_to_instructions=True,
    markdown=True,
)

team_agent = Team(
    name="Team Agent",
    model=OpenAIChat(id="gpt-4o"),
    memory=memory,
    members=[basic_agent],
    debug_mode=True,
)

agent_os = AgentOS(
    name="Example App: Basic Agent",
    description="Example app for basic agent with playground capabilities",
    os_id="basic-app",
    agents=[basic_agent],
    teams=[team_agent],
    interfaces=[Whatsapp(agent=basic_agent)],
    apps=[SessionManager(db=db)],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="sqlite:app", reload=True)
