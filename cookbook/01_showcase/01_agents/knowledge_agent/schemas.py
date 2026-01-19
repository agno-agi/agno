"""
Internal Knowledge Agent - Output Schemas
=========================================

Pydantic models for structured knowledge agent responses.
"""

from typing import Optional

from pydantic import BaseModel, Field


# ============================================================================
# Source Reference
# ============================================================================
class SourceReference(BaseModel):
    """Reference to a source document used in the answer."""

    document: str = Field(description="Document name or title")
    section: Optional[str] = Field(
        default=None, description="Section or page reference"
    )
    relevance: float = Field(description="Relevance score 0-1")
    excerpt: str = Field(description="Relevant excerpt from source")


# ============================================================================
# Knowledge Answer
# ============================================================================
class KnowledgeAnswer(BaseModel):
    """Structured answer from the knowledge agent."""

    question: str = Field(description="Original question asked")
    answer: str = Field(description="Synthesized answer from knowledge base")
    sources: list[SourceReference] = Field(
        description="Sources used to construct the answer"
    )
    confidence: str = Field(description="Confidence level: high, medium, or low")
    related_topics: list[str] = Field(
        default_factory=list, description="Suggested follow-up topics"
    )
    clarification_needed: Optional[str] = Field(
        default=None,
        description="If answer is uncertain, what clarification would help",
    )


# ============================================================================
# Exports
# ============================================================================
__all__ = [
    "SourceReference",
    "KnowledgeAnswer",
]
