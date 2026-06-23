"""
Audio Classification - With Confidence
======================================

Adds confidence so downstream routing can treat low-confidence labels
differently (escalate to a stronger model, queue for human review).
"""

from typing import Literal

import requests
from agno.agent import Agent, RunOutput  # noqa
from agno.media import Audio
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Classification(BaseModel):
    language: Literal[
        "english", "spanish", "french", "german", "mandarin", "hindi", "other"
    ] = Field(..., description="Primary language spoken in the clip")
    confidence: Literal["high", "medium", "low"] = Field(
        ..., description="Confidence in the language label"
    )


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Identify the language and report a confidence:
- high   - clear speech, accent is identifiable, no background interference
- medium - speech is audible but accent / dialect is ambiguous
- low    - very short, heavily accented, mixed-language, or noisy
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model="google:gemini-3.5-flash",
    instructions=instructions,
    output_schema=Classification,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    url = "https://agno-public.s3.us-east-1.amazonaws.com/demo_data/QA-01.mp3"
    audio_bytes = requests.get(url).content
    run: RunOutput = agent.run(
        "Identify the language and report confidence.",
        audio=[Audio(content=audio_bytes)],
    )
    pprint({"url": url, "result": run.content})
