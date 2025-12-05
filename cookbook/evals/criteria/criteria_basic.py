"""Basic CriteriaEval usage example."""

from typing import Optional

from agno.agent import Agent
from agno.eval.criteria import CriteriaEval, CriteriaResult
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    instructions="Provide clear and concise answers.",
)

response = agent.run("What is the capital of France?")

evaluation = CriteriaEval(
    name="Answer Quality",
    model=OpenAIChat(id="gpt-4o-mini"),
    criteria="Response should be accurate and concise",
    threshold=7,
    num_iterations=2,
)

result: Optional[CriteriaResult] = evaluation.run(
    input="What is the capital of France?",
    output=str(response.content),
    print_results=True,
    print_summary=True,
)
assert result is not None, "Evaluation should return a result"
