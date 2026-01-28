"""
Triage Queue
============

Demonstrates processing multiple tickets by priority.
Simulates a support queue with tickets at different priority levels.

The agent will:
1. Analyze each ticket for type and sentiment
2. Assign priority based on classification
3. Process high-priority tickets first
4. Generate appropriate responses

Prerequisites:
    1. PostgreSQL running: ./cookbook/scripts/run_pgvector.sh
    2. Knowledge loaded: python scripts/load_knowledge.py

Usage:
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/advanced/triage_queue.py
"""

from agent import agent

TICKET_QUEUE = [
    {
        "id": 1001,
        "subject": "Question about Teams",
        "description": "Hi, I was wondering how to set up a multi-agent team. Is there documentation on this?",
        "expected_type": "question",
        "expected_sentiment": "calm",
        "expected_priority": "P4",
    },
    {
        "id": 1002,
        "subject": "URGENT: Production down",
        "description": "Our production system is completely down. All agent calls are failing with 500 errors. We have a major customer demo in 1 hour. Please help ASAP!",
        "expected_type": "bug",
        "expected_sentiment": "urgent",
        "expected_priority": "P1",
    },
    {
        "id": 1003,
        "subject": "Feature request: Slack integration",
        "description": "Would be great if Agno had native Slack integration for notifications when agent runs complete. Just a suggestion for the roadmap.",
        "expected_type": "feature",
        "expected_sentiment": "calm",
        "expected_priority": "P4",
    },
    {
        "id": 1004,
        "subject": "Still having the same issue",
        "description": "I reported this last week and was told it would be fixed. The knowledge base search is STILL returning empty results. This is the third time I'm contacting support about this.",
        "expected_type": "bug",
        "expected_sentiment": "frustrated",
        "expected_priority": "P2",
    },
    {
        "id": 1005,
        "subject": "Billing question",
        "description": "Can you explain the difference between the Pro and Enterprise plans? Specifically interested in the API rate limits.",
        "expected_type": "account",
        "expected_sentiment": "calm",
        "expected_priority": "P4",
    },
]


def triage_tickets():
    """Triage and process the ticket queue."""
    print("=" * 60)
    print("Ticket Triage Queue")
    print("=" * 60)
    print()
    print(f"Processing {len(TICKET_QUEUE)} tickets...")
    print()

    print("Phase 1: Classification")
    print("-" * 40)

    classifications = []
    for ticket in TICKET_QUEUE:
        prompt = f"""
        Analyze this support ticket and classify it.
        Return ONLY a brief classification, no response yet.

        Ticket #{ticket["id"]}: {ticket["subject"]}
        ---
        {ticket["description"]}
        ---

        Provide:
        1. Type: question, bug, feature, or account
        2. Sentiment: calm, frustrated, or urgent
        3. Priority: P1 (critical), P2 (high), P3 (medium), P4 (low)
        """

        try:
            response = agent.run(prompt)
            content = response.content or ""
            print(f"Ticket #{ticket['id']}: {ticket['subject'][:30]}...")
            print(f"  Classification: {content[:100]}...")
            print(
                f"  Expected: {ticket['expected_priority']} - {ticket['expected_type']} - {ticket['expected_sentiment']}"
            )
            print()

            classifications.append(
                {
                    "ticket": ticket,
                    "classification": content,
                }
            )
        except Exception as e:
            print(f"  Error classifying ticket #{ticket['id']}: {e}")
            print()

    print()
    print("Phase 2: Priority Processing")
    print("-" * 40)
    print()
    print("Processing tickets in priority order (P1 first)...")
    print()

    sorted_tickets = sorted(
        classifications, key=lambda x: x["ticket"]["expected_priority"]
    )

    for item in sorted_tickets[:3]:
        ticket = item["ticket"]
        print(f"Processing Ticket #{ticket['id']} ({ticket['expected_priority']})")
        print(f"Subject: {ticket['subject']}")
        print("-" * 20)

        prompt = f"""
        Generate a customer response for this ticket.
        Use appropriate empathy based on sentiment.

        Ticket #{ticket["id"]}: {ticket["subject"]}
        Priority: {ticket["expected_priority"]}
        Sentiment: {ticket["expected_sentiment"]}
        ---
        {ticket["description"]}
        """

        try:
            agent.print_response(prompt, stream=True)
        except Exception as e:
            print(f"Error: {e}")

        print()
        print("=" * 60)
        print()


def show_queue_stats():
    """Display statistics about the ticket queue."""
    print("Queue Statistics")
    print("-" * 40)

    type_counts = {}
    sentiment_counts = {}
    priority_counts = {}

    for ticket in TICKET_QUEUE:
        t = ticket["expected_type"]
        s = ticket["expected_sentiment"]
        p = ticket["expected_priority"]

        type_counts[t] = type_counts.get(t, 0) + 1
        sentiment_counts[s] = sentiment_counts.get(s, 0) + 1
        priority_counts[p] = priority_counts.get(p, 0) + 1

    print(f"Total tickets: {len(TICKET_QUEUE)}")
    print()
    print("By Type:")
    for t, count in sorted(type_counts.items()):
        print(f"  {t}: {count}")
    print()
    print("By Sentiment:")
    for s, count in sorted(sentiment_counts.items()):
        print(f"  {s}: {count}")
    print()
    print("By Priority:")
    for p, count in sorted(priority_counts.items()):
        print(f"  {p}: {count}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ticket Triage Queue Demo")
    parser.add_argument(
        "--stats", action="store_true", help="Show queue statistics only"
    )
    args = parser.parse_args()

    if args.stats:
        show_queue_stats()
    else:
        triage_tickets()
