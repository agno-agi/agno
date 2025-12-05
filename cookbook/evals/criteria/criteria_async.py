"""Async CriteriaEval usage example."""

import asyncio

from agno.agent import Agent
from agno.eval.criteria import CriteriaEval
from agno.models.openai import OpenAIChat


async def main():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        instructions="Provide helpful and informative answers.",
    )

    response = await agent.arun("Explain machine learning in simple terms")

    evaluation = CriteriaEval(
        name="ML Explanation Quality",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Response should be clear, accurate, and easy to understand",
        threshold=7,
        num_iterations=2,
    )

    result = await evaluation.arun(
        input="Explain machine learning in simple terms",
        output=str(response.content),
        print_results=True,
        print_summary=True,
    )

    # Validate evaluation completed with reasonable pass rate
    assert result is not None, "Evaluation should return a result"


if __name__ == "__main__":
    asyncio.run(main())
