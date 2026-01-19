"""
Quick Scan
==========

Demonstrates a quick overview analysis of a startup.

Prerequisites:
    export SGAI_API_KEY=your-scrapegraph-api-key
    export OPENAI_API_KEY=your-openai-api-key

Usage:
    python examples/03_quick_scan.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import startup_analyst  # noqa: E402

# ============================================================================
# Quick Scan Example
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Startup Analyst - Quick Scan")
    print("=" * 60)

    company_url = "https://agno.com"
    print(f"Company: {company_url}")
    print()
    print("Performing quick scan...")
    print()

    try:
        startup_analyst.print_response(
            f"Provide a quick overview of the company at {company_url}. "
            "Focus on: "
            "1) What they do (one paragraph) "
            "2) Target market "
            "3) Key products/services "
            "4) One-line investment thesis",
            stream=True,
        )
    except Exception as e:
        print(f"Error: {e}")
        print()
        print("Note: This example requires ScrapeGraph API credentials.")
        print("Set SGAI_API_KEY environment variable to use this agent.")
