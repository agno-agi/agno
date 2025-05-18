from typing import Optional

from agno.agent import Agent
from agno.eval.accuracy import AccuracyEval, AccuracyResult
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools

evaluation = AccuracyEval(
    agent=Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[CalculatorTools(add=True, multiply=True, exponentiate=True)],
    ),
    prompt="What is 10*5 then to the power of 2? do it step by step",
    expected_answer="2500",
    num_iterations=1,
)
result_with_given_answer: Optional[AccuracyResult] = evaluation.run_with_given_answer(
    answer="2500", print_results=True
)
assert result_with_given_answer is not None and result_with_given_answer.avg_score >= 8
