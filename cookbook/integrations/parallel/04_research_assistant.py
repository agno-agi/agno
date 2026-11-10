"""
Parallel Research Assistant - Persistent, Multi-API Agent
=========================================================

A research assistant you can come back to. It combines all of Parallel's
agent APIs (Search, Extract, Task) with Agno persistence: a SQLite-backed
session, conversation history, and user memory.

Ask a question, then a follow-up - the assistant remembers what you are
working on and what it already found.

Prerequisites:
- pip install parallel-web
- export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# ---------------------------------------------------------------------------
# Setup - persistence and tools
# ---------------------------------------------------------------------------
# SqliteDb gives the assistant a place to store sessions and memories.
db = SqliteDb(db_file="tmp/parallel_assistant.db")

# Search + Extract + Task in a single toolkit.
research_tools = ParallelTools(
    enable_search=True,
    enable_extract=True,
    enable_task=True,
    default_processor="base",
)

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
assistant = Agent(
    name="Research Assistant",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[research_tools],
    db=db,
    add_history_to_context=True,
    num_history_runs=5,
    update_memory_on_run=True,
    markdown=True,
    instructions=[
        "You are a research assistant.",
        "Use Search for quick facts, Extract to read specific URLs, and the "
        "Task API for deep research that needs citations.",
        "Remember what the user is researching across the conversation.",
    ],
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    user_id = "researcher@example.com"
    session_id = "parallel-research-session"

    # First turn - establish the topic.
    assistant.print_response(
        "I'm evaluating web-research APIs for an agent we're building. "
        "Start by finding the main options.",
        stream=True,
        user_id=user_id,
        session_id=session_id,
    )

    # Follow-up - the assistant remembers the context from the first turn.
    assistant.print_response(
        "Of those, which support deep research with citations?",
        stream=True,
        user_id=user_id,
        session_id=session_id,
    )
