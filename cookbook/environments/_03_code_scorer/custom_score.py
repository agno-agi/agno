"""
Custom Score Details
====================

Implement the public Scorer protocol when a verdict needs structured reasons
and details. This scorer remains deterministic and fingerprints its source.
"""

import hashlib
import inspect

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import Score, Scorer
from pydantic import BaseModel


class Answer(BaseModel):
    value: int


class ExplainedExactScorer:
    async def ascore(self, run, expected=None):
        actual = run.content.value
        passed = actual == expected
        distance = abs(actual - expected)
        return Score(
            value=1.0 if passed else 0.0,
            passed=passed,
            reason="exact integer matched" if passed else "exact integer differed",
            detail={"actual": actual, "expected": expected, "absolute_error": distance},
        )

    def digest(self):
        source = inspect.getsource(type(self))
        return hashlib.sha256(source.encode("utf-8")).hexdigest()


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=Answer,
    instructions="Return only the requested final integer in the typed field.",
)

scorer: Scorer = ExplainedExactScorer()

environment = Environment(
    name="custom-explained-score",
    agent=agent,
    tasks=(
        Task(
            input=(
                "Compute 2718281828459045 multiplied by 1618033988749895. "
                "Add its decimal digits, multiply the sum by 131071, subtract "
                "the product remainder modulo 65521, and return the result."
            ),
            expected=20944939,
            id="chained-product-a",
        ),
        Task(
            input=(
                "Compute 1618033988749895 multiplied by 1414213562373095. "
                "Add its decimal digits, multiply the sum by 99991, subtract "
                "the product remainder modulo 65519, and return the result."
            ),
            expected=11468302,
            id="chained-product-c",
        ),
    ),
    scorer=scorer,
)


if __name__ == "__main__":
    results = run_rollouts(environment, k=4)
    print(results)
    print()
    for task_result in results.task_results:
        failed = [
            attempt.score.detail
            for attempt in task_result.attempts
            if attempt.score is not None and not attempt.score.passed
        ]
        print(
            f"{task_result.task.id}: pass_rate={task_result.pass_rate}, "
            f"failed_details={failed}"
        )
