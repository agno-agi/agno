"""CriteriaEval with agents using tools."""

from typing import Optional

from agno.agent import Agent
from agno.eval.criteria import CriteriaEval, CriteriaResult
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[CalculatorTools()],
    instructions="Use the calculator tools to solve math problems. Show your calculation steps clearly.",
)

response = agent.run("What is 15 * 23 + 47?")

evaluation = CriteriaEval(
    name="Calculator Tool Usage",
    model=OpenAIChat(id="gpt-4o-mini"),
    criteria="Response should be accurate and show the calculation process",
    threshold=7,
)

result: Optional[CriteriaResult] = evaluation.run(
    input="What is 15 * 23 + 47?",
    output=str(response.content),
    print_results=True,
)
assert result is not None, "Evaluation should return a result"
