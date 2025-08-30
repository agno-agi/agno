"""
This example shows how to use a custom evaluator agent to evaluate the accuracy of an agent.

The evaluator agent is a simple agent that uses the AccuracyAgentResponse response model.
"""

from typing import Optional

from agno.agent import Agent
from agno.eval.accuracy import AccuracyAgentResponse, AccuracyEval, AccuracyResult
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools

# This is the Agent which answer will be evaluated.
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[CalculatorTools(enable_all=True)],
)

# This is the agent we will use to perform the evaluation. We equip it with some Calculator tools to perform the evaluation.
evaluator_agent = Agent(
    model=OpenAIChat(id="o4-mini"),
    tools=[CalculatorTools(enable_all=True)],
    response_model=AccuracyAgentResponse,  # Use this response model for the evaluator agent
)

evaluation = AccuracyEval(
    agent=agent,
    evaluator_agent=evaluator_agent,
    input="A company's revenue grew by 15% in Q1, then decreased by 8% in Q2. If the Q2 revenue was $1,840,000, what was the original revenue before Q1?",
    expected_output="$1,739,130.43",
)

result: Optional[AccuracyResult] = evaluation.run(print_results=True)
assert result is not None and result.avg_score >= 8
