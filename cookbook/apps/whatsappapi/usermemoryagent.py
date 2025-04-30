from agno.agent import Agent
from agno.app.whatsapp.app import WhatsappAPI
from agno.app.whatsapp.serve import serve_whatsapp_app
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.manager import MemoryManager
from agno.memory.v2.memory import Memory
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.whatsapp import WhatsAppTools

agent_storage = SqliteStorage(
    table_name="agent_sessions", db_file="tmp/persistent_memory.db"
)
memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")

memory = Memory(
    db=memory_db,
    memory_manager=MemoryManager(
        memory_capture_instructions="""\
                        Collect User's name,
                        Collect 
                        Information about user's passion and hobbies, 
                    """,
    ),
)


# Reset the memory for this example
memory.clear()

personal_agent = Agent(
    name="Basic Agent",
    model=OpenAIChat(id="gpt-4o"),
    add_history_to_messages=True,
    num_history_responses=3,
    add_datetime_to_instructions=True,
    markdown=True,
    memory=memory,
    enable_user_memories=True,
    instructions=(
        "You are a personal agent get to know about the user and personalise your response for them"
    ),
    debug_mode=True,
)


app = WhatsappAPI(
    agent=personal_agent,
).get_app()

if __name__ == "__main__":
    serve_whatsapp_app("usermemoryagent:app", port=8000, reload=True)
