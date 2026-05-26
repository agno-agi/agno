"""
Image Bounding Boxes - Multi Object
===================================

Detect multiple objects of multiple classes in one image. The output is a
list of boxes, each with a label and normalized coordinates.
"""

from typing import List

from agno.agent import Agent, RunOutput  # noqa
from agno.media import Image
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class BoundingBox(BaseModel):
    label: str = Field(..., description="Object class for this box")
    x: float = Field(..., ge=0.0, le=1.0)
    y: float = Field(..., ge=0.0, le=1.0)
    width: float = Field(..., ge=0.0, le=1.0)
    height: float = Field(..., ge=0.0, le=1.0)


class Detection(BaseModel):
    boxes: List[BoundingBox] = Field(
        default_factory=list, description="All detected objects in the image"
    )


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Detect every distinct object in the image. For each one, return a label
and a tight bounding box in normalized coordinates (top-left x and y,
width, height - all in [0, 1]).

Skip background elements (sky, road surface) unless they are the subject.
Skip duplicates: if two objects are nearly identical and overlapping,
report a single box.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model="google:gemini-3.5-flash",
    instructions=instructions,
    output_schema=Detection,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    url = "https://storage.googleapis.com/generativeai-downloads/images/generated_elephants_giraffes_zebras_sunset.jpg"
    run: RunOutput = agent.run(
        "Detect every object in this image.", images=[Image(url=url)]
    )
    pprint({"url": url, "result": run.content})
