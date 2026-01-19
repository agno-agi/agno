"""
Competitor Comparison
=====================

Demonstrates comparing sentiment across multiple brands.

Prerequisites:
    Set X API credentials:
    export X_BEARER_TOKEN=your-bearer-token

Usage:
    python examples/02_competitor_compare.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import social_media_agent  # noqa: E402

# ============================================================================
# Competitor Comparison Example
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Social Media Analyst - Competitor Comparison")
    print("=" * 60)

    brands = ["OpenAI", "Anthropic", "Google AI"]
    print(f"Brands: {', '.join(brands)}")
    print("Analyzing and comparing sentiment...")
    print()

    try:
        social_media_agent.print_response(
            f"Compare the sentiment and public perception of {', '.join(brands)} "
            "on X (Twitter). Analyze 5 recent tweets for each and provide a "
            "comparative analysis of brand health, key themes, and recommendations.",
            stream=True,
        )
    except Exception as e:
        print(f"Error: {e}")
        print()
        print("Note: This example requires X API credentials.")
        print("Set X_BEARER_TOKEN environment variable to use this agent.")
