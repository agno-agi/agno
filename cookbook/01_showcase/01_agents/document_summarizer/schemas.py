"""
Document Summarizer Schemas
===========================

Pydantic models for structured document summaries.
"""

from typing import Optional

from pydantic import BaseModel, Field


# ============================================================================
# Entity Schema
# ============================================================================
class Entity(BaseModel):
    """An entity extracted from the document."""

    name: str = Field(description="Entity name")
    type: str = Field(
        description="Type: person, organization, date, location, technology, other"
    )
    context: Optional[str] = Field(
        default=None, description="Brief context about the entity"
    )


# ============================================================================
# Action Item Schema
# ============================================================================
class ActionItem(BaseModel):
    """An action item or task identified in the document."""

    task: str = Field(description="The action to be taken")
    owner: Optional[str] = Field(
        default=None, description="Who should do it, if mentioned"
    )
    deadline: Optional[str] = Field(
        default=None, description="When it should be done, if mentioned"
    )
    priority: Optional[str] = Field(
        default=None, description="high, medium, low if determinable"
    )


# ============================================================================
# Document Summary Schema
# ============================================================================
class DocumentSummary(BaseModel):
    """Structured summary of a document."""

    title: str = Field(description="Document title or inferred subject")
    document_type: str = Field(
        description="Type: report, article, meeting_notes, research_paper, email, other"
    )
    summary: str = Field(description="Concise summary in 1-3 paragraphs")
    key_points: list[str] = Field(description="3-7 main takeaways as bullet points")
    entities: list[Entity] = Field(
        default_factory=list, description="Key entities mentioned"
    )
    action_items: list[ActionItem] = Field(
        default_factory=list, description="Tasks or next steps identified"
    )
    word_count: int = Field(description="Original document word count")
    confidence: float = Field(
        description="Confidence in summary accuracy 0-1", ge=0.0, le=1.0
    )
