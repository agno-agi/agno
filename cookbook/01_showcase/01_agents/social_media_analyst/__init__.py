"""
Social Media Analyst
====================

A brand intelligence agent that analyzes social media sentiment on X (Twitter),
extracting engagement metrics, sentiment trends, and actionable recommendations.

Example:
    from social_media_analyst import social_media_agent

    # Analyze brand sentiment
    social_media_agent.print_response(
        "Analyze sentiment for OpenAI on X",
        stream=True
    )
"""

from social_media_analyst.agent import social_media_agent

__all__ = [
    "social_media_agent",
]
