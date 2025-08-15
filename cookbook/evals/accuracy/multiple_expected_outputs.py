"""This example shows how to use multiple expected outputs with your Accuracy Evals.

This is useful when multiple Agent or Team outputs are valid in the same flow.
"""

from typing import Optional

from agno.agent import Agent
from agno.eval.accuracy import AccuracyEval, AccuracyResult
from agno.models.openai import OpenAIChat

# When multiple different outputs are valid, you can provide them as a list:
expected_output = ["Merge sort", "Heap sort", "Quick sort"]

evaluation = AccuracyEval(
    agent=Agent(model=OpenAIChat(id="gpt-4o")),
    input="Which sorting algorithm has O(n log n) average time complexity? Mention just one.",
    expected_output=expected_output,
)

# The evaluation will then check if the Agent's output matches any of the expected outputs.
result: Optional[AccuracyResult] = evaluation.run(print_results=True)
assert result is not None and result.avg_score >= 8
