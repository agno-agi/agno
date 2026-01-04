"""
Memory V2 Agentic - Agent-Controlled Memory Tools
==================================================
This example shows how to give your agent memory tools to manage user info.
The agent decides when to save, update, or delete memory via tool calls.

Different from background memory (01_background_memory.py), agentic memory
gives the agent explicit tools. More efficient, but may miss implicit info.

Key concepts:
- enable_agentic_memory_v2: Agent gets save/delete memory tools
- Natural commands: "remember that...", "update my...", "forget that..."
- User has explicit control over what gets saved

Example prompts to try:
- "Remember that I prefer TypeScript over JavaScript"
- "Update my role - I'm now a senior engineer"
- "Forget my previous project"
"""

import json

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from rich import print_json

# ============================================================================
# Storage Configuration
# ============================================================================
agent_db = SqliteDb(db_file="tmp/user_memory.db")

# ============================================================================
# User Configuration
# ============================================================================
user_id = "sarah"

# ============================================================================
# Create the Agent
# ============================================================================
agent = Agent(
    name="Memory Manager Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=agent_db,
    enable_agentic_memory_v2=True,
    markdown=True,
)

# ============================================================================
# Run the Agent
# ============================================================================
if __name__ == "__main__":
    # Show existing memory if any
    existing = agent.get_user_memory_v2(user_id)
    if existing:
        print("Existing profile:")
        print_json(json.dumps(existing.to_dict()))
        print()

    # Explicit save command
    agent.print_response(
        "Please remember that I prefer using Pydantic for data validation in all my APIs.",
        user_id=user_id,
        stream=True,
    )

    # Explicit update command
    agent.print_response(
        "Actually, I've been promoted. Update my role - I'm now a Staff Engineer.",
        user_id=user_id,
        stream=True,
    )

    # Explicit forget command
    agent.print_response(
        "Forget that I work on the payment service. I've moved to the authentication team.",
        user_id=user_id,
        stream=True,
    )

    # Add new context
    agent.print_response(
        "Add to my context: I'm implementing OAuth2 and OpenID Connect using authlib.",
        user_id=user_id,
        stream=True,
    )

    # Verify agent remembers correctly
    agent.print_response(
        "What's my current role and what project am I working on?",
        user_id=user_id,
        stream=True,
    )

    # View final memory state
    print("\n" + "=" * 60)
    print("Final Memory State")
    print("=" * 60)

    user = agent.get_user_memory_v2(user_id)
    if user:
        print_json(json.dumps(user.to_dict()))

# ============================================================================
# More Examples
# ============================================================================
"""
Common memory commands:

Save:
- "Remember that I..."
- "Save my preference for..."
- "Note that I work on..."

Update:
- "Update my role to..."
- "Change my company to..."
- "I've switched to..."

Delete:
- "Forget that I..."
- "Remove my..."
- "I no longer work on..."

Query:
- "What do you know about me?"
- "What's my current role?"
- "What are my preferences?"
"""
