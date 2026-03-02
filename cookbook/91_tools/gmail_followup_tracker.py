"""
Gmail Follow-Up Tracker
=======================
Finds sent emails that never received a reply and drafts follow-ups.

The agent chains: search_threads (find sent threads with from:me) ->
get_thread (check for replies) -> draft_email (create follow-up drafts
for unanswered messages).

Key concepts:
- Multi-step reasoning: agent must compare sender vs user email per thread
- add_datetime_to_context: agent calculates days_waiting from message dates
- output_schema: structured report of pending follow-ups

Compare with: gmail_draft_reply.py for single-thread reply drafting.

Setup: See gmail_tools.py for Google OAuth credential setup.
Run: pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
"""

from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.gmail import GmailTools
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Output Schema
# ---------------------------------------------------------------------------


class PendingFollowUp(BaseModel):
    thread_id: str = Field(..., description="Gmail thread ID")
    subject: str = Field(..., description="Original email subject")
    recipient: str = Field(..., description="Who the email was sent to")
    sent_date: str = Field(..., description="When the original email was sent")
    days_waiting: int = Field(..., description="Days since the email was sent")
    draft_created: bool = Field(
        default=False, description="Whether a follow-up draft was created"
    )


class FollowUpReport(BaseModel):
    total_checked: int = Field(..., description="Number of sent threads checked")
    needs_followup: List[PendingFollowUp] = Field(
        default_factory=list, description="Threads that need follow-up"
    )
    summary: str = Field(..., description="Brief summary of findings")


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    name="Follow-Up Tracker",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GmailTools(search_threads=True, get_thread=True, draft_email=True)],
    instructions=[
        "Use search_threads with 'from:me' to find sent threads, then check if the last message is from you.",
        "A thread needs follow-up if the LAST message is FROM the user (no reply received).",
        "Compare the date of the last message against today to calculate days_waiting.",
        "Keep follow-up drafts short: reference the original subject and ask if they had a chance to review.",
        "Report all findings in the output schema.",
    ],
    output_schema=FollowUpReport,
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "Check my sent emails from the last week and identify any that need a follow-up. "
        "Draft follow-ups for emails waiting more than 3 days.",
        stream=True,
    )

    # Check follow-ups for a specific recipient
    # agent.print_response(
    #     "Check if I have any unanswered emails to john@example.com from the past 2 weeks",
    #     stream=True,
    # )
