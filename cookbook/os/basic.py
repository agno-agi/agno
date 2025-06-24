from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.memory import Memory
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.interfaces import Slack, Whatsapp

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Setup the database
db = PostgresDb(
    db_url=db_url,
    agent_session_table="agent_session",
    user_memory_table="user_memory",
)

# Setup the memory
memory = Memory(db=db)


basic_agent = Agent(
    name="Basic Agent",
    model=OpenAIChat(id="gpt-4o"),
    memory=memory,
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_messages=True,
    num_history_runs=3,
    add_datetime_to_instructions=True,
    markdown=True,
)

agent_os = AgentOS(
    name="Example App: Basic Agent",
    description="Example app for basic agent with playground capabilities",
    os_id="basic-app",
    agents=[
        basic_agent,
    ],
    interfaces=[Whatsapp(agent=basic_agent), Slack(agent=basic_agent)],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="basic:app", reload=True)
