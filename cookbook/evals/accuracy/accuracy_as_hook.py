"""Using AccuracyEval as an agent post-hook.

When attached as a post_hook, the eval runs automatically after each agent execution
and stores results in the database with parent linkage.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.eval.accuracy import AccuracyEval
from agno.models.openai import OpenAIChat

# Setup database
db = SqliteDb(db_file="evals.db")

# Create eval that will run as a hook
accuracy_eval = AccuracyEval(
    input="What is 2+2?",
    expected_output="4",
    db=db,
    # print_results=True,  # Print eval results when it runs as a hook
    # print_summary=True,
    telemetry=False,
)

# Attach eval to agent as post_hook
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    post_hooks=[accuracy_eval],
    markdown=True,
    telemetry=False,
)

# Run agent - eval executes automatically after
result = agent.run("What is 2+2?")

print(f"Agent run ID: {result.run_id}")
print(f"Agent response: {result.content}")

evals = db.get_eval_runs(eval_id=accuracy_eval.eval_id)
print(f"Eval parent_run_id: {evals[0].parent_run_id}")
print(f"Average Score: {evals[0].eval_data.get('avg_score', 'N/A')}/10")
