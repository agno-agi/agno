"""AgentAsJudgeEval as post-hook example."""

from agno.agent import Agent
from agno.eval.agent_as_judge import AgentAsJudgeEval
from agno.models.openai import OpenAIChat

agent_as_judge_eval = AgentAsJudgeEval(
    name="Response Quality Check",
    model=OpenAIChat(id="gpt-4o-mini"),
    criteria="Response should be professional, well-structured, and provide balanced perspectives",
    threshold=7,
    print_results=True,
    print_summary=True,
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    instructions="Provide professional and well-reasoned answers.",
    post_hooks=[agent_as_judge_eval],
)

response = agent.run("What are the benefits of renewable energy?")
print(response.content)
