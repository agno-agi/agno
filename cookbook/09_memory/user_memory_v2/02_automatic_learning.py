"""Automatic Learning - Agent extracts user info from conversations.

The agent automatically extracts:
- Profile: name, role, company, skills
- Policies: preferences like "be concise"
- Knowledge: project context, decisions
- Feedback: what worked or didn't
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory_v2 import MemoryManagerV2
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

db = SqliteDb(db_file="tmp/user_memory.db")
memory = MemoryManagerV2(
    db=db,
    model=OpenAIChat(id="gpt-4o-mini"),
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    memory_manager_v2=memory,
    update_memory_on_run=True,  # Automatic extraction enabled
    markdown=True,
)

user_id = "alex"

# Conversation 1: User shares profile info
print("Conversation 1: User introduces themselves")
agent.print_response(
    "Hi! I'm Alex, a senior backend engineer at TechCorp. "
    "I work mostly with Go and Python.",
    user_id=user_id,
    stream=True,
)

print("\nExtracted profile:")
pprint(memory.get_user(user_id).user_profile)

# Conversation 2: User shares preferences (policies)
print("\nConversation 2: User states preferences")
agent.print_response(
    "I prefer detailed technical explanations with code examples. "
    "Always include error handling.",
    user_id=user_id,
    stream=True,
)

print("\nExtracted policies:")
pprint(memory.get_user(user_id).policies)

# Conversation 3: Agent uses learned context
print("\nConversation 3: Agent uses context to respond")
agent.print_response(
    "How should I implement rate limiting?",
    user_id=user_id,
    stream=True,
)

# Show compiled context injected into system message
print("\nCompiled context (what agent sees):")
print(memory.compile_user_context(user_id))

# Cleanup
memory.delete_user(user_id)
