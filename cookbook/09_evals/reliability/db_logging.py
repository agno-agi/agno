"""
Reliability Evaluation with Database Logging
============================================

Demonstrates storing reliability evaluation results in PostgreSQL.
"""

from typing import Optional

from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.eval.reliability import ReliabilityEval, ReliabilityResult
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput
from agno.tools.calculator import CalculatorTools

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5432/ai"
db = PostgresDb(db_url=db_url, eval_table="eval_runs")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(id="gpt-5.2"),
    tools=[CalculatorTools()],
)

# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    response: RunOutput = agent.run("What is 10!?")
    evaluation = ReliabilityEval(
        db=db,
        name="Tool Call Reliability",
        agent_response=response,
        expected_tool_calls=["factorial"],
    )
    result: Optional[ReliabilityResult] = evaluation.run(print_results=True)
    if result:
        result.assert_passed()
