"""
Multi-Turn Conversation
=======================

Demonstrates follow-up questions and conversation context.
The agent remembers previous questions and builds on earlier answers.

Run:
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/knowledge_agent/examples/02_conversation.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_parent = Path(__file__).parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from agent import knowledge_agent  # noqa: E402

# ============================================================================
# Conversation Flow
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Multi-Turn Conversation")
    print("=" * 60)
    print()

    # First question - broad topic
    print("Question 1: What should I do during my first week?")
    print("-" * 40)
    knowledge_agent.print_response(
        "I just started at the company. What should I do during my first week?",
        stream=True,
    )

    print()
    print("=" * 60)
    print()

    # Follow-up - drilling down
    print("Question 2: (Follow-up) Tell me more about the compliance training")
    print("-" * 40)
    knowledge_agent.print_response(
        "Tell me more about the compliance training I need to complete.",
        stream=True,
    )

    print()
    print("=" * 60)
    print()

    # Another follow-up - related topic
    print("Question 3: (Follow-up) Who is my onboarding buddy?")
    print("-" * 40)
    knowledge_agent.print_response(
        "What is an onboarding buddy and what do they help with?",
        stream=True,
    )

    print()
    print("=" * 60)
    print()

    # Switch topics but keep context
    print("Question 4: Now tell me about the engineering setup")
    print("-" * 40)
    knowledge_agent.print_response(
        "Since I'm an engineer, what do I need to do to set up my environment?",
        stream=True,
    )

    # Uncomment for interactive mode
    # knowledge_agent.cli(stream=True)
