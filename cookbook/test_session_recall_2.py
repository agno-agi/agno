"""Test session recall - Phase 2: Test searching across sessions"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

# Use the SAME database from previous test
db = SqliteDb(db_file="/tmp/test_session_recall.db")

# Create agent with a NEW session ID
agent = Agent(
    name="RecallTestAgent",
    model=OpenAIResponses(id="gpt-4o-mini"),
    db=db,
    read_chat_history=True,
    read_tool_call_history=True,
    search_past_sessions=True,
    session_id="test-recall-session-002",  # NEW SESSION
    instructions=[
        "You are a test agent for session recall.",
        "When asked to recall past messages, use get_chat_history.",
        "When asked about past sessions, use search_past_sessions and read_past_session.",
    ],
    debug_mode=True,
)

print("=" * 60)
print("NEW SESSION: Testing search_past_sessions across sessions")
print("=" * 60)

# Test 1: Search for past sessions
response1 = agent.run(
    "Use search_past_sessions to see what other sessions I've had before."
)
print(f"\nSearch Response: {response1.content}\n")

# Test 2: Read a specific past session
response2 = agent.run(
    "Use read_past_session to read the full conversation from session test-recall-session-001"
)
print(f"\nRead Response: {response2.content}\n")

# Test 3: Ask about content from the past session
response3 = agent.run(
    "Based on what you read from the past session, what was the secret code mentioned?"
)
print(f"\nRecall Response: {response3.content}\n")

print("=" * 60)
print("TEST COMPLETE")
print("=" * 60)
