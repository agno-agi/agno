"""
Feedback: Agentic Mode
======================

This example demonstrates AGENTIC mode. Instead of a background pass
extracting feedback after each run, the agent is given a record_feedback
tool and logs feedback itself, in the same turn it notices it.

AGENTIC vs ALWAYS:
- ALWAYS: a separate model pass extracts feedback after the run (no agent tool).
- AGENTIC: the agent calls record_feedback during the run when the user reacts.

Run:
    .venvs/demo/bin/python cookbook/08_learning/11_feedback/03_agentic_feedback.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import FeedbackConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# Database connection
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
# AGENTIC mode: the agent gets a record_feedback tool and decides when to log
# feedback the user expresses, instead of a background extraction pass.
agent = Agent(
    id="agentic-feedback-agent",
    name="Agentic Feedback Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    learning=LearningMachine(
        feedback=FeedbackConfig(mode=LearningMode.AGENTIC),
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Test 1: User reacts to a response; the agent logs it via the tool
    print("=== Test 1: User gives feedback, agent records it ===\n")
    agent.print_response("What is the population of Tokyo?", session_id="agentic-1")
    agent.print_response(
        "Too long. Next time just give me the number, nothing else.",
        session_id="agentic-1",
    )

    # Test 2: The agent recorded the feedback itself
    print("\n=== Test 2: Feedback the agent logged ===\n")
    feedback_store = agent.learning_machine.feedback_store
    feedback_store.print(agent_id="agentic-feedback-agent", limit=5)

    # Test 3: A brand new session starts already adapted
    print("\n=== Test 3: New session, agent adapted ===\n")
    agent.print_response("What is the population of Osaka?", session_id="agentic-2")
