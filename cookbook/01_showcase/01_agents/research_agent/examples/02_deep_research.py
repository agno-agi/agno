"""
Deep Research
=============

Demonstrates comprehensive research mode for thorough investigations.

This example shows:
- Comprehensive depth for detailed research (10-15 sources)
- Multiple findings with cross-referenced sources
- Gap analysis and recommendations

Prerequisites:
    export PARALLEL_API_KEY=your-api-key

Usage:
    python examples/02_deep_research.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import research_topic  # noqa: E402

# ============================================================================
# Deep Research Example
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Research Agent - Comprehensive Research")
    print("=" * 60)

    question = "What are the best practices for building production-ready AI agents?"
    print(f"Question: {question}")
    print("Depth: comprehensive")
    print()
    print("Researching (this may take a moment)...")
    print()

    try:
        report = research_topic(question, depth="comprehensive")

        print("EXECUTIVE SUMMARY:")
        print("-" * 40)
        print(report.executive_summary)
        print()

        print("METHODOLOGY:")
        print("-" * 40)
        print(report.methodology)
        print()

        print(f"KEY FINDINGS ({len(report.key_findings)}):")
        print("-" * 40)
        for i, finding in enumerate(report.key_findings, 1):
            print(f"\n{i}. {finding.statement}")
            print(f"   Confidence: {finding.confidence}")
            print(f"   Sources: {len(finding.sources)}")
            for url in finding.sources[:2]:  # Show first 2 sources
                print(f"     - {url}")
            if len(finding.sources) > 2:
                print(f"     ... and {len(finding.sources) - 2} more")

        print()
        print(f"SOURCES ({len(report.sources)}):")
        print("-" * 40)

        # Group by credibility
        by_credibility: dict[str, list] = {"high": [], "medium": [], "low": []}
        for source in report.sources:
            by_credibility.get(source.credibility, by_credibility["medium"]).append(
                source
            )

        for level in ["high", "medium", "low"]:
            sources = by_credibility[level]
            if sources:
                print(f"\n{level.upper()} CREDIBILITY ({len(sources)}):")
                for source in sources[:3]:  # Show top 3 per level
                    print(f"  - {source.title}")
                    print(f"    {source.url}")

        if report.gaps:
            print()
            print("GAPS IDENTIFIED:")
            print("-" * 40)
            for gap in report.gaps:
                print(f"  - {gap}")

        if report.recommendations:
            print()
            print("RECOMMENDATIONS:")
            print("-" * 40)
            for rec in report.recommendations:
                print(f"  - {rec}")

        print()
        print("SEARCH QUERIES USED:")
        print("-" * 40)
        for query in report.search_queries_used:
            print(f"  - {query}")

    except Exception as e:
        print(f"Error: {e}")
