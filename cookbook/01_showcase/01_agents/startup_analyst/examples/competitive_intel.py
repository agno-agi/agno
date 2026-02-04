"""
Competitive Intelligence
========================

Demonstrates comparing multiple startups in the same space.

Prerequisites:
    export SGAI_API_KEY=your-scrapegraph-api-key
    export OPENAI_API_KEY=your-openai-api-key

Usage:
    python examples/competitive_intel.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import startup_analyst  # noqa: E402

# ============================================================================
# Competitive Intelligence Example
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Startup Analyst - Competitive Intelligence")
    print("=" * 60)

    companies = [
        "https://anthropic.com",
        "https://openai.com",
    ]
    print(f"Companies: {', '.join(companies)}")
    print()
    print("Performing competitive analysis...")
    print()

    try:
        startup_analyst.print_response(
            f"Compare these AI companies and provide a competitive analysis: "
            f"{', '.join(companies)}. "
            "Focus on: "
            "1) Business model differences "
            "2) Product positioning "
            "3) Team and leadership "
            "4) Funding and resources "
            "5) Competitive advantages of each",
            stream=True,
        )
    except Exception as e:
        print(f"Error: {e}")
        print()
        print("Note: This example requires ScrapeGraph API credentials.")
        print("Set SGAI_API_KEY environment variable to use this agent.")
