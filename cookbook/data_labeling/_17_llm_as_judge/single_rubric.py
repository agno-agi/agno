"""
LLM as Judge - Single Rubric
============================

Score against an explicit, named rubric. Each criterion gets its own
score, plus an overall. Use this for eval consistency across runs and
graders.
"""

from typing import Literal

from agno.agent import Agent, RunOutput  # noqa
from agno.models.openai import OpenAIResponses
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa

Score = Literal[1, 2, 3, 4, 5]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class RubricScore(BaseModel):
    correctness: Score = Field(..., description="Is everything stated true")
    completeness: Score = Field(..., description="Does it answer the prompt fully")
    clarity: Score = Field(..., description="Easy to understand for the target reader")
    concision: Score = Field(..., description="Free of wasted words")
    overall: Score = Field(..., description="Holistic quality")


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Score the response on each rubric criterion using a 1-5 scale:
1 - unusable, 2 - poor, 3 - acceptable, 4 - good, 5 - excellent.

The overall score should reflect the holistic quality, not a simple
average. A response that fails correctness can still score well on
clarity, but the overall should reflect the worst dimension.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=instructions,
    output_schema=RubricScore,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
def build_input(prompt: str, response: str) -> str:
    return f"Prompt:\n{prompt}\n\nResponse:\n{response}"


if __name__ == "__main__":
    prompt = "How do I cancel my subscription?"
    response = (
        "Go to Settings > Subscription and click 'Cancel'. The cancellation "
        "takes effect at the end of your current billing period."
    )
    run: RunOutput = agent.run(build_input(prompt, response))
    pprint({"response": response, "scores": run.content})
