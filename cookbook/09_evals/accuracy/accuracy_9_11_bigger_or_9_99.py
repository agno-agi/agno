"""
Comparison Accuracy Evaluation
==============================

Demonstrates accuracy evaluation for numeric comparison tasks.
"""

from typing import Optional

from agno.agent import Agent
from agno.eval.accuracy import AccuracyEval, AccuracyResult
from agno.models.openai import OpenAIResponses
from agno.tools.calculator import CalculatorTools

# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
evaluation = AccuracyEval(
    name="Comparison Evaluation",
    model=OpenAIResponses(id="gpt-5.6-terra"),
    agent=Agent(
        model=OpenAIResponses(id="gpt-5.6-luna"),
        tools=[CalculatorTools()],
        instructions="You must use the calculator tools for comparisons.",
    ),
    input="9.11 and 9.9 -- which is bigger?",
    expected_output="9.9",
    additional_guidelines="Its ok for the output to include additional text or information relevant to the comparison.",
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    result: Optional[AccuracyResult] = evaluation.run(print_results=True)
    assert result is not None and result.avg_score >= 8
