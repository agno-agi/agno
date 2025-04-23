from agno.agent import Agent
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.openai import OpenAIChat
from agno.playground import Playground, serve_playground_app
from agno.storage.sqlite import SqliteStorage
from agno.tools.duckduckgo import DuckDuckGoTools

db_file = "tmp/memory.db"

# ************* Memory *************
memory = Memory(
    model=OpenAIChat(id="gpt-4.1"),
    db=SqliteMemoryDb(table_name="user_memories", db_file=db_file),
    delete_memories=True,
    clear_memories=True,
)
# ************* Storage *************
storage = SqliteStorage(table_name="agent_sessions", db_file=db_file)
# *******************************

agent = Agent(
    name="Memory Agent",
    model=OpenAIChat(id="gpt-4.1"),
    memory=memory,
    # Enable the Agent to manage memories
    enable_agentic_memory=True,
    storage=storage,
    # Add chat history to the messages
    add_history_to_messages=True,
    num_history_runs=3,
    # Give the agent a tool to access chat history
    read_chat_history=True,
    # Add datetime to the instructions
    add_datetime_to_instructions=True,
    # Use markdown for the response
    markdown=True,
    # Add a tool to search the web
    tools=[DuckDuckGoTools()],
)


app = Playground(agents=[agent]).get_app()

if __name__ == "__main__":
    serve_playground_app("playground:app")
