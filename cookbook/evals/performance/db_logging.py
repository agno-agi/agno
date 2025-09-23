"""Example showing how to store evaluation results in the database."""

from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.eval.performance import PerformanceEval
from agno.models.openai import OpenAIChat


# Simple function to run an agent which performance we will evaluate
def run_agent():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        system_message="Be concise, reply with one sentence.",
    )
    response = agent.run("What is the capital of France?")
    print(response.content)
    return response


# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5432/ai"
db = PostgresDb(db_url=db_url, eval_table="eval_runs_cookbook")

simple_response_perf = PerformanceEval(
    db=db,  # Pass the database to the evaluation. Results will be stored in the database.
    name="Simple Performance Evaluation",
    func=run_agent,
    num_iterations=1,
    warmup_runs=0,
)

if __name__ == "__main__":
    simple_response_perf.run(print_results=True, print_summary=True)
