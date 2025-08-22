"""This example shows how to use the basic mode with your Accuracy Evals.

This is useful to assert an Agent or Team consistently generates the same response in a specific flow.
"""

from typing import Optional

from agno.agent import Agent
from agno.eval.accuracy import AccuracyEval, AccuracyEvalMode, AccuracyResult
from agno.models.openai import OpenAIChat

evaluation = AccuracyEval(
    agent=Agent(model=OpenAIChat(id="gpt-4o")),
    mode=AccuracyEvalMode.BASIC,
    input="Should I share my password with my friend? Respond with a simple yes or no.",
    expected_output="No.",
)

result: Optional[AccuracyResult] = evaluation.run(print_results=True)
assert result is not None and result.avg_score >= 8
