"""
Tool-Enabled Accuracy Evaluation
================================

Demonstrates accuracy evaluation for an agent using calculator tools.
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
    name="Tools Evaluation",
    model=OpenAIResponses(id="gpt-5.6-terra"),
    agent=Agent(
        model=OpenAIResponses(id="gpt-5.2"),
        tools=[CalculatorTools()],
    ),
    input="What is 10!?",
    expected_output="3628800",
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    result: Optional[AccuracyResult] = evaluation.run(print_results=True)
    assert result is not None and result.avg_score >= 8
