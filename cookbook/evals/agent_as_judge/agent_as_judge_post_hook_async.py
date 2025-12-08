"""Async AgentAsJudgeEval as post-hook example."""

import asyncio

from agno.agent import Agent
from agno.eval.agent_as_judge import AgentAsJudgeEval
from agno.models.openai import OpenAIChat


async def main():
    agent_as_judge_eval = AgentAsJudgeEval(
        name="Response Quality Check",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Response should be professional, well-balanced, and provide evidence-based perspectives",
        threshold=7,
        print_results=True,
        print_summary=True,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        instructions="Provide professional and well-reasoned answers.",
        post_hooks=[agent_as_judge_eval],
    )

    response = await agent.arun("What are the benefits of renewable energy?")
    print(response.content)


if __name__ == "__main__":
    asyncio.run(main())
