"""
Decision Logs: ALWAYS Mode (Automatic Logging)
===============================================

This example demonstrates automatic decision logging where
tool calls are automatically recorded as decisions.

In ALWAYS mode, DecisionLogStore extracts decisions from:
- Tool calls (which tool was used)
- Other significant choices the agent makes

Run:
    .venvs/demo/bin/python cookbook/08_learning/09_decision_logs/02_decision_log_always.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import DecisionLogConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# Database connection
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
# Create an agent with automatic decision logging
# ALWAYS mode: Tool calls are automatically logged as decisions
agent = Agent(
    id="auto-decision-logger",
    name="Auto Decision Logger",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    learning=LearningMachine(
        decision_log=DecisionLogConfig(
            mode=LearningMode.ALWAYS,
        ),
    ),
    tools=[DuckDuckGoTools()],
    instructions=[
        "You are a helpful research assistant.",
        "Use web search to find current information when needed.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Test: Agent uses a tool (will be logged automatically)
    print("=== Test: Agent uses web search ===\n")
    agent.print_response(
        "What are the latest developments in AI agents?",
        session_id="session-002",
    )

    # View auto-logged decisions
    print("\n=== Auto-Logged Decisions ===\n")
    decision_store = agent.learning_machine.decision_log_store
    if decision_store:
        decision_store.print(agent_id="auto-decision-logger", limit=10)
