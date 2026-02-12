"""
Guideline-Based Agent-as-Judge Evaluation
=========================================

Demonstrates agent-as-judge scoring with additional guidelines.
"""

from typing import Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.eval.agent_as_judge import AgentAsJudgeEval, AgentAsJudgeResult
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/agent_as_judge_guidelines.db")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a Tesla Model 3 product specialist. Provide detailed and helpful specifications.",
    db=db,
)

# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
evaluation = AgentAsJudgeEval(
    name="Product Info Quality",
    model=OpenAIChat(id="gpt-5.2"),
    criteria="Response should be informative, well-formatted, and accurate for product specifications",
    scoring_strategy="numeric",
    threshold=8,
    additional_guidelines=[
        "Must include specific numbers with proper units (mph, km/h, etc.)",
        "Should provide context for different model variants if applicable",
        "Information should be technically accurate and complete",
    ],
    db=db,
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    response = agent.run("What is the maximum speed of the Tesla Model 3?")
    result: Optional[AgentAsJudgeResult] = evaluation.run(
        input="What is the maximum speed?",
        output=str(response.content),
        print_results=True,
    )
    assert result is not None, "Evaluation should return a result"

    print("Database Results:")
    eval_runs = db.get_eval_runs()
    print(f"Total evaluations stored: {len(eval_runs)}")
    if eval_runs:
        latest = eval_runs[-1]
        print(f"Eval ID: {latest.run_id}")
        print(f"Additional guidelines used: {len(evaluation.additional_guidelines)}")
