"""
Audio Extraction - Meeting Notes
================================

Meeting-shape extraction: attendees, topics, action items. The standard
shape used by note-taking integrations.
"""

from typing import List, Optional

import requests
from agno.agent import Agent, RunOutput  # noqa
from agno.media import Audio
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class ActionItem(BaseModel):
    owner: str = Field(..., description="Person responsible, as named in the meeting")
    description: str = Field(..., description="What they committed to do")
    due_date: Optional[str] = Field(None, description="ISO yyyy-mm-dd if mentioned")


class MeetingNotes(BaseModel):
    attendees: List[str] = Field(
        default_factory=list, description="Speakers identifiable in the audio"
    )
    topics: List[str] = Field(
        default_factory=list, description="Main topics discussed, in order"
    )
    action_items: List[ActionItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Listen to the meeting audio and produce structured notes. Only include
action items that are explicitly assigned to a named person - skip vague
group asks. Only include attendees you can actually identify from the
audio (named by another speaker or self-introduced).
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model="google:gemini-3.5-flash",
    instructions=instructions,
    output_schema=MeetingNotes,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    url = "https://agno-public.s3.amazonaws.com/demo_data/sample_conversation.wav"
    audio_bytes = requests.get(url).content
    run: RunOutput = agent.run(
        "Produce meeting notes for this recording.",
        audio=[Audio(content=audio_bytes)],
    )
    pprint(run.content)
