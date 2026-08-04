"""Test runs_limit flows correctly to PostgreSQL.

Run with: python cookbook/test_runs_limit_postgres.py

Requires: PostgreSQL running (./cookbook/scripts/run_pgvector.sh)
"""

import os
os.environ["AGNO_DEBUG"] = "true"

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses

# Connect to local Postgres (default from run_pgvector.sh)
db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    session_table="test_runs_limit_sessions",
    runs_table="test_runs_limit_runs",
)

SESSION_ID = "postgres-test-session-001"

print("=" * 60)
print("Testing runs_limit with PostgreSQL")
print("=" * 60)
print(f"  db.supports_runs_limit: {db.supports_runs_limit}")

# Create agent with bounded history
agent = Agent(
    model=OpenAIResponses(id="gpt-4o-mini"),
    add_history_to_context=True,
    num_history_runs=10,
    db=db,
    session_id=SESSION_ID,
)

print(f"  agent.num_history_runs: {agent.num_history_runs}")
print("=" * 60)

# Phase 1: Build up 5 runs
print("\nPhase 1: Running agent 5 times...")
for i in range(5):
    response = agent.run(f"Test message {i+1}")
    print(f"  Run {i+1} done")

# Phase 2: New agent, fresh DB read
print("\n" + "=" * 60)
print("Phase 2: New agent - fresh DB read with runs_limit=10")
print("=" * 60)

agent2 = Agent(
    model=OpenAIResponses(id="gpt-4o-mini"),
    add_history_to_context=True,
    num_history_runs=10,
    db=db,
    session_id=SESSION_ID,
)

print("\nRunning agent2 (should load only last 3 runs from DB):")
response = agent2.run("What did I say before?")

print(f"\nResponse: {response.content[:100]}...")

# Cleanup
print("\n" + "=" * 60)
print("Cleaning up test tables...")
try:
    from sqlalchemy import text
    with db.Session() as sess:
        sess.execute(text("DROP TABLE IF EXISTS test_runs_limit_runs CASCADE"))
        sess.execute(text("DROP TABLE IF EXISTS test_runs_limit_sessions CASCADE"))
        sess.commit()
    print("✓ Cleaned up test tables")
except Exception as e:
    print(f"Cleanup failed: {e}")

print("=" * 60)
print("Done!")
