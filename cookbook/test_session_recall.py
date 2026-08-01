"""Test session recall tools - can an agent access its own history?

This test:
1. Creates an agent with session recall tools enabled
2. Has a multi-turn conversation (builds up history)
3. Asks the agent to recall earlier parts of the conversation
4. Tests if it can search past sessions
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

# Use a persistent database so sessions survive across runs
db = SqliteDb(db_file="/tmp/test_session_recall.db")

agent = Agent(
    name="RecallTestAgent",
    model=OpenAIResponses(id="gpt-4o-mini"),
    db=db,
    # Enable the session recall tools
    read_chat_history=True,
    read_tool_call_history=True,
    search_past_sessions=True,
    # Use a fixed session ID so we build up history
    session_id="test-recall-session-001",
    instructions=[
        "You are a test agent for session recall.",
        "When asked to recall past messages, use get_chat_history.",
        "When asked about past sessions, use search_past_sessions.",
    ],
    debug_mode=True,
)

print("=" * 60)
print("PHASE 1: Building up conversation history")
print("=" * 60)

# Turn 1: Establish some facts
response1 = agent.run(
    "My favorite color is blue and I have 3 cats named Whiskers, Shadow, and Luna."
)
print(f"Turn 1 Response: {response1.content}\n")

# Turn 2: Add more context
response2 = agent.run(
    "I work as a software engineer at a company called TechCorp. I've been there for 5 years."
)
print(f"Turn 2 Response: {response2.content}\n")

# Turn 3: Add something specific
response3 = agent.run("The secret code is ALPHA-BRAVO-7749. Remember this for later.")
print(f"Turn 3 Response: {response3.content}\n")

print("=" * 60)
print("PHASE 2: Testing recall (agent should use get_chat_history)")
print("=" * 60)

# Now test if the agent can recall using the tool
response4 = agent.run(
    "What was the secret code I told you earlier? Use your get_chat_history tool to find it."
)
print(f"Turn 4 Response: {response4.content}\n")

# Test recall of other facts
response5 = agent.run("What are my cats' names? Check your chat history to be sure.")
print(f"Turn 5 Response: {response5.content}\n")

print("=" * 60)
print("PHASE 3: Testing search_past_sessions")
print("=" * 60)

# Test searching past sessions
response6 = agent.run(
    "Use the search_past_sessions tool to see what other sessions exist."
)
print(f"Turn 6 Response: {response6.content}\n")

print("=" * 60)
print("PHASE 4: Check what tools were actually called")
print("=" * 60)

# Check tool calls
response7 = agent.run(
    "Use get_tool_call_history to show me what tools you've called in this session."
)
print(f"Turn 7 Response: {response7.content}\n")

print("=" * 60)
print("TEST COMPLETE")
print("=" * 60)
