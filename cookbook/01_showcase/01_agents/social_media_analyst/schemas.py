"""
Social Media Analyst Schemas
============================

Pydantic models for structured social media analysis output.
"""

from pydantic import BaseModel, Field


# ============================================================================
# Output Schemas
# ============================================================================
class SentimentBreakdown(BaseModel):
    """Breakdown of sentiment across analyzed posts."""

    positive_count: int = Field(description="Number of positive posts")
    negative_count: int = Field(description="Number of negative posts")
    neutral_count: int = Field(description="Number of neutral posts")
    mixed_count: int = Field(description="Number of mixed sentiment posts")
    net_sentiment: float = Field(
        description="Net sentiment score: (positive - negative) / total"
    )


class ThemeAnalysis(BaseModel):
    """Analysis of a specific theme in the social media data."""

    theme: str = Field(description="Theme name or category")
    sentiment_trend: str = Field(description="Overall sentiment for this theme")
    post_count: int = Field(description="Number of posts in this theme")
    representative_posts: list[str] = Field(description="Example posts from this theme")
    key_insights: str = Field(description="Key insights about this theme")


class RiskItem(BaseModel):
    """Identified risk from social media analysis."""

    risk_type: str = Field(description="Type: crisis, churn, trust, reputation")
    description: str = Field(description="Description of the risk")
    severity: str = Field(description="Severity: high, medium, low")
    evidence: list[str] = Field(description="Posts that indicate this risk")


class Recommendation(BaseModel):
    """Actionable recommendation based on analysis."""

    timeframe: str = Field(description="Timeframe: immediate, short_term, long_term")
    action: str = Field(description="Recommended action to take")
    rationale: str = Field(description="Why this action is recommended")
    priority: str = Field(description="Priority: high, medium, low")


class SocialMediaReport(BaseModel):
    """Complete social media analysis report."""

    # Overview
    brand_or_topic: str = Field(description="Brand or topic analyzed")
    posts_analyzed: int = Field(description="Number of posts analyzed")
    analysis_period: str = Field(description="Time period of analysis")

    # Sentiment
    brand_health_score: float = Field(description="Brand health score (1-10)")
    sentiment: SentimentBreakdown = Field(description="Sentiment breakdown")

    # Drivers
    top_positive_drivers: list[str] = Field(
        description="Top factors driving positive sentiment"
    )
    top_negative_drivers: list[str] = Field(
        description="Top factors driving negative sentiment"
    )

    # Analysis
    themes: list[ThemeAnalysis] = Field(description="Thematic analysis")
    risks: list[RiskItem] = Field(description="Identified risks")
    opportunities: list[str] = Field(description="Identified opportunities")

    # Actions
    recommendations: list[Recommendation] = Field(
        description="Prioritized recommendations"
    )

    # Summary
    executive_summary: str = Field(description="Executive summary of findings")
