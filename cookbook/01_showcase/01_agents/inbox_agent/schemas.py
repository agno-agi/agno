"""
Inbox Agent - Output Schemas
============================

Pydantic models for structured email triage and analysis responses.
"""

from typing import Optional

from pydantic import BaseModel, Field


# ============================================================================
# Email Summary
# ============================================================================
class EmailSummary(BaseModel):
    """Summary of a single email."""

    thread_id: str = Field(description="Gmail thread ID")
    message_id: str = Field(description="Gmail message ID")
    subject: str = Field(description="Email subject line")
    sender: str = Field(description="Sender email address")
    received_at: Optional[str] = Field(default=None, description="Date received")
    category: str = Field(
        description="Category: urgent, action_required, fyi, newsletter, spam"
    )
    priority: int = Field(description="Priority 1-5, 1 being highest")
    summary: str = Field(description="1-2 sentence summary of the email")
    action_items: list[str] = Field(
        default_factory=list, description="Action items if any"
    )
    suggested_response: Optional[str] = Field(
        default=None, description="Draft response if applicable"
    )


# ============================================================================
# Triage Report
# ============================================================================
class TriageReport(BaseModel):
    """Complete inbox triage report."""

    total_emails: int = Field(description="Total emails processed")
    urgent: list[EmailSummary] = Field(
        default_factory=list, description="Urgent emails requiring immediate attention"
    )
    action_required: list[EmailSummary] = Field(
        default_factory=list, description="Emails needing a response"
    )
    fyi: list[EmailSummary] = Field(
        default_factory=list, description="Informational emails"
    )
    newsletters: list[EmailSummary] = Field(
        default_factory=list, description="Newsletter and subscription emails"
    )
    archived_count: int = Field(default=0, description="Number auto-archived")
    executive_summary: str = Field(description="Overall inbox summary")


# ============================================================================
# Thread Summary
# ============================================================================
class ThreadSummary(BaseModel):
    """Summary of an email thread."""

    thread_id: str = Field(description="Gmail thread ID")
    subject: str = Field(description="Thread subject")
    participants: list[str] = Field(description="Email addresses in thread")
    message_count: int = Field(description="Number of messages")
    summary: str = Field(description="Summary of the conversation")
    key_points: list[str] = Field(description="Key discussion points")
    action_items: list[str] = Field(
        default_factory=list, description="Action items from thread"
    )
    open_questions: list[str] = Field(
        default_factory=list, description="Unanswered questions"
    )
    suggested_response: Optional[str] = Field(
        default=None, description="Suggested reply if needed"
    )


# ============================================================================
# Draft Response
# ============================================================================
class DraftResponse(BaseModel):
    """A drafted email response."""

    to: str = Field(description="Recipient email")
    subject: str = Field(description="Email subject")
    body: str = Field(description="Email body text")
    tone: str = Field(description="Tone: formal, friendly, urgent, apologetic")
    notes: Optional[str] = Field(
        default=None, description="Notes about the draft for the user"
    )


# ============================================================================
# Exports
# ============================================================================
__all__ = [
    "EmailSummary",
    "TriageReport",
    "ThreadSummary",
    "DraftResponse",
]
