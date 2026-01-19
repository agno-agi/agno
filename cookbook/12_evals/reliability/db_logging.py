"""Example showing how to store evaluation results in the database."""

from typing import Optional

from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.eval.reliability import ReliabilityEval, ReliabilityResult
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput
from agno.tools.calculator import CalculatorTools

# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5432/ai"
db = PostgresDb(db_url=db_url, eval_table="eval_runs")


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[CalculatorTools()],
)
response: RunOutput = agent.run("What is 10!?")

evaluation = ReliabilityEval(
    db=db,  # Pass the database to the evaluation. Results will be stored in the database.
    name="Tool Call Reliability",
    agent_response=response,
    expected_tool_calls=["factorial"],
)
result: Optional[ReliabilityResult] = evaluation.run(print_results=True)
