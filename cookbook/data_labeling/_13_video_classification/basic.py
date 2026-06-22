"""
Video Classification - Basic
============================

Assign a single label from a closed set to a video clip. The model watches
the clip end-to-end and emits one label for the whole thing.
"""

from typing import Literal

import httpx
from agno.agent import Agent, RunOutput  # noqa
from agno.media import Video
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


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model="google:gemini-3.5-flash",
    instructions="You classify short video clips by dominant scene type.",
    output_schema=Classification,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    url = "https://agno-public.s3.amazonaws.com/demo/sample_seaview.mp4"
    video_bytes = httpx.get(url).content
    run: RunOutput = agent.run(
        "Classify this clip.",
        videos=[Video(content=video_bytes, format="mp4")],
    )
    pprint({"url": url, "result": run.content})
