"""
Brand Sentiment Analysis
========================

Demonstrates analyzing brand sentiment on X (Twitter).

Prerequisites:
    Set X API credentials:
    export X_BEARER_TOKEN=your-bearer-token

Usage:
    python examples/brand_analysis.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import social_media_agent  # noqa: E402

# ============================================================================
# Brand Analysis Example
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Social Media Analyst - Brand Analysis")
    print("=" * 60)

    brand = "Anthropic"
    print(f"Brand: {brand}")
    print("Analyzing recent tweets...")
    print()

    try:
        social_media_agent.print_response(
            f"Analyze the sentiment of {brand} and Claude AI on X (Twitter) for the past 10 tweets",
            stream=True,
        )
    except Exception as e:
        print(f"Error: {e}")
        print()
        print("Note: This example requires X API credentials.")
        print("Set X_BEARER_TOKEN environment variable to use this agent.")
