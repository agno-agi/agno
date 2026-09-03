"""
Task Metadata
=============

Attach split and difficulty labels to tasks, then select the original task
objects before running. Metadata organizes the dataset without entering the
agent prompt or changing the scorer.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel


class Answer(BaseModel):
    value: int


def answer_matches(run, expected):
    return run.content.value == expected


TASKS = (
    Task(
        input=(
            "Compute 2718281828459045 multiplied by 1618033988749895. Add "
            "the product's decimal digits, multiply the sum by 131071, "
            "subtract the product remainder modulo 65521, and return the result."
        ),
        expected=20944939,
        id="chained-product-a",
        metadata={"split": "validation", "difficulty": "calibration"},
    ),
    Task(
        input=(
            "Compute 3141592653589793 multiplied by 1414213562373095. Add "
            "the product's decimal digits, multiply the sum by 104729, "
            "subtract the product remainder modulo 65537, and return the result."
        ),
        expected=16731173,
        id="chained-product-b",
        metadata={"split": "validation", "difficulty": "calibration"},
    ),
    Task(
        input="What is 43 multiplied by 47?",
        expected=2021,
        id="easy-product",
        metadata={"split": "smoke", "difficulty": "anchor"},
    ),
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=Answer,
    instructions="Return only the requested final integer in the typed field.",
)

environment = Environment(
    name="metadata-task-set",
    agent=agent,
    tasks=TASKS,
    scorer=CodeScorer(answer_matches),
)


if __name__ == "__main__":
    calibration_tasks = tuple(
        task
        for task in environment.tasks
        if task.metadata["difficulty"] == "calibration"
    )
    results = run_rollouts(environment, tasks=calibration_tasks, k=4)
    print(results)
    print()
    for task_result in results.task_results:
        split = task_result.task.metadata["split"]
        difficulty = task_result.task.metadata["difficulty"]
        print(
            f"{task_result.task.id}: split={split}, difficulty={difficulty}, "
            f"pass_rate={task_result.pass_rate}"
        )
