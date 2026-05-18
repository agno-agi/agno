"""
Audio Classification - Basic
============================

Assign a single label from a closed set to an audio clip. The classic
language-identification primitive shown here applies to any closed-set
audio classification (genre, emotion, speaker, intent).
"""

from typing import Literal

import requests
from agno.agent import Agent, RunOutput  # noqa
from agno.media import Audio
from agno.models.google import Gemini
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Classification(BaseModel):
    language: Literal[
        "english", "spanish", "french", "german", "mandarin", "hindi", "other"
    ] = Field(..., description="Primary language spoken in the clip")


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=Gemini(id="gemini-3-flash-preview"),
    instructions="You classify audio clips by spoken language.",
    output_schema=Classification,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    url = "https://agno-public.s3.us-east-1.amazonaws.com/demo_data/QA-01.mp3"
    audio_bytes = requests.get(url).content
    run: RunOutput = agent.run(
        "What language is spoken in this audio?",
        audio=[Audio(content=audio_bytes)],
    )
    pprint({"url": url, "result": run.content})
