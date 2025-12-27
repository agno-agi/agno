"""
Control Memory Database Tools - Add, Update, Delete, and Clear Operations

This cookbook demonstrates how to control which memory database operations
are available to the AI model using the four DB tools parameters:
- add_memories: Controls whether the AI can add new memories
- update_memories: Controls whether the AI can update existing memories
- delete_memories: Controls whether the AI can delete individual memories
- clear_memories: Controls whether the AI can clear all memories

These parameters provide fine-grained control over memory operations for security
and functionality purposes.
"""

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory.manager import MemoryManager
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

# Setup database and user
memory_db = SqliteDb(db_file="tmp/memory_control_demo.db")
john_doe_id = "john_doe@example.com"

memory_manager_full = MemoryManager(
    model=OpenAIChat(id="gpt-4o"),
    db=memory_db,
    add_memories=True,
    update_memories=True,
)

agent_full = Agent(
    model=OpenAIChat(id="gpt-4o"),
    memory_manager=memory_manager_full,
    enable_agentic_memory=True,
    db=memory_db,
)

# Add initial memory
agent_full.print_response(
    "My name is John Doe and I like to hike in the mountains on weekends. I also enjoy photography.",
    stream=True,
    user_id=john_doe_id,
)

# Test memory recall
agent_full.print_response("What are my hobbies?", stream=True, user_id=john_doe_id)

# Test memory update
agent_full.print_response(
    "I no longer enjoy photography. Instead, I've taken up rock climbing.",
    stream=True,
    user_id=john_doe_id,
)

print("\nMemories after update:")
memories = memory_manager_full.get_user_memories(user_id=john_doe_id)
pprint([m.memory for m in memories] if memories else [])
