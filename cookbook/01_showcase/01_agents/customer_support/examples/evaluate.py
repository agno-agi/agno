"""
Evaluate
========
Test queries to verify the agent and knowledge base are working.

Run:
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/examples/evaluate.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import create_support_agent

QUERIES = [
    "What are the SLA response times for P1 critical tickets?",
    "When should I escalate a ticket to Tier 2?",
    "How should I respond to a frustrated customer?",
]

if __name__ == "__main__":
    print("Agent Evaluation")
    print("=" * 50)

    agent = create_support_agent(
        customer_id="eval@example.com",
        ticket_id="eval_session",
    )

    for i, query in enumerate(QUERIES, 1):
        print(f"\n[{i}/{len(QUERIES)}] {query}")
        print("-" * 50)
        agent.print_response(query, stream=True)
