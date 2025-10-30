"""
This example shows how you can configure the Memory Manager and Summarizer models individually.

In this example, we use OpenRouter and LLama 3.3-70b-instruct for the memory manager and Claude 3.5 Sonnet for the summarizer. And we use Gemini for the Agent.

We also set custom system prompts for the memory manager and summarizer. You can either override the entire system prompt or add additional instructions which is added to the end of the system prompt.
"""

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.memory import MemoryManager
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url)

# You can also override the entire `system_message` for the memory manager
memory_manager = MemoryManager(
    model=OpenAIChat(id="gpt-4o"),
    additional_instructions="""
    IMPORTANT: Don't store any memories about the user's name. Just say "The User" instead of referencing the user's name.
    """,
    db=db,
)

john_doe_id = "john_doe@example.com"

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    memory_manager=memory_manager,
    enable_user_memories=True,
    user_id=john_doe_id,
)

agent.print_response(
    "My name is John Doe and I like to swim and play soccer.", stream=True
)

agent.print_response("I dont like to swim", stream=True)


memories = agent.get_user_memories(user_id=john_doe_id)

print("John Doe's memories:")
pprint(memories)
