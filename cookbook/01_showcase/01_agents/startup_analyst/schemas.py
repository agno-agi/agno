"""
Startup Analyst Schemas
=======================

Pydantic models for structured startup analysis output.
"""

from typing import Optional

from pydantic import BaseModel, Field


# ============================================================================
# Supporting Models
# ============================================================================
class TeamMember(BaseModel):
    """Key team member information."""

    name: str = Field(description="Full name")
    role: str = Field(description="Job title or role")
    background: Optional[str] = Field(
        default=None, description="Brief background or expertise"
    )
    linkedin: Optional[str] = Field(default=None, description="LinkedIn profile URL")


class FundingRound(BaseModel):
    """Funding round information."""

    date: Optional[str] = Field(default=None, description="Date of funding round")
    amount: Optional[str] = Field(default=None, description="Amount raised")
    round_type: str = Field(description="Type: seed, series_a, series_b, etc.")
    investors: list[str] = Field(default_factory=list, description="List of investors")


class RiskAssessment(BaseModel):
    """Risk assessment item."""

    category: str = Field(
        description="Category: market, technology, team, financial, regulatory"
    )
    description: str = Field(description="Description of the risk")
    severity: str = Field(description="Severity: high, medium, low")
    mitigation: Optional[str] = Field(
        default=None, description="Potential mitigation strategy"
    )


# ============================================================================
# Main Report Model
# ============================================================================
class StartupReport(BaseModel):
    """Complete startup due diligence report."""

    # Company Basics
    company_name: str = Field(description="Company name")
    website: str = Field(description="Company website URL")
    founded: Optional[str] = Field(default=None, description="Year founded")
    location: Optional[str] = Field(default=None, description="Headquarters location")
    industry: Optional[str] = Field(default=None, description="Industry or sector")

    # Business Model
    value_proposition: str = Field(description="Core value proposition")
    business_model: str = Field(description="How the company makes money")
    revenue_streams: list[str] = Field(
        default_factory=list, description="Revenue streams"
    )
    target_market: str = Field(description="Target market and customer segments")

    # Product
    products_services: list[str] = Field(
        default_factory=list, description="Main products or services"
    )
    key_features: list[str] = Field(
        default_factory=list, description="Key product features"
    )
    technology_stack: Optional[str] = Field(
        default=None, description="Technology or platform details"
    )

    # Team
    team_size: Optional[str] = Field(default=None, description="Approximate team size")
    key_team: list[TeamMember] = Field(
        default_factory=list, description="Key team members"
    )

    # Financials
    funding_history: list[FundingRound] = Field(
        default_factory=list, description="Funding history"
    )
    total_raised: Optional[str] = Field(
        default=None, description="Total funding raised"
    )
    revenue_indicators: list[str] = Field(
        default_factory=list, description="Revenue or traction indicators"
    )

    # Analysis
    competitive_advantages: list[str] = Field(
        default_factory=list, description="Competitive advantages or moats"
    )
    competitors: list[str] = Field(
        default_factory=list, description="Known competitors"
    )
    risks: list[RiskAssessment] = Field(
        default_factory=list, description="Risk assessment"
    )
    opportunities: list[str] = Field(
        default_factory=list, description="Growth opportunities"
    )

    # Recommendations
    investment_thesis: str = Field(
        description="Summary investment thesis or partnership rationale"
    )
    due_diligence_focus: list[str] = Field(
        default_factory=list, description="Areas requiring further due diligence"
    )

    # Metadata
    confidence_score: float = Field(description="Confidence in analysis accuracy (0-1)")
    sources_used: list[str] = Field(
        default_factory=list, description="URLs and sources consulted"
    )
    executive_summary: str = Field(description="Executive summary of findings")
