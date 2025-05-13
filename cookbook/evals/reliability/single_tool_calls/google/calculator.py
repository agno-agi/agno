from typing import Optional

from agno.agent import Agent
from agno.eval.reliability import ReliabilityEval, ReliabilityResult
from agno.models.google import Gemini
from agno.run.response import RunResponse
from agno.tools.calculator import CalculatorTools


def factorial():
    model = Gemini(id="gemini-1.5-flash")
    agent = Agent(model=model, tools=[CalculatorTools(factorial=True)])
    response: RunResponse = agent.run("What is 10!?")

    evaluation = ReliabilityEval(
        agent_response=response, expected_tool_calls=["factorial"]
    )
    result: Optional[ReliabilityResult] = evaluation.run(print_results=True)
    result.assert_passed()


if __name__ == "__main__":
    factorial()
