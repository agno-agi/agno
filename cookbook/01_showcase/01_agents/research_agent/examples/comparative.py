"""
Comparative Research
====================

Demonstrates using the research agent for comparison tasks.

This example shows:
- Researching multiple options for comparison
- Extracting structured comparison data
- Using the agent for decision support

Prerequisites:
    export PARALLEL_API_KEY=your-api-key

Usage:
    python examples/comparative.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import research_topic  # noqa: E402

# ============================================================================
# Comparative Research Example
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Research Agent - Comparative Analysis")
    print("=" * 60)

    question = (
        "Compare Pinecone, Weaviate, and Chroma as vector databases for RAG "
        "applications. Consider: performance, pricing, ease of use, and features."
    )
    print(f"Question: {question}")
    print("Depth: standard")
    print()
    print("Researching...")
    print()

    try:
        report = research_topic(question, depth="standard")

        print("EXECUTIVE SUMMARY:")
        print("-" * 40)
        print(report.executive_summary)
        print()

        print("COMPARISON FINDINGS:")
        print("-" * 40)

        # Try to categorize findings by which product they mention
        products = ["pinecone", "weaviate", "chroma"]
        categorized: dict[str, list] = {p: [] for p in products}
        general: list = []

        for finding in report.key_findings:
            statement_lower = finding.statement.lower()
            matched = False
            for product in products:
                if product in statement_lower:
                    categorized[product].append(finding)
                    matched = True
                    break
            if not matched:
                general.append(finding)

        # Print general findings first
        if general:
            print("\nGENERAL:")
            for finding in general:
                print(f"  [{finding.confidence}] {finding.statement}")

        # Print by product
        for product in products:
            findings = categorized[product]
            if findings:
                print(f"\n{product.upper()}:")
                for finding in findings:
                    print(f"  [{finding.confidence}] {finding.statement}")

        print()
        print("RECOMMENDATIONS:")
        print("-" * 40)
        if report.recommendations:
            for rec in report.recommendations:
                print(f"  - {rec}")
        else:
            print("  No specific recommendations provided.")

        print()
        print(f"SOURCES ({len(report.sources)}):")
        print("-" * 40)
        for source in report.sources[:5]:  # Show top 5
            print(f"  [{source.credibility}] {source.title}")
        if len(report.sources) > 5:
            print(f"  ... and {len(report.sources) - 5} more sources")

        if report.gaps:
            print()
            print("AREAS FOR FURTHER RESEARCH:")
            print("-" * 40)
            for gap in report.gaps:
                print(f"  - {gap}")

    except Exception as e:
        print(f"Error: {e}")
