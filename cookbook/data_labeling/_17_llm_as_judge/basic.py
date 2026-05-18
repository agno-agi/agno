"""
LLM as Judge - Basic
====================

Score a generated response against the prompt on a 1-5 scale. The simplest
eval primitive - and identical machinery to single-label text
classification, just applied to (prompt, response) pairs.
"""

from typing import Literal

from agno.agent import Agent, RunOutput  # noqa
from agno.models.openai import OpenAIResponses
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Score(BaseModel):
    overall: Literal[1, 2, 3, 4, 5] = Field(
        ..., description="Overall quality on a 1-5 scale where 5 is excellent"
    )


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Score the response on overall quality:
1 - unusable
2 - poor
3 - acceptable
4 - good
5 - excellent

Use the full scale. Reserve 5 for genuinely excellent responses.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=instructions,
    output_schema=Score,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
def build_input(prompt: str, response: str) -> str:
    return f"Prompt:\n{prompt}\n\nResponse:\n{response}"


if __name__ == "__main__":
    prompt = "Explain why the sky is blue, in one sentence."
    samples = [
        (
            "Sunlight scatters off air molecules; shorter (blue) wavelengths "
            "scatter more, so blue dominates what we see."
        ),
        "It just is.",
    ]
    for response in samples:
        run: RunOutput = agent.run(build_input(prompt, response))
        pprint({"response": response, "score": run.content})
