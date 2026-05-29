"""
Team Agent-as-Judge Evaluation
==============================

Demonstrates response quality evaluation for team outputs.
"""

from typing import Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.eval.agent_as_judge import AgentAsJudgeEval, AgentAsJudgeResult
from agno.models.openai import OpenAIChat
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/agent_as_judge_team.db")

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
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
    db=db,
)

# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
evaluation = AgentAsJudgeEval(
    name="Team Response Quality",
    model=OpenAIChat(id="gpt-5.2"),
    criteria="Response should be well-researched, clear, and comprehensive with good flow",
    scoring_strategy="binary",
    db=db,
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    response = research_team.run("Explain quantum computing")
    result: Optional[AgentAsJudgeResult] = evaluation.run(
        input="Explain quantum computing",
        output=str(response.content),
        print_results=True,
        print_summary=True,
    )
    assert result is not None, "Evaluation should return a result"

    print("Database Results:")
    eval_runs = db.get_eval_runs()
    print(f"Total evaluations stored: {len(eval_runs)}")
    if eval_runs:
        latest = eval_runs[-1]
        print(f"Eval ID: {latest.run_id}")
        print(f"Team: {research_team.name}")
