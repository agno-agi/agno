"""
Text Pairwise Preference - With Rubric
======================================

Same shape as `basic.py` but the judgement is grounded in an explicit
rubric supplied in the instructions. Use this when you need consistency
across many graders or many runs.
"""

from typing import Literal

from agno.agent import Agent, RunOutput  # noqa
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Preference(BaseModel):
    winner: Literal["A", "B", "tie"] = Field(..., description="Winner per rubric")


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are evaluating two candidate responses to the same prompt. Apply the
rubric below in order. Earlier criteria dominate later ones.

Rubric:
1. Factual correctness    - is everything stated true?
2. Completeness           - does it actually answer the prompt?
3. Clarity                - is it easy to understand for the target reader?
4. Concision              - is anything in it wasted?

Return 'A', 'B', or 'tie'. Use 'tie' only when the two responses are
indistinguishable on the rubric above.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model="google:gemini-3.5-flash",
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
    prompt = "How do I cancel my subscription?"
    a = (
        "Go to Settings > Subscription and click 'Cancel'. The cancellation "
        "takes effect at the end of your current billing period."
    )
    b = (
        "You can cancel anytime. Just dig around in the app, you'll find it. "
        "Maybe try the help docs."
    )
    run: RunOutput = agent.run(build_input(prompt, a, b))
    pprint({"A": a, "B": b, "result": run.content})
