"""Using ReliabilityEval as a team post-hook.

Reliability evals verify expected tool calls and can be attached to teams
to automatically validate team behavior.
"""

from agno.db.sqlite import SqliteDb
from agno.eval.reliability import ReliabilityEval
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools.calculator import CalculatorTools

db = SqliteDb(db_file="evals.db")

# Create reliability eval as hook
reliability_eval = ReliabilityEval(
    expected_tool_calls=["add"],
    db=db,
    # print_results=True,  # Print eval results when it runs as a hook
    telemetry=False,
)

# Attach to team with tools
team = Team(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    members=[],
    post_hooks=[reliability_eval],
    tools=[CalculatorTools()],
    markdown=True,
    telemetry=False,
)

result = team.run("What is 5 + 3?")

print(f"Team run ID: {result.run_id}")
print(f"Team response: {result.content}")

evals = db.get_eval_runs(eval_id=reliability_eval.eval_id)
print(f"Eval parent_run_id: {evals[0].parent_run_id}")
print(f"Eval Status: {evals[0].eval_data.get('eval_status', 'N/A')}")
