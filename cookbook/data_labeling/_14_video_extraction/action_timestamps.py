"""
Video Extraction - Action Timestamps
====================================

Detect actions or events in the clip with start/end times in seconds. The
shape used to generate chapter markers, "skip intro" cues, or training
data for temporal action detection.
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
class Event(BaseModel):
    action: str = Field(..., description="Short phrase naming the action or event")
    start_seconds: float = Field(..., ge=0.0, description="Start time in seconds")
    end_seconds: float = Field(..., ge=0.0, description="End time in seconds")


class Events(BaseModel):
    events: List[Event]


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Detect distinct actions or events in the clip. For each one, return a
short action name and start/end times in seconds from the beginning of
the clip. Times should be monotonically non-decreasing. Skip ambient or
filler content - only include events with a clear beginning and end.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    output_schema=Events,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    url = "https://agno-public.s3.amazonaws.com/demo/sample_seaview.mp4"
    video_bytes = httpx.get(url).content
    run: RunOutput = agent.run(
        "Detect events with timestamps.",
        videos=[Video(content=video_bytes, format="mp4")],
    )
    pprint(run.content)
