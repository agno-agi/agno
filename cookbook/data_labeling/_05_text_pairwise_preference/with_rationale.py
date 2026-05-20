"""
Text Pairwise Preference - With Rationale
=========================================

Winner plus a short rationale. The rationale is itself useful training
data: it can be distilled into a reward model or used to explain a model's
own preferences to a human reviewer.
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
        ..., description="Which response is better"
    )
    rationale: str = Field(..., description="One sentence explaining the decision")


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are evaluating two candidate responses to the same prompt. Decide
which response is better and provide a one-sentence rationale that names
the specific quality that drove the decision (correctness, completeness,
clarity, tone, etc.).
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
    prompt = "Suggest a name for a side project that helps people sleep better."
    a = "How about 'Drift'? Short, evocative, and the .app domain is probably free."
    b = "SleepHelperProMaxXL"
    run: RunOutput = agent.run(build_input(prompt, a, b))
    pprint({"A": a, "B": b, "result": run.content})
