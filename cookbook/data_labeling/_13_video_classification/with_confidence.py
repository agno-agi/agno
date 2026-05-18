"""
Video Classification - With Confidence
======================================

Adds confidence so downstream consumers can route low-confidence clips to
human review or a stronger model.
"""

from typing import Literal

import httpx
from agno.agent import Agent, RunOutput  # noqa
from agno.media import Video
from agno.models.google import Gemini
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Classification(BaseModel):
    scene_type: Literal[
        "nature",
        "urban",
        "indoor",
        "people",
        "vehicle",
        "animal",
        "other",
    ] = Field(..., description="Dominant scene type in the clip")
    confidence: Literal["high", "medium", "low"] = Field(
        ..., description="Confidence in the label"
    )


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Classify the clip and report a confidence:
- high   - the dominant scene is unambiguous across the clip
- medium - the dominant scene is identifiable but some shots break the
           pattern
- low    - the clip mixes several scene types and you had to pick
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    output_schema=Classification,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    url = "https://agno-public.s3.amazonaws.com/demo/sample_seaview.mp4"
    video_bytes = httpx.get(url).content
    run: RunOutput = agent.run(
        "Classify this clip with confidence.",
        videos=[Video(content=video_bytes, format="mp4")],
    )
    pprint({"url": url, "result": run.content})
