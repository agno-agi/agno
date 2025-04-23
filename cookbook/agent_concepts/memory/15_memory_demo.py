from agno.agent import Agent
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from rich.pretty import pprint

user_id = "ava"
db_file = "tmp/memory.db"
memory = Memory(
    db=SqliteMemoryDb(table_name="user_memories", db_file=db_file),
    delete_memories=True,
    clear_memories=True,
)
memory.clear()
storage = SqliteStorage(table_name="agent_sessions", db_file=db_file)

memory_agent = Agent(
    model=OpenAIChat(id="gpt-4.1"),
    memory=memory,
    enable_agentic_memory=True,
    storage=storage,
    add_history_to_messages=True,
    num_history_runs=3,
    read_chat_history=True,
)

memory_agent.print_response("My name is Ava and I like to ski.", user_id=user_id)
print("Memories about Ava:")
pprint(memory.get_user_memories(user_id=user_id))

memory_agent.print_response(
    "I live in san francisco, shall i move to tahoe?", user_id=user_id
)
print("Memories about Ava:")
pprint(memory.get_user_memories(user_id=user_id))
