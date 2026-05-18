"""
Image Bounding Boxes - With Confidence
======================================

Adds per-box confidence so downstream consumers can threshold or send
low-confidence boxes to a human reviewer.
"""

from typing import Literal

from agno.agent import Agent, RunOutput  # noqa
from agno.media import Image
from agno.models.openai import OpenAIResponses
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class BoundingBox(BaseModel):
    label: str = Field(..., description="What the box contains")
    x: float = Field(..., ge=0.0, le=1.0)
    y: float = Field(..., ge=0.0, le=1.0)
    width: float = Field(..., ge=0.0, le=1.0)
    height: float = Field(..., ge=0.0, le=1.0)
    confidence: Literal["high", "medium", "low"] = Field(
        ..., description="Confidence in the box and label"
    )


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Locate the main subject and return a bounding box plus a confidence:
- high   - subject is clearly visible, box is tight and accurate
- medium - subject is identifiable but partly occluded, box is approximate
- low    - subject is barely visible or you are guessing at the location
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=instructions,
    output_schema=BoundingBox,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    url = "https://upload.wikimedia.org/wikipedia/commons/4/4d/Cat_November_2010-1a.jpg"
    run: RunOutput = agent.run(
        "Locate the main subject and report confidence.", images=[Image(url=url)]
    )
    pprint({"url": url, "result": run.content})
