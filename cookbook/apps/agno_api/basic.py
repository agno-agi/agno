from agno.agent import Agent
from agno.app.agno_api import AgnoAPI
from agno.app.agno_api.interfaces.playground import Playground
from agno.app.agno_api.interfaces.slack import Slack
from agno.app.agno_api.interfaces.whatsapp import Whatsapp
from agno.db.sqlite import SqliteStorage
from agno.memory import Memory
from agno.memory.db.sqlite import SqliteMemoryDb
from agno.models.openai import OpenAIChat

agent_storage_file: str = "tmp/agents.db"

memory_storage_file: str = "tmp/memory.db"
memory_db = SqliteMemoryDb(table_name="memory", db_file=memory_storage_file)

# No need to set the model, it gets set by the agent to the agent's model
memory = Memory(db=memory_db)

basic_agent = Agent(
    name="Basic Agent",
    model=OpenAIChat(id="gpt-4o"),
    memory=memory,
    enable_user_memories=True,
    enable_session_summaries=True,
    storage=SqliteStorage(
        table_name="simple_agent", db_file=agent_storage_file, auto_upgrade_schema=True
    ),
    add_history_to_messages=True,
    num_history_responses=3,
    add_datetime_to_instructions=True,
    markdown=True,
)

agno_client = AgnoAPI(
    name="Example App: Basic Agent",
    description="Example app for basic agent with playground capabilities",
    app_id="basic-app",
    agents=[
        basic_agent,
    ],
    interfaces=[Playground(), Whatsapp(agent=basic_agent), Slack(agent=basic_agent)],
)
app = agno_client.get_app()

if __name__ == "__main__":
    agno_client.serve(app="basic:app", reload=True)
