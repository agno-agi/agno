"""
LLM as Judge - With Rationale
=============================

Score plus a one-sentence rationale. The rationale lets a human spot-
check the model's reasoning and is itself useful as training data for a
reward model.
"""

from agno.agent import Agent, RunOutput  # noqa
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Score(BaseModel):
    overall: int = Field(..., ge=1, le=5, description="Overall quality 1-5")
    rationale: str = Field(..., description="One sentence explaining the score")


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Score the response on a 1-5 scale where 5 is excellent. In the rationale,
name the specific quality (or absence) that drove your score - quote a
phrase from the response when possible.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model="google:gemini-3.5-flash",
    instructions=instructions,
    output_schema=Score,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
def build_input(prompt: str, response: str) -> str:
    return f"Prompt:\n{prompt}\n\nResponse:\n{response}"


if __name__ == "__main__":
    prompt = "Suggest a name for a side project that helps people sleep better."
    response = (
        "How about 'Drift'? Short, evocative, and the .app domain is probably free."
    )
    run: RunOutput = agent.run(build_input(prompt, response))
    pprint({"response": response, "score": run.content})
