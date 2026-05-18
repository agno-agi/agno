"""
Video Extraction - Basic
========================

Extract a clip-level summary plus a flat list of scenes. The shape most
useful for "give me an overview" tasks - chapters, thumbnails, index
metadata.
"""

from typing import List, Optional

import httpx
from agno.agent import Agent, RunOutput  # noqa
from agno.media import Video
from agno.models.google import Gemini
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class VideoSummary(BaseModel):
    overall_summary: str = Field(
        ..., description="Two-sentence summary of the whole clip"
    )
    dominant_subject: Optional[str] = Field(
        None, description="Main subject of the clip"
    )
    scenes: List[str] = Field(
        default_factory=list,
        description="Distinct scenes in order, each as a short phrase",
    )


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Watch the clip and summarize it. List distinct scenes in chronological
order as short phrases (e.g. "wide shot of harbor", "close-up of seagulls").
Skip transitions and filler. The summary should reflect what is actually
shown, not what the clip is "about" thematically.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    output_schema=VideoSummary,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    url = "https://agno-public.s3.amazonaws.com/demo/sample_seaview.mp4"
    video_bytes = httpx.get(url).content
    run: RunOutput = agent.run(
        "Summarize this clip and list the scenes.",
        videos=[Video(content=video_bytes, format="mp4")],
    )
    pprint(run.content)
