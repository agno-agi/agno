"""Run `pip install openai agno` to install dependencies."""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.eval.performance import PerformanceEval
from agno.models.openai import OpenAIChat

db = SqliteDb(db_file="tmp/storage.db")


def run_agent():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        system_message="Be concise, reply with one sentence.",
        add_history_to_context=True,
    )
    response_1 = agent.run("What is the capital of France?")
    print(response_1.content)

    response_2 = agent.run("How many people live there?")
    print(response_2.content)

    return response_2.content


response_with_storage_perf = PerformanceEval(
    name="Storage Performance",
    func=run_agent,
    num_iterations=1,
    warmup_runs=0,
)

if __name__ == "__main__":
    response_with_storage_perf.run(print_results=True, print_summary=True)
