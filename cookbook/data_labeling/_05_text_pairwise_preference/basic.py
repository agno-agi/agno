"""
Text Pairwise Preference - Basic
================================

Given a prompt and two responses, pick the better one. The output is the
data shape used to train reward models (RLHF) or do DPO fine-tuning.
"""

from typing import Literal

from agno.agent import Agent, RunOutput  # noqa
from agno.models.openai import OpenAIResponses
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Preference(BaseModel):
    winner: Literal["A", "B", "tie"] = Field(
        ..., description="Which response is better, or 'tie' if equally good"
    )


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are evaluating two candidate responses to the same prompt. Decide which
response better answers the prompt. Return 'A', 'B', or 'tie'. Use 'tie'
only when the two are genuinely indistinguishable in quality.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=instructions,
    output_schema=Preference,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
def build_input(prompt: str, response_a: str, response_b: str) -> str:
    return (
        f"Prompt:\n{prompt}\n\nResponse A:\n{response_a}\n\nResponse B:\n{response_b}"
    )


if __name__ == "__main__":
    prompt = "Explain why the sky is blue, in one sentence."
    a = (
        "Sunlight scatters off air molecules, and shorter (blue) wavelengths "
        "scatter more than longer ones, so we see blue from every direction."
    )
    b = "Because of physics."
    run: RunOutput = agent.run(build_input(prompt, a, b))
    pprint({"A": a, "B": b, "result": run.content})
