"""CriteriaEval as pre-hook example."""

from agno.agent import Agent
from agno.eval.criteria import CriteriaEval
from agno.models.openai import OpenAIChat

criteria_eval = CriteriaEval(
    name="Input Quality Check",
    model=OpenAIChat(id="gpt-4o-mini"),
    criteria="Input should be clear, specific, and well-formed",
    threshold=6,
    print_results=True,
    print_summary=True,
    num_iterations=1,
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    instructions="Provide helpful and accurate answers.",
    pre_hooks=[criteria_eval],
)

response = agent.run("What is the capital of France?")
print(response.content)
