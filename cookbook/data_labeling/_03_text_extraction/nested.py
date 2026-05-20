"""
Text Extraction - Nested
========================

Extract a list of nested sub-objects from text. The same shape used for
line items, meeting attendees, action items, citations, etc.

This example extracts action items from a meeting transcript.
"""

from typing import List, Optional

from agno.agent import Agent, RunOutput  # noqa
from agno.models.openai import OpenAIResponses
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class ActionItem(BaseModel):
    owner: str = Field(..., description="Person responsible, as named in the meeting")
    description: str = Field(..., description="What they committed to do")
    due_date: Optional[str] = Field(None, description="ISO yyyy-mm-dd if mentioned")


class Meeting(BaseModel):
    action_items: List[ActionItem]


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Extract action items from the meeting transcript. An action item is a
commitment a named person made during the meeting. Only include items that
are clearly assigned to a specific person; ignore vague group asks. If a
due date is not mentioned, leave it null.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=instructions,
    output_schema=Meeting,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    transcript = """\
Mike:  I'll send out the updated roadmap by Friday.
Sarah: Great. And I'll set up the kickoff with the design team next week.
Jess:  We should probably get budget approval at some point.
Mike:  Yeah. Let me draft the budget memo by end of next week so we can
       send it to finance.
"""
    run: RunOutput = agent.run(transcript)
    pprint(run.content)
