"""Using AccuracyEval as a team post-hook.

Attaching evals to teams allows evaluation of the entire team's output.
"""

from agno.db.sqlite import SqliteDb
from agno.eval.accuracy import AccuracyEval
from agno.models.openai import OpenAIChat
from agno.team import Team

db = SqliteDb(db_file="evals.db")

# Create eval for team
accuracy_eval = AccuracyEval(
    input="What is the capital of France?",
    expected_output="Paris",
    db=db,
    # print_results=True,  # Print eval results when it runs as a hook
    # print_summary=True,
    telemetry=False,
)

# Attach eval to team
team = Team(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    members=[],
    post_hooks=[accuracy_eval],
    markdown=True,
    telemetry=False,
)

result = team.run("What is the capital of France?")

print(f"Team run ID: {result.run_id}")
print(f"Team response: {result.content}")

evals = db.get_eval_runs(eval_id=accuracy_eval.eval_id)
print(f"Eval parent_run_id: {evals[0].parent_run_id}")
print(f"Average Score: {evals[0].eval_data.get('avg_score', 'N/A')}/10")
