"""Example showing how to store evaluation results in the database."""

from typing import Optional

from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.eval.accuracy import AccuracyEval, AccuracyResult
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools

# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5432/ai"
db = PostgresDb(db_url=db_url, eval_table="eval_runs_cookbook")


evaluation = AccuracyEval(
    db=db,  # Pass the database to the evaluation. Results will be stored in the database.
    name="Calculator Evaluation",
    model=OpenAIChat(id="o4-mini"),
    agent=Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[CalculatorTools()],
    ),
    input="What is 10*5 then to the power of 2? do it step by step",
    expected_output="2500",
    additional_guidelines="Agent output should include the steps and the final answer.",
    num_iterations=1,
)

result: Optional[AccuracyResult] = evaluation.run(print_results=True)
assert result is not None and result.avg_score >= 8
