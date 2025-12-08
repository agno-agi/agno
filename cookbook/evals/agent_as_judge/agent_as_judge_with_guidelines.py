"""AgentAsJudgeEval with additional guidelines."""

from typing import Optional

from agno.agent import Agent
from agno.eval.agent_as_judge import AgentAsJudgeEval, AgentAsJudgeResult
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a Tesla Model 3 product specialist. Provide detailed and helpful specifications.",
)

response = agent.run("What is the maximum speed of the Tesla Model 3?")

evaluation = AgentAsJudgeEval(
    name="Product Info Quality",
    model=OpenAIChat(id="gpt-4o-mini"),
    criteria="Response should be informative, well-formatted, and accurate for product specifications",
    threshold=8,
    additional_guidelines=[
        "Must include specific numbers with proper units (mph, km/h, etc.)",
        "Should provide context for different model variants if applicable",
        "Information should be technically accurate and complete",
    ],
)

result: Optional[AgentAsJudgeResult] = evaluation.run(
    input="What is the maximum speed?",
    output=str(response.content),
    print_results=True,
)
assert result is not None, "Evaluation should return a result"
