"""
Image Bounding Boxes - Basic
============================

Detect a single object in an image and return its bounding box. The model
emits normalized coordinates so the result is resolution-independent.
"""

from agno.agent import Agent, RunOutput  # noqa
from agno.media import Image
from agno.models.google import Gemini
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class BoundingBox(BaseModel):
    label: str = Field(..., description="What the box contains")
    x: float = Field(..., ge=0.0, le=1.0, description="Top-left x in [0, 1]")
    y: float = Field(..., ge=0.0, le=1.0, description="Top-left y in [0, 1]")
    width: float = Field(..., ge=0.0, le=1.0, description="Width in [0, 1]")
    height: float = Field(..., ge=0.0, le=1.0, description="Height in [0, 1]")


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Locate the main subject of the image and return its bounding box in
normalized coordinates. Coordinates are relative to the full image:
- x, y: top-left corner, each in [0, 1]
- width, height: size, each in [0, 1]

The box should be tight: include the subject and exclude as much background
as possible without clipping the subject.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=Gemini(id="gemini-3.5-flash"),
    instructions=instructions,
    output_schema=BoundingBox,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    url = "https://www.gstatic.com/webp/gallery/2.jpg"
    run: RunOutput = agent.run(
        "Locate the main subject of this image.", images=[Image(url=url)]
    )
    pprint({"url": url, "result": run.content})
