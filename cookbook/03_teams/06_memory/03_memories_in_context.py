"""
Memories in Context
===================

Demonstrates `add_memories_to_context` with team memory capture.
"""

from pprint import pprint

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory import MemoryManager
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_file = "tmp/team_memories.db"
team_db = SqliteDb(
    db_file=db_file, session_table="team_sessions", memory_table="team_memories"
)
memory_manager = MemoryManager(
    model=OpenAIResponses(id="gpt-5-mini"),
    db=team_db,
)


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
assistant_agent = Agent(
    name="Personal Assistant",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=[
        "Use recent memories to personalize responses.",
        "When unsure, ask for clarification.",
    ],
)


# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
personal_team = Team(
    name="Personal Memory Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[assistant_agent],
    db=team_db,
    memory_manager=memory_manager,
    update_memory_on_run=True,
    add_memories_to_context=True,
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    user_id = "jane.doe@example.com"

    personal_team.print_response(
        "My preferred coding language is Python and I like weekend hikes.",
        stream=True,
        user_id=user_id,
    )

    personal_team.print_response(
        "What do you know about my preferences?",
        stream=True,
        user_id=user_id,
    )

    memories = personal_team.get_user_memories(user_id=user_id)
    print("\nCaptured memories:")
    pprint(memories)
