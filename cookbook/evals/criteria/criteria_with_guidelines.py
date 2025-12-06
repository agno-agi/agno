"""CriteriaEval with additional guidelines and context."""

from typing import Optional

from agno.agent import Agent
from agno.eval.criteria import CriteriaEval, CriteriaResult
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a Tesla Model 3 product specialist. Provide accurate specifications with proper units.",
)

response = agent.run("What is the maximum speed of the Tesla Model 3?")

evaluation = CriteriaEval(
    name="Product Info Accuracy",
    model=OpenAIChat(id="gpt-4o-mini"),
    criteria="Response should match specifications",
    threshold=8,
    additional_guidelines=[
        "Must include specific numbers",
        "Must use proper units (mph, km/h, etc.)",
    ],
    additional_context="Product specs: Tesla Model 3 - approximately 140 mph (225 km/h)",
)

result: Optional[CriteriaResult] = evaluation.run(
    input="What is the maximum speed?",
    output=str(response.content),
    print_results=True,
)
assert result is not None, "Evaluation should return a result"
