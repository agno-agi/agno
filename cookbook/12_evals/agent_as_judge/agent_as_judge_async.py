"""Async AgentAsJudgeEval usage example with async on_fail callback."""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import AsyncSqliteDb
from agno.eval.agent_as_judge import AgentAsJudgeEval, AgentAsJudgeEvaluation
from agno.models.openai import OpenAIChat


def on_evaluation_failure(evaluation: AgentAsJudgeEvaluation):
    """Async callback triggered when evaluation fails (score < threshold)."""
    print(f"Evaluation failed - Score: {evaluation.score}/10")
    print(f"Reason: {evaluation.reason}")


async def main():
    # Setup database to persist eval results
    db = AsyncSqliteDb(db_file="tmp/agent_as_judge_async.db")

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        instructions="Provide helpful and informative answers.",
        db=db,
    )

    response = await agent.arun("Explain machine learning in simple terms")

    evaluation = AgentAsJudgeEval(
        name="ML Explanation Quality",
        model=OpenAIChat(id="gpt-4o-mini"),
        criteria="Explanation should be clear, beginner-friendly, and avoid jargon",
        scoring_strategy="numeric",
        threshold=10,
        on_fail=on_evaluation_failure,
        db=db,
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
