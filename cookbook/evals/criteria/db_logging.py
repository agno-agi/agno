"""Example showing how to store evaluation results in the database."""

from typing import Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.eval.criteria import CriteriaEval, CriteriaResult
from agno.models.openai import OpenAIChat

# Setup the database
db = SqliteDb(db_file="tmp/criteria_evals.db", eval_table="eval_runs_cookbook")

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    instructions="Provide clear and professional answers.",
    db=db,
)

response = agent.run("What are the benefits of cloud computing?")

evaluation = CriteriaEval(
    db=db,  # Pass the database to the evaluation. Results will be stored in the database.
    name="Cloud Computing Response Quality",
    model=OpenAIChat(id="gpt-4o-mini"),
    criteria="Response should be accurate, comprehensive, and well-structured",
    threshold=7,
    additional_guidelines=[
        "Include at least 3 specific benefits",
        "Use clear language",
    ],
)

result: Optional[CriteriaResult] = evaluation.run(
    input="What are the benefits of cloud computing?",
    output=str(response.content),
    print_results=True,
)
assert result is not None, "Evaluation should return a result"
