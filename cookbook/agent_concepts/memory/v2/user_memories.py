from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.memory.manager import MemoryManager  # noqa: F401
from agno.models.openai import OpenAIChat

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(
    db_url=db_url,
    session_table="sessions",
    user_memory_table="user_memories",
)

# 1. Using the default memory manager by setting enable_user_memories=True
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    session_id="user_memories",
    enable_user_memories=True,
)

agent.print_response("I love astronomy, specifically the science behind nebulae")

# 2. Using a custom memory manager by creating an instance of MemoryManager
# memory_manager = MemoryManager(model=OpenAIChat(id="gpt-4o-mini"))

# agent = Agent(
#     model=OpenAIChat(id="gpt-4o-mini"),
#     db=db,
#     session_id="user_memories",
#     memory_manager=memory_manager,
# )

# agent.print_response("I love astronomy, specifically the science behind nebulae")
