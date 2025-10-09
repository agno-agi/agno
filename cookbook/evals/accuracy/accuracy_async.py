"""This example shows how to run an Accuracy evaluation asynchronously."""

import asyncio
from typing import Optional

from agno.agent import Agent
from agno.eval.accuracy import AccuracyEval, AccuracyResult
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools

evaluation = AccuracyEval(
    model=OpenAIChat(id="o4-mini"),
    agent=Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[CalculatorTools()],
    ),
    input="What is 10*5 then to the power of 2? do it step by step",
    expected_output="2500",
    additional_guidelines="Agent output should include the steps and the final answer.",
    num_iterations=3,
)

# Run the evaluation calling the arun method.
result: Optional[AccuracyResult] = asyncio.run(evaluation.arun(print_results=True))
assert result is not None and result.avg_score >= 8
