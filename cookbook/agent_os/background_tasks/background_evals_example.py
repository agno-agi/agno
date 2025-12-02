"""
Example: Per-Hook Background Control in AgentOS

This example demonstrates fine-grained control over which hooks run in background:
- Use @hook(run_in_background=True) for custom functions
- Set eval.run_in_background = True for eval instances
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.eval.accuracy import AccuracyEval
from agno.eval.reliability import ReliabilityEval
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools.calculator import CalculatorTools

# Setup database
db = SqliteDb(db_file="tmp/evals.db")

# AccuracyEval with run_in_background=True
accuracy_eval = AccuracyEval(
    input="What is 2+2?",
    expected_output="4",
    db=db,
    print_results=True,
    telemetry=False,
)
accuracy_eval.run_in_background = True  # Runs in background

# ReliabilityEval without background - runs synchronously
reliability_eval = ReliabilityEval(
    expected_tool_calls=["add"],
    db=db,
    print_results=True,
    telemetry=False,
)

# Create an agent with evals as background post-hooks
agent = Agent(
    id="math-agent",
    name="MathAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a helpful math assistant. Always use the Calculator tools you have.",
    tools=[CalculatorTools()],
    db=db,
    # Mixed hooks: some run in background, some sync
    post_hooks=[
        accuracy_eval,  # run_in_background=True
        reliability_eval,  # run_in_background=False (default)
    ],
    markdown=True,
    telemetry=False,
)

# Create AgentOS
agent_os = AgentOS(
    agents=[agent],
)

# Get the FastAPI app
app = agent_os.get_app()


# When you make a request to POST /agents/{agent_id}/runs:
# 1. Agent processes the request
# 2. Sync hooks run first (reliability_eval)
# 3. Response sent to user
# 4. Background hooks run after (accuracy_eval)

# curl -X POST http://localhost:7777/agents/math-agent/runs \
#   -F "message=What is 2+2?" \
#   -F "stream=false"

if __name__ == "__main__":
    agent_os.serve(app="background_evals_example:app", port=7777, reload=True)
