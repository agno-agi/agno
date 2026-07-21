"""
Feedback: Conversational Extraction
===================================

This example demonstrates feedback without any UI. The user expresses
feedback in the conversation itself ("too long, just give me the number")
and the agent records it automatically after the run, then adapts.

How it works:
- After each run, the feedback store analyzes the latest user message
- Praise, complaints, corrections, and redo requests are recorded as
  feedback with a distilled lesson
- Recent feedback is injected into future runs, even in new sessions

Run:
    .venvs/demo/bin/python cookbook/08_learning/11_feedback/02_conversational_feedback.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# Database connection
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
# Create an agent with feedback learning enabled. No UI, no endpoints:
# feedback expressed in the chat is extracted automatically after each run.
agent = Agent(
    id="conversational-feedback-agent",
    name="Conversational Feedback Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    learning=LearningMachine(feedback=True),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Test 1: The user asks, then complains in the same session
    print("=== Test 1: User gives feedback in the conversation ===\n")
    run_output = agent.run("What is the population of Tokyo?", session_id="session-001")
    print(run_output.content)

    run_output = agent.run(
        "Too long. Next time just give me the number, nothing else.",
        session_id="session-001",
    )
    print(run_output.content)

    # Test 2: The complaint was recorded as feedback automatically
    print("\n=== Test 2: Extracted feedback ===\n")
    feedback_store = agent.learning_machine.feedback_store
    for feedback in feedback_store.search(
        agent_id="conversational-feedback-agent", limit=5
    ):
        print(f"[{feedback.signal}] {feedback.comment}")
        if feedback.learning:
            print(f"  Lesson: {feedback.learning}")

    # Test 3: A brand new session starts already adapted
    print("\n=== Test 3: New session, agent adapted ===\n")
    run_output = agent.run("What is the population of Osaka?", session_id="session-002")
    print(run_output.content)
