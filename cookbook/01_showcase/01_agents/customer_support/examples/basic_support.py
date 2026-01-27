"""
Basic Support
=============

Demonstrates the basic customer support workflow:
1. Fetch a ticket from Zendesk (or simulate one)
2. Classify the ticket type and sentiment
3. Search knowledge base for relevant information
4. Generate a response

Prerequisites:
    1. PostgreSQL running: ./cookbook/scripts/run_pgvector.sh
    2. Knowledge loaded: python scripts/load_knowledge.py
    3. API keys set: OPENAI_API_KEY, ZENDESK_* (optional)

Usage:
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/examples/basic_support.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import support_agent  # noqa: E402

# ============================================================================
# Example Queries
# ============================================================================
EXAMPLE_QUERIES = [
    # Question about the product
    "A customer is asking: How do I set up a knowledge base with PgVector?",
    # Frustrated customer with a bug
    "Ticket from customer (frustrated): I've tried three times but the agent keeps crashing when I add tools. This is blocking my demo tomorrow.",
    # Urgent production issue
    "URGENT: Customer reports their production agents are returning empty responses. They have a client presentation in 2 hours.",
]


def run_basic_examples():
    """Run the support agent on example queries."""
    print("=" * 60)
    print("Customer Support Agent - Basic Examples")
    print("=" * 60)
    print()

    for i, query in enumerate(EXAMPLE_QUERIES, 1):
        print(f"Example {i}:")
        print("-" * 40)
        print(f"Query: {query[:80]}...")
        print()

        try:
            support_agent.print_response(query, stream=True)
        except Exception as e:
            print(f"Error: {e}")

        print()
        print("=" * 60)
        print()


def interactive_mode():
    """Run the support agent in interactive mode."""
    print("=" * 60)
    print("Customer Support Agent - Interactive Mode")
    print("=" * 60)
    print()
    print("Enter ticket descriptions or support queries.")
    print("Type 'quit' to exit.")
    print()

    try:
        support_agent.cli_app(stream=True)
    except KeyboardInterrupt:
        print("\nExiting...")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Customer Support Agent Examples")
    parser.add_argument(
        "--interactive", "-i", action="store_true", help="Run in interactive mode"
    )
    args = parser.parse_args()

    if args.interactive:
        interactive_mode()
    else:
        run_basic_examples()
