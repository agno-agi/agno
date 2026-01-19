"""
Basic Knowledge Query
=====================

Simple Q&A against the company knowledge base.
Demonstrates single-turn question answering with source citations.

Run:
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/knowledge_agent/examples/01_basic_query.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_parent = Path(__file__).parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from agent import knowledge_agent  # noqa: E402

# ============================================================================
# Example Queries
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Basic Knowledge Query")
    print("=" * 60)
    print()

    # Ask a simple policy question
    print("Question: What is the PTO policy?")
    print("-" * 40)
    knowledge_agent.print_response(
        "What is the PTO policy? How many days do I get?",
        stream=True,
    )

    print()
    print("=" * 60)
    print()

    # Ask about development setup
    print("Question: How do I set up my development environment?")
    print("-" * 40)
    knowledge_agent.print_response(
        "How do I set up my development environment?",
        stream=True,
    )

    print()
    print("=" * 60)
    print()

    # Ask about a product feature
    print("Question: How do I add a new user to the platform?")
    print("-" * 40)
    knowledge_agent.print_response(
        "How do I add a new user to the platform?",
        stream=True,
    )

    # Uncomment for interactive mode
    # knowledge_agent.cli(stream=True)
