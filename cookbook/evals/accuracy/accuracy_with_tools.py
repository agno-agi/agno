from typing import Optional

from agno.agent import Agent
from agno.eval.accuracy import AccuracyEval, AccuracyResult
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools

evaluation = AccuracyEval(
    agent=Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[CalculatorTools(factorial=True)],
    ),
    prompt="What is 10!?",
    expected_answer="3628800",
    num_iterations=1,
)

result: Optional[AccuracyResult] = evaluation.run(print_results=True)
assert result is not None and result.avg_score >= 8
