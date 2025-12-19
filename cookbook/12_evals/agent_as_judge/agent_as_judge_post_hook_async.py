"""Async AgentAsJudgeEval as post-hook example."""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import AsyncSqliteDb
from agno.eval.agent_as_judge import AgentAsJudgeEval
from agno.models.openai import OpenAIChat


async def main():
    # Setup database to persist eval results
    db = AsyncSqliteDb(db_file="tmp/agent_as_judge_post_hook_async.db")

    # Eval runs as post-hook, results saved to database
    agent_as_judge_eval = AgentAsJudgeEval(
        name="Response Quality Check",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Response should be professional, well-balanced, and provide evidence-based perspectives",
        scoring_strategy="numeric",
        threshold=7,
        db=db,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        instructions="Provide professional and well-reasoned answers.",
        post_hooks=[agent_as_judge_eval],
        db=db,
    )

    response = await agent.arun("What are the benefits of renewable energy?")
    print(response.content)

    # Query database for eval results
    print("Evaluation Results:")
    eval_runs = await db.get_eval_runs()
    if eval_runs:
        latest = eval_runs[-1]
        if latest.eval_data and "results" in latest.eval_data:
            result = latest.eval_data["results"][0]
            print(f"Score: {result.get('score', 'N/A')}/10")
            print(f"Status: {'PASSED' if result.get('passed') else 'FAILED'}")
            print(f"Reason: {result.get('reason', 'N/A')[:200]}...")


if __name__ == "__main__":
    asyncio.run(main())
