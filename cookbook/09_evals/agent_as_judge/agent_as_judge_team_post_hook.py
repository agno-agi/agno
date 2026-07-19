"""
Team Post-Hook Agent-as-Judge Evaluation
========================================

Demonstrates a post-hook judge running on team responses.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.eval.agent_as_judge import AgentAsJudgeEval
from agno.models.openai import OpenAIChat
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/agent_as_judge_team_post_hook.db")

# ---------------------------------------------------------------------------
# Create Team and Evaluation Hook
# ---------------------------------------------------------------------------
agent_as_judge_eval = AgentAsJudgeEval(
    name="Team Response Quality",
    model=OpenAIChat(id="gpt-5.2"),
    criteria="Response should be well-researched, clear, comprehensive, and show good collaboration between team members",
    scoring_strategy="numeric",
    threshold=7,
    db=db,
)
researcher = Agent(
    name="Researcher",
    role="Research and gather information",
    model=OpenAIChat(id="gpt-4o"),
)
writer = Agent(
    name="Writer",
    role="Write clear and concise summaries",
    model=OpenAIChat(id="gpt-4o"),
)
research_team = Team(
    name="Research Team",
    model=OpenAIChat("gpt-4o"),
    members=[researcher, writer],
    instructions=["First research the topic thoroughly, then write a clear summary."],
    post_hooks=[agent_as_judge_eval],
    db=db,
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    response = research_team.run("Explain quantum computing")
    print(response.content)

    print("Evaluation Results:")
    eval_runs = db.get_eval_runs()
    if eval_runs:
        latest = eval_runs[-1]
        if latest.eval_data and "results" in latest.eval_data:
            result = latest.eval_data["results"][0]
            print(f"Score: {result.get('score', 'N/A')}/10")
            print(f"Status: {'PASSED' if result.get('passed') else 'FAILED'}")
            print(f"Reason: {result.get('reason', 'N/A')[:200]}...")
