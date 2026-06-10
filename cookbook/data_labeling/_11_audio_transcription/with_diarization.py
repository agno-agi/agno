"""
Audio Transcription - With Diarization
======================================

Speech-to-text with speaker labels. Each segment is attributed to a
speaker identifier (Speaker A, Speaker B, ...). The model assigns labels
consistently across the clip but does not know real names.
"""

from typing import List

import requests
from agno.agent import Agent, RunOutput  # noqa
from agno.media import Audio
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class DiarizedTurn(BaseModel):
    speaker: str = Field(
        ..., description="Speaker identifier - 'Speaker A', 'Speaker B', etc."
    )
    text: str = Field(..., description="What this speaker said in this turn")


class DiarizedTranscript(BaseModel):
    turns: List[DiarizedTurn]


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Transcribe the audio and split it into turns. Each turn is one continuous
stretch of speech by a single speaker. Label speakers consistently across
the whole clip: the first speaker is "Speaker A", the second is
"Speaker B", and so on. Do not invent names.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model="google:gemini-3.5-flash",
    instructions=instructions,
    output_schema=DiarizedTranscript,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    url = "https://agno-public.s3.amazonaws.com/demo_data/sample_conversation.wav"
    audio_bytes = requests.get(url).content
    run: RunOutput = agent.run(
        "Transcribe with speaker labels.",
        audio=[Audio(content=audio_bytes)],
    )
    pprint(run.content)
