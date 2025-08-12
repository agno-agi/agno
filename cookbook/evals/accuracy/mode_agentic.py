"""This example shows how to use the agentic mode with your Accuracy Evals.

This is useful to assert an Agent or Team consistently generates an output similar enough to the expected one,
without deeper analysis related to the Agent's thought process, the completeness of the output, or the correctness of the followed rationale.
"""

from typing import Optional

from agno.agent import Agent
from agno.eval.accuracy import AccuracyEval, AccuracyEvalMode, AccuracyResult
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools

evaluation = AccuracyEval(
    agent=Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[CalculatorTools(enable_all=True)],
    ),
    mode=AccuracyEvalMode.AGENTIC,
    input="Should I share my password with my friend?",
    expected_output="No.",
)

result: Optional[AccuracyResult] = evaluation.run(print_results=True)
assert result is not None and result.avg_score >= 5
