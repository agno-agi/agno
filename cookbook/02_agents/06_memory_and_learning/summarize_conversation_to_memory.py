"""
Summarize Conversation Into Memory
==================================

Demonstrates turning a multi-turn conversation into concise user memories.

The agent captures facts after each turn (`update_memory_on_run`), then
consolidates the discussion into a short memory brief the user can recall later.

Key concepts:
- update_memory_on_run: extract memories automatically after each response
- enable_agentic_memory: agent can merge or rewrite memories on request
- Memories are durable summaries, not full chat transcripts

Example prompts to try:
- "I'm planning a trip to Kyoto in April."
- "I want temples, tea houses, and one day trip to Nara."
- "Summarize our trip plan into one memory I can reuse next week."
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory.manager import MemoryManager
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/summarize_to_memory.db")
user_id = "kyoto-traveler"

memory_manager = MemoryManager(
    db=db,
    model=OpenAIResponses(id="gpt-5-mini"),
    additional_instructions=(
        "Store concise, factual memories. Prefer one-sentence summaries over long transcripts."
    ),
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
    db=db,
    memory_manager=memory_manager,
    update_memory_on_run=True,
    enable_agentic_memory=True,
    instructions=[
        "You are a travel planning assistant.",
        "When asked to summarize, consolidate prior discussion into one clear memory brief.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = "kyoto_planning"

    print("=== Turn 1: destination and timing ===")
    agent.print_response(
        "I'm planning a trip to Kyoto in April.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )

    print("\n=== Turn 2: interests ===")
    agent.print_response(
        "I want temples, tea houses, and one day trip to Nara.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )

    print("\n=== Turn 3: consolidate into one memory ===")
    agent.print_response(
        "Summarize our trip plan into one memory I can reuse next week.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )

    print("\n=== Stored memories (summarized facts) ===")
    for memory in agent.get_user_memories(user_id=user_id):
        print(f"- {memory.memory}")