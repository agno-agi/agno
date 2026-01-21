"""
Trending Topic Analysis
=======================

Demonstrates analyzing sentiment around a trending topic or hashtag.

Prerequisites:
    Set X API credentials:
    export X_BEARER_TOKEN=your-bearer-token

Usage:
    python examples/trending_topic.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import social_media_agent  # noqa: E402

# ============================================================================
# Trending Topic Example
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Social Media Analyst - Trending Topic")
    print("=" * 60)

    topic = "AI agents"
    print(f"Topic: {topic}")
    print("Analyzing trending discussion...")
    print()

    try:
        social_media_agent.print_response(
            f"Analyze the current discussion around '{topic}' on X (Twitter). "
            "Look at the past 15 tweets and identify: "
            "1) Main themes and narratives "
            "2) Sentiment distribution "
            "3) Key influencers or viral posts "
            "4) Emerging trends or concerns "
            "5) Opportunities for engagement",
            stream=True,
        )
    except Exception as e:
        print(f"Error: {e}")
        print()
        print("Note: This example requires X API credentials.")
        print("Set X_BEARER_TOKEN environment variable to use this agent.")
