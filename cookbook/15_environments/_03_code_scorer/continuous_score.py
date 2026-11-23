"""
Continuous Code Scores
======================

Award partial credit for correct intermediate values while keeping the pass
bar strict. Score.value diagnoses how far an attempt got; passed still means
all four independently checked fields were correct.
"""

from typing import Any, Dict

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel


class Calculation(BaseModel):
    product: int
    digit_sum: int
    remainder: int
    value: int


def component_accuracy(run, expected: Dict[str, Any]):
    actual = run.content.model_dump()
    correct = sum(actual[field] == value for field, value in expected.items())
    return correct / len(expected)


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=Calculation,
    instructions=(
        "Fill every typed field: the full product, its decimal digit sum, the "
        "requested remainder, and the final value."
    ),
)

environment = Environment(
    name="continuous-code-score",
    agent=agent,
    tasks=(
        Task(
            input=(
                "Compute 2718281828459045 multiplied by 1618033988749895. "
                "Add its decimal digits, multiply the sum by 131071, subtract "
                "the product remainder modulo 65521, and return every intermediate."
            ),
            expected={
                "product": 4398272389447946427773755550275,
                "digit_sum": 160,
                "remainder": 26421,
                "value": 20944939,
            },
            id="audited-chain-a",
        ),
        Task(
            input=(
                "Compute 3141592653589793 multiplied by 1414213562373095. "
                "Add its decimal digits, multiply the sum by 104729, subtract "
                "the product remainder modulo 65537, and return every intermediate."
            ),
            expected={
                "product": 4442882938158365756463749819335,
                "digit_sum": 160,
                "remainder": 25467,
                "value": 16731173,
            },
            id="audited-chain-b",
        ),
    ),
    scorer=CodeScorer(component_accuracy, pass_threshold=1.0),
)


if __name__ == "__main__":
    results = run_rollouts(environment, k=4)
    print(results)
    print()
    for task_result in results.task_results:
        values = [
            attempt.score.value for attempt in task_result.attempts if attempt.score
        ]
        print(
            f"{task_result.task.id}: component scores={values}, "
            f"pass_rate={task_result.pass_rate}"
        )
