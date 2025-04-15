"""
This example shows how you can configure the Memory Manager and Summarizer models individually.

In this example, we use OpenAIChat for the memory manager and Claude for the summarizer. And we use Gemini for the Agent.
"""

from agno.agent.agent import Agent
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory, MemoryManager, SessionSummarizer
from agno.models.anthropic.claude import Claude
from agno.models.google.gemini import Gemini
from agno.models.openrouter.openrouter import OpenRouter

memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")


# You can also set the model for Memory Manager and Summarizer individually
memory = Memory(
    db=memory_db,
    memory_manager=MemoryManager(
        model=OpenRouter(id="meta-llama/llama-3.3-70b-instruct")
    ),
    summarizer=SessionSummarizer(model=Claude(id="claude-3-5-sonnet-20241022")),
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
for i, m in enumerate(memories):
    print(f"{i}: {m.memory}")
