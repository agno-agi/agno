"""
Difficulty calibration - Ambiguity ladder
=========================================

Increase difficulty without larger numbers by changing natural-language scope.
These prompts have plausible competing groupings, so repeated answers reveal
where wording needs clarification.
"""

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel, Field


class FinalInteger(BaseModel):
    value: int = Field(
        description="The final integer under the most natural prose grouping"
    )


def exact_integer(run, expected) -> bool:
    return isinstance(run.content, FinalInteger) and run.content.value == expected


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    instructions=(
        "Interpret each instruction as ordinary prose, not algebraic notation. "
        "When scope is genuinely ambiguous, choose the reading a careful editor "
        "would consider most natural. Return only the final integer."
    ),
    output_schema=FinalInteger,
)

env = Environment(
    name="ambiguity-ladder",
    agent=agent,
    tasks=(
        Task(id="comma-scope", input="Take 48 minus 6, divided by 3.", expected=14),
        Task(id="modifier-scope", input="Add 12 to 5 times 4.", expected=32),
        Task(id="coordination-scope", input="Divide 84 by 7 plus 5.", expected=17),
        Task(
            id="nested-scope",
            input="Subtract 9 from 63 divided by 3, then add 4 times 2.",
            expected=20,
        ),
    ),
    scorer=CodeScorer(exact_integer),
)


if __name__ == "__main__":
    result = run_rollouts(env, k=6, concurrency=6)
    print(result)
    for task_result in result.task_results:
        print(f"{task_result.task.id}: pass rate {task_result.pass_rate}")
