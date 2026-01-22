"""
Edge Cases and Uncertainty
==========================

Demonstrates how the agent handles:
- Questions with no clear answer in the knowledge base
- Ambiguous questions requiring clarification
- Multi-source synthesis

Run:
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/knowledge_agent/examples/edge_cases.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_parent = Path(__file__).parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from agent import knowledge_agent  # noqa: E402

# ============================================================================
# Edge Case Queries
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Edge Cases and Uncertainty Handling")
    print("=" * 60)
    print()

    # Question not in knowledge base
    print("Test 1: Question not in knowledge base")
    print("Question: What is the company stock ticker?")
    print("-" * 40)
    knowledge_agent.print_response(
        "What is the company stock ticker symbol?",
        stream=True,
    )

    print()
    print("=" * 60)
    print()

    # Ambiguous question
    print("Test 2: Ambiguous question")
    print("Question: What are the deadlines?")
    print("-" * 40)
    knowledge_agent.print_response(
        "What are the deadlines I should know about?",
        stream=True,
    )

    print()
    print("=" * 60)
    print()

    # Multi-source synthesis
    print("Test 3: Multi-source synthesis")
    print("Question: What communication channels do we use?")
    print("-" * 40)
    knowledge_agent.print_response(
        "What communication channels does the company use? "
        "I want to know about both general company channels and engineering-specific ones.",
        stream=True,
    )

    print()
    print("=" * 60)
    print()

    # Cross-document question
    print("Test 4: Cross-document question")
    print("Question: What do I need to do to be ready for my first on-call shift?")
    print("-" * 40)
    knowledge_agent.print_response(
        "I'm a new engineer. What do I need to do to be ready for my first on-call shift?",
        stream=True,
    )

    # Uncomment for interactive mode
    # knowledge_agent.cli(stream=True)
