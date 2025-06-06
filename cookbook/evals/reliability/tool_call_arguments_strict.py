"""Example showing how to check if the Agent has made the expected tool calls with the expected arguments, using the ReliabilityEval class."""

from typing import Optional

from agno.agent import Agent
from agno.eval.reliability import ExpectedToolCall, ReliabilityEval, ReliabilityResult
from agno.models.openai import OpenAIChat
from agno.run.response import RunResponse
from agno.tools.calculator import CalculatorTools

# Define the Agent's expected tool calls
expected_tool_calls = [
    ExpectedToolCall(
        tool_name="factorial",
        tool_call_args={"number": 10},
    ),
]


def factorial():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[CalculatorTools(factorial=True)],
    )
    response: RunResponse = agent.run("What is 10!?")
    evaluation = ReliabilityEval(
        agent_response=response,
        expected_tool_calls=["factorial"],
        strict_args_check=True,  # Check if the arguments provided in the ExpectedToolCall are exactly equal to the used arguments
    )
    result: Optional[ReliabilityResult] = evaluation.run(print_results=True)
    result.assert_passed()


if __name__ == "__main__":
    factorial()
