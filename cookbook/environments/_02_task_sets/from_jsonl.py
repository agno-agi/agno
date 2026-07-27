"""
Task Sets from JSONL
====================

Load a version-controlled task set with `Task.from_jsonl`. Each line may hold
input, expected output, id, and metadata; unknown keys fail validation.
"""

from pathlib import Path

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel


class Answer(BaseModel):
    value: int


def answer_matches(run, expected):
    return run.content.value == expected


TASKS_PATH = Path(__file__).parent / "data" / "chained_arithmetic.jsonl"

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=Answer,
    instructions="Return only the requested final integer in the typed field.",
)

environment = Environment(
    name="jsonl-task-set",
    agent=agent,
    tasks=Task.from_jsonl(TASKS_PATH),
    scorer=CodeScorer(answer_matches),
)


if __name__ == "__main__":
    results = run_rollouts(environment, k=4)
    print(results)
    print(f"loaded {len(environment.tasks)} tasks from {TASKS_PATH}")
