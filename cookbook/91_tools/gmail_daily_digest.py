"""
Gmail Daily Digest
==================
Summarizes recent emails into a structured daily digest grouped by priority.

The agent fetches today's emails, classifies each by category and urgency,
and returns a structured report.

Key concepts:
- output_schema: Forces structured JSON output matching DailyDigest model
- add_datetime_to_context: Agent knows today's date for time-aware queries


Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Gmail API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent, saves token.json for reuse
"""

from typing import List, Literal

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.gmail import GmailTools
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Output Schema
# ---------------------------------------------------------------------------


class EmailDigestItem(BaseModel):
    subject: str = Field(..., description="Email subject line")
    sender: str = Field(..., description="Sender name or email")
    category: Literal["action_required", "fyi", "newsletter", "personal", "other"] = (
        Field(..., description="Email category based on content")
    )
    summary: str = Field(..., description="One-sentence summary of the email")
    priority: Literal["high", "medium", "low"] = Field(
        ..., description="Priority level based on urgency and importance"
    )


class DailyDigest(BaseModel):
    date: str = Field(..., description="Digest date in YYYY-MM-DD format")
    total_emails: int = Field(..., description="Total number of emails processed")
    action_required: List[EmailDigestItem] = Field(
        default_factory=list, description="Emails requiring action"
    )
    fyi: List[EmailDigestItem] = Field(
        default_factory=list, description="Informational emails"
    )
    newsletters: List[EmailDigestItem] = Field(
        default_factory=list, description="Newsletter and subscription emails"
    )
    personal: List[EmailDigestItem] = Field(
        default_factory=list, description="Personal emails"
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    name="Daily Digest Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GmailTools()],
    instructions=[
        "Categorize each email as action_required, fyi, newsletter, personal, or other.",
        "Assign priority: high for urgent/time-sensitive, medium for important, low for routine.",
        "Write a one-sentence summary for each email capturing the key point.",
        "Group results by category in the output schema.",
    ],
    output_schema=DailyDigest,
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "Give me a digest of today's emails, categorized by urgency",
        stream=True,
    )
