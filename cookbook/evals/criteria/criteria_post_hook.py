"""CriteriaEval as post-hook example."""

from agno.agent import Agent
from agno.eval.criteria import CriteriaEval
from agno.models.openai import OpenAIChat

criteria_eval = CriteriaEval(
    name="Response Quality Check",
    model=OpenAIChat(id="gpt-4o-mini"),
    criteria="Response should be professional and accurate",
    threshold=7,
    print_results=True,
    print_summary=True,
    num_iterations=2,
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    instructions="Provide professional and accurate answers.",
    post_hooks=[criteria_eval],
)

response = agent.run("What are the benefits of renewable energy?")
print(response.content)
