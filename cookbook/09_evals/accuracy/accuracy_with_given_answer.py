"""
Given Answer Accuracy Evaluation
================================

Demonstrates accuracy evaluation for a provided answer string.
"""

from typing import Optional

from agno.eval.accuracy import AccuracyEval, AccuracyResult
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
evaluation = AccuracyEval(
    name="Given Answer Evaluation",
    model=OpenAIChat(id="o4-mini"),
    input="What is 10*5 then to the power of 2? do it step by step",
    expected_output="2500",
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    result_with_given_answer: Optional[AccuracyResult] = evaluation.run_with_output(
        output="2500", print_results=True
    )
    assert (
        result_with_given_answer is not None and result_with_given_answer.avg_score >= 8
    )
