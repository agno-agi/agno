"""
Image Extraction - With Confidence
==================================

Adds per-field confidence to image attribute extraction. Useful when the
input quality varies (low-res, motion blur, partial occlusion) and you
need to flag uncertain fields for review.
"""

from typing import List, Literal, Optional

from agno.agent import Agent, RunOutput  # noqa
from agno.media import Image
from agno.models.openai import OpenAIResponses
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa

Confidence = Literal["high", "medium", "low"]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class ConfidentStr(BaseModel):
    value: Optional[str] = None
    confidence: Confidence


class ConfidentList(BaseModel):
    values: List[str] = Field(default_factory=list)
    confidence: Confidence


class Scene(BaseModel):
    subject: ConfidentStr
    setting: ConfidentStr
    time_of_day: ConfidentStr
    dominant_colors: ConfidentList
    notable_objects: ConfidentList


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Describe the image as a structured Scene. For each field, report
confidence:
- high   - clearly determinable from the image
- medium - inferred but well-supported
- low    - guessed or partially obscured

Be conservative. If you cannot see a field, mark its value null and
confidence low.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=instructions,
    output_schema=Scene,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    url = "https://upload.wikimedia.org/wikipedia/commons/a/a8/Tour_Eiffel_Wikimedia_Commons.jpg"
    run: RunOutput = agent.run("Extract the scene attributes.", images=[Image(url=url)])
    pprint({"url": url, "result": run.content})
