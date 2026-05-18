"""
Audio Transcription - Basic
===========================

Speech-to-text on an audio clip. The output is a flat transcript string.
"""

import requests
from agno.agent import Agent, RunOutput  # noqa
from agno.media import Audio
from agno.models.google import Gemini
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Transcript(BaseModel):
    text: str = Field(..., description="Verbatim transcript of all spoken audio")


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Transcribe everything spoken in the audio clip. Preserve disfluencies
(um, uh, like) only if asked - by default produce a clean verbatim
transcript. Do not add commentary.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    output_schema=Transcript,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    url = "https://agno-public.s3.us-east-1.amazonaws.com/demo_data/QA-01.mp3"
    audio_bytes = requests.get(url).content
    run: RunOutput = agent.run(
        "Transcribe this audio.",
        audio=[Audio(content=audio_bytes)],
    )
    pprint(run.content)
