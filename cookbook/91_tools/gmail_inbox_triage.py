"""
Gmail Inbox Triage
==================
Classifies unread emails and applies labels to organize the inbox.

The agent reads unread emails, classifies each into a category,
and applies labels. Includes a read-only variant that classifies
without modifying the inbox.

Key concepts:
- Two agents: full triage (applies labels) vs classify-only (read-only)
- output_schema: Structured classification results

Compare with: gmail_daily_digest.py for read-only summarization.

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


class TriagedEmail(BaseModel):
    message_id: str = Field(..., description="Gmail message ID")
    subject: str = Field(..., description="Email subject")
    sender: str = Field(..., description="Sender email")
    label: Literal["Action-Required", "FYI", "Newsletter", "Scheduling", "Finance"] = (
        Field(..., description="Category label to apply")
    )
    reason: str = Field(..., description="Brief reason for classification")


class TriageResult(BaseModel):
    processed: int = Field(..., description="Number of emails processed")
    emails: List[TriagedEmail] = Field(
        default_factory=list, description="Classification results"
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Full triage: classifies AND applies labels (modifies mailbox)
agent = Agent(
    name="Inbox Triage Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GmailTools(modify_labels=True)],
    instructions=[
        "Classify each email into exactly one category: Action-Required, FYI, Newsletter, Scheduling, or Finance.",
        "Use modify_labels to apply the category label to each classified email by message_id.",
        "Only add the new category label -- do NOT remove existing labels.",
        "Return the classification results in the output schema.",
    ],
    output_schema=TriageResult,
    markdown=True,
)

# Read-only variant that classifies without modifying the inbox
classify_only_agent = Agent(
    name="Email Classifier",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GmailTools()],
    instructions=[
        "Classify each unread email into: Action-Required, FYI, Newsletter, Scheduling, or Finance.",
        "Do NOT apply any labels or modify emails -- only report classifications.",
    ],
    output_schema=TriageResult,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Safe: classify only, no labels applied
    classify_only_agent.print_response(
        "Classify my 10 most recent unread emails by category",
        stream=True,
    )

    # Full triage: classifies AND applies labels (modifies mailbox)
    # agent.print_response(
    #     "Triage my 10 most recent unread emails and label them by category",
    #     stream=True,
    # )
