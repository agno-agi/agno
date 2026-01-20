"""
Startup Analysis
================

Demonstrates comprehensive startup due diligence.

Prerequisites:
    export SGAI_API_KEY=your-scrapegraph-api-key
    export OPENAI_API_KEY=your-openai-api-key

Usage:
    python examples/analyze_startup.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import startup_analyst  # noqa: E402

# ============================================================================
# Startup Analysis Example
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Startup Analyst - Full Analysis")
    print("=" * 60)

    company_url = "https://x.ai"
    print(f"Company: {company_url}")
    print()
    print("Performing comprehensive analysis...")
    print("(This may take a moment as we crawl the website)")
    print()

    try:
        startup_analyst.print_response(
            f"Perform a comprehensive startup intelligence analysis on {company_url}",
            stream=True,
        )
    except Exception as e:
        print(f"Error: {e}")
        print()
        print("Note: This example requires ScrapeGraph API credentials.")
        print("Set SGAI_API_KEY environment variable to use this agent.")
