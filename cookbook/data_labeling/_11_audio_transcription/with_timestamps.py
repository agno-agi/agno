"""
Audio Transcription - With Timestamps
=====================================

Speech-to-text with start/end timing per segment, in seconds from the
start of the clip. Useful for video captioning, jump-to-quote UI, or
chunked playback.
"""

from typing import List

import requests
from agno.agent import Agent, RunOutput  # noqa
from agno.media import Audio
from agno.models.google import Gemini
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Segment(BaseModel):
    start_seconds: float = Field(..., ge=0.0, description="Start time in seconds")
    end_seconds: float = Field(..., ge=0.0, description="End time in seconds")
    text: str = Field(..., description="Transcript of this segment")


class TimedTranscript(BaseModel):
    segments: List[Segment]


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Transcribe the audio and split it into segments of roughly one sentence
each. For each segment, return the start and end time in seconds from the
beginning of the clip. Times should be monotonically non-decreasing.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    output_schema=TimedTranscript,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    url = "https://agno-public.s3.us-east-1.amazonaws.com/demo_data/QA-01.mp3"
    audio_bytes = requests.get(url).content
    run: RunOutput = agent.run(
        "Transcribe with timestamps.",
        audio=[Audio(content=audio_bytes)],
    )
    pprint(run.content)
