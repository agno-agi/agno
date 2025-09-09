"""Run `pip install openai agno memory_profiler` to install dependencies."""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.eval.performance import PerformanceEval
from agno.models.openai import OpenAIChat

# Memory creation requires a db to be provided
db = SqliteDb(db_file="tmp/memory.db")


def run_agent():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        system_message="Be concise, reply with one sentence.",
        db=db,
        enable_user_memories=True,
    )

    response = agent.run("My name is Tom! I'm 25 years old and I live in New York.")
    print(f"Agent response: {response.content}")

    return response


response_with_memory_updates_perf = PerformanceEval(
    name="Memory Updates Performance",
    func=run_agent,
    num_iterations=5,
    warmup_runs=0,
)

if __name__ == "__main__":
    response_with_memory_updates_perf.run(print_results=True, print_summary=True)
