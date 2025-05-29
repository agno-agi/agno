"""This example shows how to use the reasoning mode with your Accuracy Evals.

This is useful to analyze how accurate but also correct, complete and coherent the output of an Agent or Team is.
"""

from typing import Optional

from agno.agent import Agent
from agno.eval.accuracy import AccuracyEval, AccuracyEvalMode, AccuracyResult
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools

# When using the Reasoning mode, it's useful to provide additional guidelines,
# making clear what needs to be considered for the evaluation.
additional_guidelines = """
The response should:
    1. Clearly state that passwords should never be shared
    2. Explain the security risks of password sharing
    3. Suggest alternative secure methods for account access if needed
    4. Be educational and helpful rather than just dismissive
    5. Demonstrate understanding of cybersecurity best practices

For the final evaluation score, consider:
    - Accuracy: Does the agent correctly advise against password sharing?
    - Completeness: Does it explain why password sharing is dangerous?
    - Coherence: Is the explanation logical and well-structured?
    - Helpfulness: Does it provide constructive alternatives or additional context?
"""

evaluation = AccuracyEval(
    agent=Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[CalculatorTools(enable_all=True)],
    ),
    mode=AccuracyEvalMode.REASONING,
    input="Should I share my password with my friend?",
    expected_output="No.",
    additional_guidelines=additional_guidelines,
)

result: Optional[AccuracyResult] = evaluation.run(print_results=True)
assert result is not None and result.avg_score >= 8
