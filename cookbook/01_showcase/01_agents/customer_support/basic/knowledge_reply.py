"""
Knowledge Reply
================

Demonstrates retrieval-augmented response generation where the agent:
1. Always searches the knowledge base first
2. Cites specific sources in the response
3. Falls back gracefully when no relevant docs found

This example shows the RAG pattern in action for customer support.

Prerequisites:
    1. PostgreSQL running: ./cookbook/scripts/run_pgvector.sh
    2. Knowledge loaded: python scripts/load_knowledge.py

Usage:
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/basic/knowledge_reply.py
"""

from agent import agent

KB_QUERIES = [
    {
        "query": "When should I escalate a ticket to Tier 2 support?",
        "expected_source": "escalation_guidelines.md",
        "description": "Should cite escalation guidelines document",
    },
    {
        "query": "What are the SLA response times for P1 critical tickets?",
        "expected_source": "sla_guidelines.md",
        "description": "Should cite SLA guidelines document",
    },
    {
        "query": "How should I respond to a frustrated customer who has contacted us multiple times?",
        "expected_source": "response_templates.md",
        "description": "Should cite response templates with empathy statements",
    },
    {
        "query": "How do I classify and prioritize incoming support tickets?",
        "expected_source": "ticket_triage.md",
        "description": "Should cite ticket triage document",
    },
]


def run_knowledge_first_examples():
    """Run queries that demonstrate knowledge-first responses."""
    print("=" * 60)
    print("Knowledge-First Reply Demo")
    print("=" * 60)
    print()
    print("This demo shows how the agent retrieves from the knowledge base")
    print("before generating responses, and cites sources in its answers.")
    print()

    for i, item in enumerate(KB_QUERIES, 1):
        print(f"Query {i}: {item['query'][:50]}...")
        print("-" * 40)
        print(f"Expected source: {item['expected_source']}")
        print(f"Description: {item['description']}")
        print()
        print("Agent Response:")
        print("-" * 20)

        try:
            agent.print_response(item["query"], stream=True)
        except Exception as e:
            print(f"Error: {e}")

        print()
        print("=" * 60)
        print()

        if i < len(KB_QUERIES):
            try:
                input("Press Enter for next query...")
            except KeyboardInterrupt:
                print("\nExiting...")
                return
            print()


def test_no_knowledge_fallback():
    """Test behavior when no relevant KB docs exist."""
    print("=" * 60)
    print("Fallback Behavior Test")
    print("=" * 60)
    print()
    print("Testing query with no matching KB content:")
    print()

    query = "Can you help me configure AWS Lambda integration with custom VPC settings?"
    print(f"Query: {query}")
    print()
    print("Agent Response:")
    print("-" * 20)

    try:
        agent.print_response(query, stream=True)
    except Exception as e:
        print(f"Error: {e}")

    print()
    print("Note: The agent should acknowledge when information is not in the KB")
    print("and suggest alternatives (like consulting official documentation).")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Knowledge-First Reply Demo")
    parser.add_argument(
        "--fallback", action="store_true", help="Test fallback behavior only"
    )
    args = parser.parse_args()

    if args.fallback:
        test_no_knowledge_fallback()
    else:
        run_knowledge_first_examples()
