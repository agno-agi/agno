"""
Task selection - Rerun failures
===============================

Run the task set once, select every original row that did not reach a full pass
rate, and gather a second independent batch of evidence for only those rows.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel, Field


class FinalInteger(BaseModel):
    value: int = Field(description="The final integer after every requested operation")


def exact_integer(run, expected) -> bool:
    return isinstance(run.content, FinalInteger) and run.content.value == expected


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    instructions="Calculate exactly. Return only the final integer in the response schema.",
    output_schema=FinalInteger,
)

env = Environment(
    name="targeted-rerun",
    agent=agent,
    tasks=(
        Task(id="easy-anchor", input="Multiply 17 by 23.", expected=391),
        Task(
            id="rerun-edge-a",
            input=(
                "Multiply 2718281828459045 by 1618033988749895. Add the decimal "
                "digits of the product, multiply that digit sum by 131071, then "
                "subtract the product's remainder modulo 65521."
            ),
            expected=20944939,
        ),
        Task(
            id="rerun-edge-b",
            input=(
                "Multiply 3141592653589793 by 1414213562373095. Add the decimal "
                "digits of the product, multiply that digit sum by 65537, then "
                "subtract the product's remainder modulo 32749."
            ),
            expected=10481347,
        ),
    ),
    scorer=CodeScorer(exact_integer),
)


if __name__ == "__main__":
    first = run_rollouts(env, k=4, concurrency=4)
    print("Initial grid")
    print(first)

    retry_ids = {
        task_result.task.id
        for task_result in first.task_results
        if task_result.pass_rate is not None and task_result.pass_rate < 1
    }
    retry_tasks = [task for task in env.tasks if task.id in retry_ids]
    print(f"rerunning task ids: {sorted(retry_ids)}")

    rerun = run_rollouts(env, tasks=retry_tasks, k=4, concurrency=4)
    print("Rerun grid")
    print(rerun)
    for task_result in rerun.task_results:
        print(f"{task_result.task.id}: pass rate {task_result.pass_rate}")
