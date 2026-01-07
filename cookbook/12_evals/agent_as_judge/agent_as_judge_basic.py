"""Basic AgentAsJudgeEval usage with numeric scoring (1-10) and on_fail callback."""

from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.eval.agent_as_judge import AgentAsJudgeEval, AgentAsJudgeEvaluation
from agno.models.openai import OpenAIChat


def on_evaluation_failure(evaluation: AgentAsJudgeEvaluation):
    """Callback triggered when evaluation fails (score < threshold)."""
    print(f"Evaluation failed - Score: {evaluation.score}/10")
    print(f"Reason: {evaluation.reason[:100]}...")


# Setup database to persist eval results
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a technical writer. Explain concepts clearly and concisely.",
    db=db,
)

response = agent.run("Explain what an API is")

evaluation = AgentAsJudgeEval(
    name="Explanation Quality",
    criteria="Explanation should be clear, beginner-friendly, and use simple language",
    scoring_strategy="numeric",  # Score 1-10
    threshold=7,  # Pass if score >= 7
    on_fail=on_evaluation_failure,
    db=db,
)

result = evaluation.run(
    input="Explain what an API is",
    output=str(response.content),
    print_results=True,
    print_summary=True,
)

# Query database for stored results
print("Database Results:")
eval_runs = db.get_eval_runs()
print(f"Total evaluations stored: {len(eval_runs)}")
if eval_runs:
    latest = eval_runs[-1]
    print(f"Eval ID: {latest.run_id}")
    print(f"Name: {latest.name}")
