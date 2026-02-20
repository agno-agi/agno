"""
Decision Logs: Basic Usage
==========================

This example demonstrates how to use DecisionLogStore to record
and retrieve agent decisions.

DecisionLogStore is useful for:
- Auditing agent behavior
- Debugging unexpected outcomes
- Learning from past decisions
- Building feedback loops

Run:
    .venvs/demo/bin/python cookbook/08_learning/09_decision_logs/01_basic_decision_log.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import DecisionLogConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# Database connection
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
# Create an agent with decision logging
# AGENTIC mode: Agent explicitly logs decisions via the log_decision tool
agent = Agent(
    id="decision-logger",
    name="Decision Logger",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    learning=LearningMachine(
        decision_log=DecisionLogConfig(
            mode=LearningMode.AGENTIC,
            enable_agent_tools=True,
            agent_can_save=True,
            agent_can_search=True,
        ),
    ),
    instructions=[
        "You are a helpful assistant that logs important decisions.",
        "When you make a significant choice (like selecting a tool, choosing a response style, or deciding to ask for clarification), use the log_decision tool to record it.",
        "Include your reasoning and any alternatives you considered.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Test: Ask the agent to make a decision
    print("=== Test 1: Agent logs a decision ===\n")
    agent.print_response(
        "I need help choosing between Python and JavaScript for a web scraping project. What would you recommend?",
        session_id="session-001",
    )

    # View logged decisions
    print("\n=== Decisions Logged ===\n")
    decision_store = agent.learning_machine.decision_log_store
    if decision_store:
        decision_store.print(agent_id="decision-logger", limit=5)
