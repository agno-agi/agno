"""
Memory V2 Multi-User - Isolated Memory for Multiple Users
==========================================================
This example shows how a single agent serves multiple users with isolated memory.
Each user has their own memory profile, enabling personalized responses.

Different from shared memory (where agents share), this shows user isolation
where the same agent serves many users without mixing their data.

Key concepts:
- user_id: Unique identifier for each user
- Memory isolation: Users don't see each other's data
- Personalization: Same question gets different answers based on user context

Example prompts to try:
- Different users describe different interests
- Ask "What should I do this weekend?" to each user
- Each gets personalized recommendations
"""

import asyncio
import json

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from rich import print_json

# ============================================================================
# Storage Configuration
# ============================================================================
agent_db = SqliteDb(db_file="tmp/multi_user_memory.db")

# ============================================================================
# User Configuration
# ============================================================================
user_mark = "mark@example.com"
user_john = "john@example.com"
user_jane = "jane@example.com"

# ============================================================================
# Create the Agent
# ============================================================================
agent = Agent(
    name="Multi-User Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=agent_db,
    update_memory_on_run=True,
    markdown=True,
)


# ============================================================================
# User Conversations
# ============================================================================
async def run_conversations():
    # Mark - anime and gaming enthusiast
    await agent.aprint_response(
        "My name is Mark Gonzales and I like anime and video games.",
        user_id=user_mark,
    )
    await agent.aprint_response(
        "I also enjoy reading manga and playing RPGs.",
        user_id=user_mark,
    )

    # John - outdoor enthusiast
    await agent.aprint_response(
        "Hi my name is John Doe.",
        user_id=user_john,
    )
    await agent.aprint_response(
        "I'm planning to hike this weekend. I love mountain trails.",
        user_id=user_john,
    )

    # Jane - fitness enthusiast
    await agent.aprint_response(
        "Hi my name is Jane Smith.",
        user_id=user_jane,
    )
    await agent.aprint_response(
        "I'm going to the gym tomorrow. I do CrossFit.",
        user_id=user_jane,
    )

    # Personalized recommendation - agent uses each user's memory
    await agent.aprint_response(
        "What do you suggest I do this weekend?",
        user_id=user_mark,
    )


# ============================================================================
# Run the Agent
# ============================================================================
if __name__ == "__main__":
    asyncio.run(run_conversations())

    print("\n" + "=" * 60)
    print("User Profiles")
    print("=" * 60)

    print("\nMark's profile:")
    mark = agent.get_user_memory_v2(user_mark)
    if mark:
        print_json(json.dumps(mark.to_dict()))

    print("\nJohn's profile:")
    john = agent.get_user_memory_v2(user_john)
    if john:
        print_json(json.dumps(john.to_dict()))

    print("\nJane's profile:")
    jane = agent.get_user_memory_v2(user_jane)
    if jane:
        print_json(json.dumps(jane.to_dict()))

# ============================================================================
# More Examples
# ============================================================================
"""
User ID best practices:

1. Use stable identifiers:
   - Email: "user@example.com"
   - UUID: "550e8400-e29b-41d4-a716-446655440000"
   - Internal ID: "user_12345"

2. Don't use:
   - Session IDs (change per session)
   - IP addresses (can change)
   - Anonymous tokens (can't persist)

3. For multi-tenant apps:
   - Include tenant: "tenant_abc:user_123"
   - Or use separate databases per tenant

Memory isolation is automatic - users can't access each other's data.
"""
