"""
This example shows how you can configure the Memory Manager and Summarizer models individually.

In this example, we use OpenRouter and LLama 3.3-70b-instruct for the memory manager and Claude 3.5 Sonnet for the summarizer. And we use Gemini for the Agent.

We also set custom system prompts for the memory manager and summarizer. You can either override the entire system prompt or add additional instructions which is added to the end of the system prompt.
"""

from agno.agent.agent import Agent
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory, MemoryManager, SessionSummarizer
from agno.models.anthropic.claude import Claude
from agno.models.google.gemini import Gemini
from agno.models.openrouter.openrouter import OpenRouter
from rich.pretty import pprint

memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")


# You can also override the entire `system_message` for the memory manager
memory_manager = MemoryManager(
    model=OpenRouter(id="meta-llama/llama-3.3-70b-instruct"),
    additional_instructions="""
    IMPORTANT: Don't store any memories about the user's name. Just say "The User" instead of referencing the user's name.
    """,
)

# You can also override the entire `system_message` for the session summarizer
session_summarizer = SessionSummarizer(
    model=Claude(id="claude-3-5-sonnet-20241022"),
    additional_instructions="""
    Make the summary very informal and conversational.
    """,
)

memory = Memory(
    db=memory_db,
    memory_manager=memory_manager,
    summarizer=session_summarizer,
)

# Reset the memory for this example
memory.clear()

john_doe_id = "john_doe@example.com"

agent = Agent(
    model=Gemini(id="gemini-2.0-flash-exp"),
    memory=memory,
    enable_user_memories=True,
    enable_session_summaries=True,
    user_id=john_doe_id,
)

agent.print_response(
    "My name is John Doe and I like to swim and play soccer.", stream=True
)

agent.print_response("I dont like to swim", stream=True)


memories = memory.get_user_memories(user_id=john_doe_id)

print("John Doe's memories:")
pprint(memories)

summary = agent.get_session_summary()
print("Session summary:")
pprint(summary)
