"""Using PerformanceEval as a team post-hook.

Performance evals measure execution time and can be attached to teams
to automatically benchmark each team run.
"""

from agno.db.sqlite import SqliteDb
from agno.eval.performance import PerformanceEval
from agno.models.openai import OpenAIChat
from agno.team import Team


def sample_benchmark():
    """Function to benchmark"""
    return sum(range(10000))


db = SqliteDb(db_file="evals.db")

# Create performance eval as hook
performance_eval = PerformanceEval(
    func=sample_benchmark,
    db=db,
    # print_results=True,  # Print eval results when it runs as a hook
    # print_summary=True,
    telemetry=False,
)

# Attach to team
team = Team(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    members=[],
    post_hooks=[performance_eval],
    markdown=True,
    telemetry=False,
)

result = team.run("Hello")

print(f"Team run ID: {result.run_id}")
print(f"Team response: {result.content}")

evals = db.get_eval_runs(eval_id=performance_eval.eval_id)
print(f"Eval parent_run_id: {evals[0].parent_run_id}")
result_data = evals[0].eval_data.get("result", {})
print(f"Average Runtime: {result_data.get('avg_run_time', 'N/A')}s")
