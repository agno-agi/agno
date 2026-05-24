"""
Audio Extraction - Call Summary
===============================

Customer support call shape: issue, resolution status, customer sentiment.
Common shape for populating ticketing systems from voice channels.
"""

from typing import Literal, Optional

import requests
from agno.agent import Agent, RunOutput  # noqa
from agno.media import Audio
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class SupportCall(BaseModel):
    issue: str = Field(..., description="What the customer is reporting")
    resolution_status: Literal["resolved", "pending", "escalated", "unclear"] = Field(
        ..., description="State of the issue at end of call"
    )
    customer_sentiment: Literal["positive", "neutral", "negative"]
    follow_up_required: bool = Field(
        ..., description="Whether the agent committed to a follow-up"
    )
    notes: Optional[str] = Field(
        None, description="One sentence of additional context, if useful"
    )


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are extracting structured data from a customer support call recording.
Be conservative on resolution status: if you cannot confirm the issue was
resolved on the call, use 'pending' or 'unclear'. Sentiment reflects the
customer's tone, not the support agent's.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model="google:gemini-3.5-flash",
    instructions=instructions,
    output_schema=SupportCall,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    url = "https://agno-public.s3.amazonaws.com/demo_data/sample_conversation.wav"
    audio_bytes = requests.get(url).content
    run: RunOutput = agent.run(
        "Extract a support-call summary.",
        audio=[Audio(content=audio_bytes)],
    )
    pprint(run.content)
