"""
Export SFT - Empty Zone Guard
=============================

An empty selection is a normal outcome. Check it before export instead of
mistaking an empty file for a completed dataset-generation step.
"""

from dataclasses import replace
from pathlib import Path

from agno.agent import Agent
from agno.environments import Environment, Task, run_rollouts, to_sft_jsonl
from agno.models.openai import OpenAIResponses
from agno.scorer import CodeScorer
from pydantic import BaseModel


class Answer(BaseModel):
    value: int


def exact_value(run, expected):
    return run.content.value == expected


agent = Agent(
    model=OpenAIResponses(id="gpt-5.5", reasoning_effort="low"),
    output_schema=Answer,
)

env = Environment(
    name="export-empty-zone-guard",
    agent=agent,
    tasks=(
        Task(
            id="easy-anchor",
            input="Return the integer equal to 17 times 23.",
            expected=391,
        ),
        Task(
            id="product-a",
            input=(
                "Compute 2718281828459045 times 1618033988749895. Add the "
                "decimal digits of that product, multiply the digit sum by "
                "131071, subtract the product remainder modulo 65521, and "
                "return the final integer."
            ),
            expected=20944939,
        ),
        Task(
            id="product-b",
            input=(
                "Compute 3141592653589793 times 2718281828459045. Add the "
                "decimal digits of that product, multiply the digit sum by "
                "104729, subtract the product remainder modulo 65537, and "
                "return the final integer."
            ),
            expected=16756170,
        ),
    ),
    scorer=CodeScorer(exact_value),
)

output_path = Path(__file__).parent / "data" / "generated" / "guarded.jsonl"
sidecar_path = Path(str(output_path) + ".meta.json")


if __name__ == "__main__":
    # A no-op export must not leave a prior run's dataset at the advertised path.
    output_path.unlink(missing_ok=True)
    sidecar_path.unlink(missing_ok=True)

    result = run_rollouts(env, k=4)
    print(result)

    zone = result.learning_zone()
    if zone.task_results:
        report = to_sft_jsonl(zone, output_path)
        print(f"real learning-zone export rows: {report.n_written}")
    else:
        assert not output_path.exists() and not sidecar_path.exists()
        print("No real learning-zone rows; make the tasks harder.")

    empty_selection = replace(result, task_results=()).learning_zone()
    if not empty_selection.task_results:
        print(
            "Synthetic empty selection detected; exporter intentionally not called. "
            "Any files present now belong to this run's real selection."
        )
