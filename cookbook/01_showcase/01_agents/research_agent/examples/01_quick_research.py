"""
Quick Research
==============

Demonstrates quick research mode for fast overviews.

This example shows:
- Using the research_topic helper function
- Quick depth for fast results (3-5 sources)
- Accessing structured report fields

Prerequisites:
    export PARALLEL_API_KEY=your-api-key

Usage:
    python examples/01_quick_research.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import research_topic  # noqa: E402

# ============================================================================
# Quick Research Example
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Research Agent - Quick Research")
    print("=" * 60)

    question = "What is RAG (Retrieval Augmented Generation) in AI?"
    print(f"Question: {question}")
    print("Depth: quick")
    print()
    print("Researching...")
    print()

    try:
        report = research_topic(question, depth="quick")

        print("EXECUTIVE SUMMARY:")
        print("-" * 40)
        print(report.executive_summary)
        print()

        print("KEY FINDINGS:")
        print("-" * 40)
        for i, finding in enumerate(report.key_findings, 1):
            print(f"{i}. [{finding.confidence}] {finding.statement}")
            if finding.sources:
                print(f"   Source: {finding.sources[0]}")
            print()

        print("SOURCES CONSULTED:")
        print("-" * 40)
        for source in report.sources:
            print(f"  [{source.credibility}] {source.title}")
            print(f"  URL: {source.url}")
            print()

        if report.gaps:
            print("GAPS IDENTIFIED:")
            print("-" * 40)
            for gap in report.gaps:
                print(f"  - {gap}")

    except Exception as e:
        print(f"Error: {e}")
