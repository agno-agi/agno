"""
Performance Evaluation with Database Logging
============================================

Demonstrates storing performance evaluation results in PostgreSQL.
"""

from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.eval.performance import PerformanceEval
from agno.models.openai import OpenAIChat


# ---------------------------------------------------------------------------
# Create Benchmark Function
# ---------------------------------------------------------------------------
def run_agent():
    agent = Agent(
        model=OpenAIChat(id="gpt-5.2"),
        system_message="Be concise, reply with one sentence.",
    )
    response = agent.run("What is the capital of France?")
    print(response.content)
    return response


# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5432/ai"
db = PostgresDb(db_url=db_url, eval_table="eval_runs_cookbook")

# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
simple_response_perf = PerformanceEval(
    db=db,
    name="Simple Performance Evaluation",
    func=run_agent,
    num_iterations=1,
    warmup_runs=0,
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    simple_response_perf.run(print_results=True, print_summary=True)
