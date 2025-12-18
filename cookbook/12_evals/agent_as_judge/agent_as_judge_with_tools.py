"""AgentAsJudgeEval with agents using tools."""

from typing import Optional

from agno.agent import Agent
from agno.eval.agent_as_judge import AgentAsJudgeEval, AgentAsJudgeResult
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[CalculatorTools()],
    instructions="Use the calculator tools to solve math problems. Explain your reasoning and show calculation steps clearly.",
)

response = agent.run("What is 15 * 23 + 47?")

evaluation = AgentAsJudgeEval(
    name="Calculator Tool Usage Quality",
    model=OpenAIChat(id="gpt-4o-mini"),
    criteria="Response should clearly explain the calculation process, show intermediate steps, and present the final answer in a user-friendly way",
    scoring_strategy="numeric",
    threshold=7,
)

result: Optional[AgentAsJudgeResult] = evaluation.run(
    input="What is 15 * 23 + 47?",
    output=str(response.content),
    print_results=True,
)
assert result is not None, "Evaluation should return a result"
