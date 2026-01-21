"""
Research Agent Schemas
======================

Pydantic models for structured research reports.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ============================================================================
# Source Schema
# ============================================================================
class Source(BaseModel):
    """A source consulted during research."""

    url: str = Field(description="Source URL")
    title: str = Field(description="Page or article title")
    snippet: str = Field(description="Relevant excerpt from the source")
    credibility: str = Field(description="high, medium, low based on domain reputation")
    accessed_at: datetime = Field(
        default_factory=datetime.now, description="When the source was accessed"
    )


# ============================================================================
# Finding Schema
# ============================================================================
class Finding(BaseModel):
    """A research finding supported by sources."""

    statement: str = Field(description="The finding or fact")
    sources: list[str] = Field(description="URLs that support this finding")
    confidence: str = Field(description="high, medium, low")


# ============================================================================
# Research Report Schema
# ============================================================================
class ResearchReport(BaseModel):
    """Structured research report with findings and citations."""

    question: str = Field(description="Original research question")
    executive_summary: str = Field(description="2-3 sentence overview")
    key_findings: list[Finding] = Field(description="Main discoveries")
    methodology: str = Field(description="How research was conducted")
    sources: list[Source] = Field(description="All sources consulted")
    gaps: list[str] = Field(
        default_factory=list, description="Areas needing more research"
    )
    recommendations: list[str] = Field(
        default_factory=list, description="Suggested next steps"
    )
    search_queries_used: list[str] = Field(
        default_factory=list, description="Search queries executed"
    )
    research_depth: str = Field(description="quick, standard, comprehensive")
    total_sources_consulted: Optional[int] = Field(
        default=None, description="Number of sources reviewed"
    )
