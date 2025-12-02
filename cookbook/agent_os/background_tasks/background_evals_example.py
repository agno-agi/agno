"""
Example: Per-Hook Background Control in AgentOS

This example demonstrates fine-grained control over which hooks run in background:
- Set eval.run_in_background = True for eval instances
"""

from agno.agent import Agent
from agno.db.sqlite import AsyncSqliteDb
from agno.eval.performance import PerformanceEval
from agno.eval.reliability import ReliabilityEval
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools.calculator import CalculatorTools

# Setup database
db = AsyncSqliteDb(db_file="tmp/evals.db")


# Function to benchmark
async def count_to_100():
    import asyncio

    await asyncio.sleep(2)
    total = 0
    for i in range(1, 101):
        total += i
    return total


# PerformanceEval - runs in background
performance_eval = PerformanceEval(
    func=count_to_100,
    num_iterations=5,
    warmup_runs=2,
    db=db,
    print_results=False,
    print_summary=True,  # Just show summary
    telemetry=False,
)
performance_eval.run_in_background = True

# ReliabilityEval - runs synchronously (default)
reliability_eval = ReliabilityEval(
    expected_tool_calls=["add", "multiply", "divide"],
    db=db,
    print_results=True,
    telemetry=False,
)
# reliability_eval.run_in_background = True

agent = Agent(
    id="math-agent",
    name="MathAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a helpful math assistant. Always use the Calculator tools.",
    tools=[CalculatorTools()],
    db=db,
    post_hooks=[
        reliability_eval,  # run_in_background=False - runs first, blocks
        performance_eval,  # run_in_background=True - runs after response
    ],
    markdown=True,
    telemetry=False,
)

# Create AgentOS
agent_os = AgentOS(agents=[agent])
app = agent_os.get_app()

# Flow:
# 1. Agent processes request
# 2. Sync hooks run (reliability_eval)
# 3. Response sent to user
# 4. Background hooks run (performance_eval)

# curl -X POST http://localhost:7777/agents/math-agent/runs \
#   -F "message=What is 2+2?" -F "stream=false"

if __name__ == "__main__":
    agent_os.serve(app="background_evals_example:app", port=7777, reload=True)
