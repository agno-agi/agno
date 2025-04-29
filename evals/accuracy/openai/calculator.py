from typing import Optional

from agno.agent import Agent
from agno.eval.accuracy import AccuracyEval, AccuracyResult
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools


def multiply_and_exponentiate():
    evaluation = AccuracyEval(
        agent=Agent(
            model=OpenAIChat(id="gpt-4o-mini"),
            tools=[CalculatorTools(add=True, multiply=True, exponentiate=True)],
        ),
        question="What is 10*5 then to the power of 2? do it step by step",
        expected_answer="2500",
        num_iterations=1
    )
    result: Optional[AccuracyResult] = evaluation.run(print_results=True)

    assert result is not None and result.avg_score >= 8


def factorial():
    evaluation = AccuracyEval(
        agent=Agent(
            model=OpenAIChat(id="gpt-4o-mini"),
            tools=[CalculatorTools(factorial=True)],
        ),
        question="What is 10!?",
        expected_answer="3628800",
        num_iterations=1
    )
    result: Optional[AccuracyResult] = evaluation.run(print_results=True)

    assert result is not None and result.avg_score >= 8


if __name__ == "__main__":
    multiply_and_exponentiate()
    # factorial()
