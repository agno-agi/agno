"""Run `pip install openai agno memory_profiler` to install dependencies."""

from agno.agent import Agent
from agno.eval.performance import PerformanceEval
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.openai import OpenAIChat

# Memory creation requires a db to be provided
memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")
memory = Memory(db=memory_db)


def run_agent():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        system_message="Be concise, reply with one sentence.",
        memory=memory,
        enable_user_memories=True,
        enable_session_summaries=True,
    )
    response = agent.run("My name is Tom! I'm 25 years old and I live in New York.")
    print(response.content)
    return response


response_with_memory_updates_perf = PerformanceEval(
    name="Memory Updates Performance", func=run_agent, num_iterations=5, warmup_runs=0
)

if __name__ == "__main__":
    response_with_memory_updates_perf.run(print_results=True, print_summary=True)
