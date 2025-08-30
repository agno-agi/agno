"""
This example shows how to use a custom response model for your evaluator agent.

We recommend using our AccuracyAgentResponse class as response_model for the evaluator agent.
That will give you a full Accuracy result containing score averages and other relevant information.

However, if you want to use a custom response model or no response model at all, you can do that.
This is useful if you want to evaluate something specific and do not care about the full Accuracy result.
"""

from typing import Optional

from agno.agent import Agent
from agno.eval.accuracy import AccuracyEval, AccuracyResult
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools
from pydantic import BaseModel


# Simple custom response model
class ResponseModel(BaseModel):
    answer: str
    reason: str

    def __str__(self) -> str:
        return f"Answer: {self.answer}\nReason: {self.reason}"


# This is the Agent which answer will be evaluated.
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[CalculatorTools(enable_all=True)],
)

# This is the Agent that will perform the evaluation. We equip it with some Calculator tools to perform the evaluation.
evaluator_agent = Agent(
    instructions="You are a helpful assistant that evaluates the accuracy of a given Agent's answer.",
    model=OpenAIChat(id="o4-mini"),
    tools=[CalculatorTools(enable_all=True)],
    response_model=ResponseModel,
)

evaluation = AccuracyEval(
    agent=agent,
    evaluator_agent=evaluator_agent,
    input="A company's revenue grew by 15% in Q1, then decreased by 8% in Q2. If the Q2 revenue was $1,840,000, what was the original revenue before Q1?",
    expected_output="$1,739,130.43",
)

evaluation_result: Optional[AccuracyResult] = evaluation.run(print_results=True)
assert evaluation_result is not None

# You can check the evaluator Agent responses:
for result in evaluation_result.results:
    evalutor_agent_response = result.output
