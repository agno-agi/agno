"""
Accuracy Evaluation with Custom Evaluator Agent
================================================

Demonstrates accuracy evaluation using a custom evaluator agent.
"""

from typing import Optional

from agno.agent import Agent
from agno.eval.accuracy import AccuracyAgentResponse, AccuracyEval, AccuracyResult
from agno.models.openai import OpenAIResponses
from agno.tools.calculator import CalculatorTools

# ---------------------------------------------------------------------------
# Create Evaluator Agent
# ---------------------------------------------------------------------------
evaluator_agent = Agent(
    model=OpenAIResponses(id="gpt-5"),
    output_schema=AccuracyAgentResponse,
)

# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
evaluation = AccuracyEval(
    model=OpenAIResponses(id="gpt-5.6-terra"),
    agent=Agent(model=OpenAIResponses(id="gpt-5.2"), tools=[CalculatorTools()]),
    input="What is 10*5 then to the power of 2? do it step by step",
    expected_output="2500",
    evaluator_agent=evaluator_agent,
    additional_guidelines="Agent output should include the steps and the final answer.",
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    result: Optional[AccuracyResult] = evaluation.run(print_results=True)
    assert result is not None and result.avg_score >= 8
