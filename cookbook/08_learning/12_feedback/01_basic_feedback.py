"""
Feedback: Basic Usage
=====================

This example demonstrates how to use FeedbackStore to record user
feedback on agent runs (positive/negative with a comment) and have the
agent learn from it.

FeedbackStore is useful for:
- Reviewing runs (positive/negative with an optional comment)
- Adapting agent behavior based on what users liked or disliked
- Building instruction-improvement loops on top of feedback patterns

Run:
    .venvs/demo/bin/python cookbook/08_learning/12_feedback/01_basic_feedback.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
# Feedback recorded on this agent's runs is injected into its future runs.
agent = Agent(
    id="feedback-agent",
    name="Feedback Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    learning=LearningMachine(feedback=True),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Test 1: First run, before any feedback
    print("=== Test 1: First run ===\n")
    run_output = agent.run("What is the population of Tokyo?", session_id="basic-1")
    print(run_output.content)

    # Test 2: A negative review with a comment
    print("\n=== Test 2: Record negative feedback ===\n")
    feedback_store = agent.learning_machine.feedback_store
    feedback = feedback_store.record(
        signal="negative",
        comment="Too verbose. Just give me the number, no history lesson.",
        run_id=run_output.run_id,
        session_id="basic-1",
        agent_id="feedback-agent",
        context=f"User input: What is the population of Tokyo?\nAgent response: {str(run_output.content)[:300]}",
    )
    print(f"Recorded: {feedback}")
    if feedback and feedback.learning:
        print(f"Distilled lesson: {feedback.learning}")

    # Test 3: Next run, the agent sees the feedback and adapts
    print("\n=== Test 3: Run again with feedback applied ===\n")
    run_output = agent.run("What is the population of Osaka?", session_id="basic-2")
    print(run_output.content)
