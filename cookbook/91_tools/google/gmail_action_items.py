"""
Gmail Action Item Extractor
============================
Extracts action items from email threads and returns a structured checklist.

The agent reads a thread, identifies who needs to do what by when,
and returns structured action items. This is an LLM reasoning task --
no special tool needed, just get_thread + output_schema.

Key concepts:
- get_thread: Fetches full thread context for multi-message analysis
- output_schema: Forces structured action item extraction
- add_datetime_to_context: Agent knows today's date for deadline reasoning

Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Gmail API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent, saves token.json for reuse
"""

from typing import List, Literal, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.gmail import GmailTools
from pydantic import BaseModel, Field


class ActionItem(BaseModel):
    owner: str = Field(..., description="Person responsible (name or email)")
    task: str = Field(..., description="What needs to be done")
    deadline: Optional[str] = Field(
        None, description="Due date if mentioned, in YYYY-MM-DD format"
    )
    priority: Literal["high", "medium", "low"] = Field(
        ..., description="Priority based on urgency language and deadlines"
    )
    source_quote: str = Field(
        ..., description="Brief quote from the email that implies this action"
    )


class ThreadActionItems(BaseModel):
    thread_subject: str = Field(..., description="Thread subject line")
    participants: List[str] = Field(..., description="All people in the thread")
    action_items: List[ActionItem] = Field(
        default_factory=list, description="Extracted action items"
    )
    summary: str = Field(..., description="One-sentence summary of the thread")


agent = Agent(
    name="Action Item Extractor",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GmailTools()],
    instructions=[
        "Search for the requested thread, then use get_thread to read all messages.",
        "Extract action items from the FULL conversation -- check every message.",
        "An action item is anything someone is asked to do, agrees to do, or volunteers to do.",
        "Look for phrases like 'can you', 'please', 'I will', 'let's', 'by Friday', 'deadline'.",
        "If no deadline is stated, leave deadline as null -- do not guess.",
        "Set priority: high if deadline is soon or language is urgent, low for nice-to-haves.",
    ],
    output_schema=ThreadActionItems,
    add_datetime_to_context=True,
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response(
        "Find the most recent thread about a project or meeting and extract all action items",
        stream=True,
    )
