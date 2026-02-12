"""
Memory Update Performance Evaluation
====================================

Demonstrates measuring performance when memory updates are enabled.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.eval.performance import PerformanceEval
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/memory.db")


# ---------------------------------------------------------------------------
# Create Benchmark Function
# ---------------------------------------------------------------------------
def run_agent():
    agent = Agent(
        model=OpenAIChat(id="gpt-5.2"),
        system_message="Be concise, reply with one sentence.",
        db=db,
        update_memory_on_run=True,
    )

    response = agent.run("My name is Tom! I'm 25 years old and I live in New York.")
    print(f"Agent response: {response.content}")

    return response


# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
response_with_memory_updates_perf = PerformanceEval(
    name="Memory Updates Performance",
    func=run_agent,
    num_iterations=5,
    warmup_runs=0,
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    response_with_memory_updates_perf.run(print_results=True, print_summary=True)
