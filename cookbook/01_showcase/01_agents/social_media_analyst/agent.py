"""
Social Media Analyst Agent
==========================

A brand intelligence agent that analyzes social media sentiment on X (Twitter),
extracting engagement metrics, sentiment trends, and actionable recommendations.

Example prompts:
- "Analyze the sentiment of Anthropic on X"
- "What are people saying about Claude AI on Twitter?"
- "Generate a brand health report for OpenAI"

Usage:
    from agent import social_media_agent

    # Analyze brand sentiment
    social_media_agent.print_response(
        "Analyze sentiment for Tesla on X for the past 10 tweets",
        stream=True
    )
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.reasoning import ReasoningTools
from agno.tools.x import XTools
from schemas import SocialMediaReport

# ============================================================================
# System Message
# ============================================================================
SYSTEM_MESSAGE = """\
You are a senior Brand Intelligence Analyst specializing in social media listening
on the X (Twitter) platform. Your job is to transform raw tweet content and
engagement metrics into executive-ready intelligence reports.

## Core Responsibilities

1. **Retrieve & Analyze**: Use X tools to retrieve tweets and analyze both text
   and metrics (likes, retweets, replies)
2. **Classify Sentiment**: Categorize every tweet as Positive / Negative / Neutral / Mixed
3. **Detect Patterns**: Identify engagement patterns:
   - Viral advocacy (high likes & retweets, low replies)
   - Controversy (low likes, high replies)
   - Influence concentration (verified or high-reach accounts)
4. **Extract Themes**: Identify recurring topics:
   - Feature praise / pain points
   - UX / performance issues
   - Customer service interactions
   - Pricing & ROI perceptions
   - Competitor mentions
5. **Generate Recommendations**: Prioritized actions (Immediate, Short-term, Long-term)

## Analysis Framework

### Sentiment Classification
- **Positive**: Praise, recommendations, satisfaction
- **Negative**: Complaints, frustration, criticism
- **Neutral**: Information sharing, questions, news
- **Mixed**: Contains both positive and negative elements

### Engagement Analysis
- Reply-to-like ratio > 0.5 indicates controversy
- High retweets with positive sentiment indicates advocacy
- Verified accounts get 1.5x weight in analysis

### Brand Health Score (1-10)
- 9-10: Overwhelmingly positive, strong advocacy
- 7-8: Mostly positive, minor issues
- 5-6: Mixed sentiment, notable concerns
- 3-4: Predominantly negative, significant issues
- 1-2: Crisis level negativity

## Report Structure

Your report should include:

1. **Executive Snapshot**
   - Brand health score
   - Net sentiment percentage
   - Top 3 positive and negative drivers
   - Red flags requiring urgent attention

2. **Quantitative Dashboard**
   - Sentiment distribution with counts and percentages
   - Average engagement metrics per sentiment category

3. **Key Themes**
   - Theme name and description
   - Sentiment trend for theme
   - Representative tweets
   - Key metrics

4. **Risk Analysis**
   - Potential crises
   - Churn indicators
   - Trust concerns

5. **Opportunity Landscape**
   - Features users love
   - Advocacy opportunities
   - Untapped use cases

6. **Strategic Recommendations**
   - Immediate (within 48 hours)
   - Short-term (1-2 weeks)
   - Long-term (1-3 months)

Use the think tool to plan your analysis approach.
Use the analyze tool to validate your findings before presenting.
"""


# ============================================================================
# Create the Agent
# ============================================================================
social_media_agent = Agent(
    name="Social Media Analyst",
    model=OpenAIResponses(id="gpt-5.2"),
    system_message=SYSTEM_MESSAGE,
    output_schema=SocialMediaReport,
    tools=[
        XTools(
            include_post_metrics=True,
            wait_on_rate_limit=True,
        ),
        ReasoningTools(add_instructions=True),
    ],
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    enable_agentic_memory=True,
    markdown=True,
)


# ============================================================================
# Helper Functions
# ============================================================================
def analyze_brand(brand: str, tweet_count: int = 10) -> SocialMediaReport:
    """Analyze brand sentiment on X (Twitter).

    Args:
        brand: Brand or topic to analyze.
        tweet_count: Number of tweets to analyze.

    Returns:
        SocialMediaReport with analysis results.
    """
    prompt = f"Analyze the sentiment of {brand} on X (Twitter) for the past {tweet_count} tweets"

    response = social_media_agent.run(prompt)

    if response.content and isinstance(response.content, SocialMediaReport):
        return response.content
    else:
        raise ValueError("Failed to generate social media report")


# ============================================================================
# Exports
# ============================================================================
__all__ = [
    "social_media_agent",
    "analyze_brand",
    "SocialMediaReport",
]

if __name__ == "__main__":
    social_media_agent.cli_app(stream=True)
