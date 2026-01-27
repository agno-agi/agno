"""
Customer Support Agent - Output Schemas
=======================================

Pydantic models for ticket classification and resolution.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ============================================================================
# Ticket Classification
# ============================================================================
class TicketType(str, Enum):
    """Category of support ticket based on content."""

    QUESTION = "question"  # How do I..., What is...
    BUG = "bug"  # Error, not working, broken
    FEATURE = "feature"  # Can you add, suggestion
    ACCOUNT = "account"  # Billing, access, login


class Sentiment(str, Enum):
    """Customer sentiment level detected from ticket."""

    CALM = "calm"  # Neutral tone, no urgency
    FRUSTRATED = "frustrated"  # Still not working, again, multiple times
    URGENT = "urgent"  # ASAP, critical, blocking, production


# ============================================================================
# Ticket Analysis
# ============================================================================
class TicketAnalysis(BaseModel):
    """Structured analysis of a support ticket."""

    ticket_id: int = Field(description="Zendesk ticket ID")
    ticket_type: TicketType = Field(description="Classified type of ticket")
    sentiment: Sentiment = Field(description="Detected customer sentiment")
    summary: str = Field(description="Brief summary of the issue")
    key_entities: list[str] = Field(
        default_factory=list, description="Products, features, or terms mentioned"
    )


# ============================================================================
# Resolution
# ============================================================================
class SourceReference(BaseModel):
    """Reference to a knowledge base source."""

    document: str = Field(description="Document name or URL")
    excerpt: str = Field(description="Relevant excerpt from source")
    relevance: float = Field(description="Relevance score 0-1")


class Resolution(BaseModel):
    """Complete resolution for a support ticket."""

    ticket_id: int = Field(description="Zendesk ticket ID")
    ticket_type: TicketType = Field(description="Classified type")
    sentiment: Sentiment = Field(description="Customer sentiment")
    answer: str = Field(description="Response to send to customer")
    sources: list[SourceReference] = Field(
        default_factory=list, description="Knowledge base sources used"
    )
    confidence: float = Field(
        description="Confidence in the answer (0-1)", ge=0.0, le=1.0
    )
    needs_clarification: bool = Field(
        default=False, description="Whether HITL clarification is needed"
    )
    clarification_reason: Optional[str] = Field(
        default=None, description="Why clarification is needed"
    )
    suggested_status: str = Field(
        default="pending", description="Suggested ticket status after response"
    )


# ============================================================================
# HITL Clarification
# ============================================================================
class ClarificationRequest(BaseModel):
    """Request for human clarification."""

    ticket_id: int = Field(description="Ticket needing clarification")
    question: str = Field(description="What needs to be clarified")
    options: list[str] = Field(
        default_factory=list, description="Possible answers if known"
    )
    context: str = Field(description="Relevant context from the ticket")


# ============================================================================
# Exports
# ============================================================================
__all__ = [
    "TicketType",
    "Sentiment",
    "TicketAnalysis",
    "SourceReference",
    "Resolution",
    "ClarificationRequest",
]
