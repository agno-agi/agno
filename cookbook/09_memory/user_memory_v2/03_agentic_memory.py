"""Agentic Memory - Agent uses tools to manage memory.

In agentic mode, the agent has tools to:
- update_user_profile: Save identity/background
- update_user_policies: Save preferences/rules
- add_user_knowledge: Save context/facts
- add_user_feedback: Save feedback
- manage_user_memory: Delete/clear memory

The agent decides when and what to remember.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory_v2 import MemoryManagerV2
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

db = SqliteDb(db_file="tmp/user_memory.db")
memory = MemoryManagerV2(db=db)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    memory_manager_v2=memory,
    enable_agentic_memory_v2=True,  # Agent has tools to manage memory
    markdown=True,
    show_tool_calls=True,
)

user_id = "jordan"

# Conversation 1: Agent uses update_user_profile tool
print("Conversation 1: User introduces themselves")
agent.print_response(
    "Hi! I'm Jordan, a ML engineer working on computer vision.",
    user_id=user_id,
    stream=True,
)

print("\nMemory after conversation 1:")
pprint(memory.get_user(user_id).to_dict() if memory.get_user(user_id) else {})

# Conversation 2: Agent uses update_user_policies tool
print("\nConversation 2: User states preferences")
agent.print_response(
    "I prefer concise answers. Always include code examples.",
    user_id=user_id,
    stream=True,
)

print("\nMemory after conversation 2:")
pprint(memory.get_user(user_id).to_dict() if memory.get_user(user_id) else {})

# Conversation 3: Agent uses manage_user_memory tool to delete
print("\nConversation 3: User asks to forget something")
agent.print_response(
    "Actually, forget that I work on computer vision - I'm switching to NLP.",
    user_id=user_id,
    stream=True,
)

print("\nMemory after deletion:")
pprint(memory.get_user(user_id).to_dict() if memory.get_user(user_id) else {})

# Cleanup
memory.delete_user(user_id)
