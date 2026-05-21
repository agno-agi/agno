"""
Video Extraction - Scene Descriptions
=====================================

One structured description per detected scene. Each scene has a name, a
detailed description, and a list of visible objects - the shape used for
video indexing and search.
"""

from typing import List

import httpx
from agno.agent import Agent, RunOutput  # noqa
from agno.media import Video
from agno.models.google import Gemini
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Scene(BaseModel):
    name: str = Field(..., description="Short phrase naming the scene")
    description: str = Field(..., description="One to two sentences of detail")
    visible_objects: List[str] = Field(
        default_factory=list, description="Up to five notable objects in the scene"
    )


class ScenesDocument(BaseModel):
    scenes: List[Scene]


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Watch the clip and split it into distinct scenes. For each scene, return a
short name, a detailed description of what is visually shown, and the
notable objects. A new scene begins when the location, subject, or shot
changes substantially. Do not invent details.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=Gemini(id="gemini-3.5-flash"),
    instructions=instructions,
    output_schema=ScenesDocument,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    url = "https://agno-public.s3.amazonaws.com/demo/sample_seaview.mp4"
    video_bytes = httpx.get(url).content
    run: RunOutput = agent.run(
        "Describe each scene in this clip.",
        videos=[Video(content=video_bytes, format="mp4")],
    )
    pprint(run.content)
