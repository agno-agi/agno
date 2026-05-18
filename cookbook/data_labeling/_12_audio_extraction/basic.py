"""
Audio Extraction - Basic
========================

Extract typed structured data from an audio clip. The schema here is a
generic call summary; swap in domain-specific shapes for production use.
"""

from typing import List, Optional

import requests
from agno.agent import Agent, RunOutput  # noqa
from agno.media import Audio
from agno.models.google import Gemini
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class CallSummary(BaseModel):
    caller_intent: str = Field(..., description="What the caller is trying to do")
    key_topics: List[str] = Field(
        default_factory=list, description="Main topics discussed"
    )
    next_action: Optional[str] = Field(
        None, description="What should happen next, if mentioned"
    )


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Listen to the call and extract a structured summary. Use what is actually
said - do not invent topics or actions. If the caller's intent is unclear,
write what you can determine and leave others null.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    output_schema=CallSummary,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    url = "https://agno-public.s3.amazonaws.com/demo_data/sample_conversation.wav"
    audio_bytes = requests.get(url).content
    run: RunOutput = agent.run(
        "Summarize this call.",
        audio=[Audio(content=audio_bytes)],
    )
    pprint(run.content)
