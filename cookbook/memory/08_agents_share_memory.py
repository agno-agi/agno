"""
In this example, we have two agents that share the same memory.
"""

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.memory import MemoryManager
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from rich.pretty import pprint

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url)

# No need to set the model, it gets set by the agent to the agent's model
memory_manager = MemoryManager(db=db)

john_doe_id = "john_doe@example.com"

chat_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="You are a helpful assistant that can chat with users",
    db=db,
    memory_manager=memory_manager,
    enable_user_memories=True,
)

chat_agent.print_response(
    "My name is John Doe and I like to hike in the mountains on weekends.",
    stream=True,
    user_id=john_doe_id,
)

chat_agent.print_response("What are my hobbies?", stream=True, user_id=john_doe_id)


research_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="You are a research assistant that can help users with their research questions",
    tools=[DuckDuckGoTools(cache_results=True)],
    db=db,
    memory_manager=memory_manager,
    enable_user_memories=True,
)

research_agent.print_response(
    "I love asking questions about quantum computing. What is the latest news on quantum computing?",
    stream=True,
    user_id=john_doe_id,
)

memories = memory_manager.get_user_memories(user_id=john_doe_id)
print("Memories about John Doe:")
pprint(memories)
