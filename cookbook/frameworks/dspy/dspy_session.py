"""
DSPy agent with session persistence.

Demonstrates multi-turn conversations where chat history is persisted
to Agno's DB. Each run is stored as a session with messages, so you
can resume conversations and see history in the AgentOS UI.

Requirements:
    pip install dspy

Usage:
    python cookbook/frameworks/dspy/dspy_session.py
"""

import dspy
from agno.agents.dspy import DSPyAgent
from agno.db.postgres import PostgresDb

# ----- Configure DSPy -----
lm = dspy.LM("openai/gpt-5.4")
dspy.configure(lm=lm)

# ----- Create agent with Postgres persistence -----
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

agent = DSPyAgent(
    name="DSPy Chat",
    program=dspy.ChainOfThought("question -> answer"),
    db=db,
)

SESSION_ID = "demo-session-1"

# Turn 1
agent.print_response(
    "What is quantum computing?",
    stream=True,
    session_id=SESSION_ID,
)

# Turn 2 — same session, history is persisted
agent.print_response(
    "How is it different from classical computing?",
    stream=True,
    session_id=SESSION_ID,
)

# Turn 3
agent.print_response(
    "What are some real-world applications?",
    stream=True,
    session_id=SESSION_ID,
)

print(f"\n--- Session {SESSION_ID} persisted to Postgres ---")
print("You can inspect the DB to see all runs and messages stored.")
