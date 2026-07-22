"""
Shared Sessions: Multiple Users in One Session
===============================================

Demonstrates the `shared_sessions` feature that allows multiple users
to share a single session while maintaining per-user memory isolation.

Use Case:
- Group chat scenarios (Slack threads, Discord channels, team chats)
- Multiple users collaborating in the same conversation
- Each user's messages are part of shared history
- Each user's memories remain isolated

SECURITY WARNING:
-----------------
This feature is designed for use with authenticated interfaces (Slack, Discord, etc.)
where user identity is verified by the platform. For production use:

1. Always use with proper authentication (OAuth, JWT, etc.)
2. Never trust user-supplied user_id without verification
3. Consider using `hitl_owner_only=True` to restrict approvals to run owners

Run: .venvs/demo/bin/python cookbook/02_agents/05_state_and_session/shared_sessions_multiuser.py
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

db = SqliteDb(db_file="tmp/shared_session_demo.db")

agent = Agent(
    name="GroupChatBot",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions=[
        "You are a helpful assistant in a group chat.",
        "Multiple users may be talking to you in the same conversation.",
        "Address users by name when relevant.",
    ],
    # Enable shared sessions - all users share one session
    shared_sessions=True,
    add_history_to_context=True,
    num_history_runs=10,
    markdown=True,
)

# Simulate a group chat thread with multiple users
SHARED_SESSION_ID = "group-chat-thread-123"

print("=" * 60)
print("SHARED SESSIONS DEMO: Multiple Users, One Session")
print("=" * 60)
print()
print("Scenario: Alice, Bob, Charlie in a shared chat thread.")
print("All messages visible to all users (shared history).")
print()

# Alice starts the conversation
print("[Alice joins]")
agent.print_response(
    "Hi! I'm Alice. Can you help us plan a team lunch?",
    user_id="alice",
    session_id=SHARED_SESSION_ID,
    stream=True,
)

# Bob joins and adds to the conversation
print("\n[Bob joins]")
agent.print_response(
    "Hey, I'm Bob. I'm vegetarian, keep that in mind.",
    user_id="bob",
    session_id=SHARED_SESSION_ID,
    stream=True,
)

# Charlie joins
print("\n[Charlie joins]")
agent.print_response(
    "Charlie here! I love spicy food.",
    user_id="charlie",
    session_id=SHARED_SESSION_ID,
    stream=True,
)

# Alice asks for summary (tests shared context)
print("\n[Alice asks for summary]")
agent.print_response(
    "Summarize everyone's food preferences.",
    user_id="alice",
    session_id=SHARED_SESSION_ID,
    stream=True,
)

# Bob references Alice's earlier message (proves shared history)
print("\n[Bob references earlier context]")
agent.print_response(
    "What did Alice originally ask us to plan?",
    user_id="bob",
    session_id=SHARED_SESSION_ID,
    stream=True,
)

print()
print("=" * 60)
print("KEY POINTS:")
print("=" * 60)
print()
print("1. SHARED HISTORY: Bob could ask about Alice's message")
print("2. USER ATTRIBUTION: Each run has its own user_id")
print("3. SESSION OWNERSHIP: Alice 'owns' the session (first user)")
print("4. For Slack/Discord: use multi_user_threads=True")
print()
