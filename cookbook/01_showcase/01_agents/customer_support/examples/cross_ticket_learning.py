"""
Cross-Ticket Learning Demo
==========================
Demonstrates how the Learning Machine enables knowledge transfer:
- Ticket 1: First customer reports issue, agent solves it
- Customer confirms solution worked, agent saves learning
- Ticket 2: Different customer, similar issue, agent finds prior solution

This is the key value proposition of Learning Machines in support.

Run:
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/examples/cross_ticket_learning.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import create_support_agent

# ============================================================================
# Demo
# ============================================================================

if __name__ == "__main__":
    org_id = "acme"

    # Ticket 1: First customer with login issue
    print("\n" + "=" * 60)
    print("TICKET 1: First login issue")
    print("=" * 60 + "\n")

    agent = create_support_agent("customer_1@example.com", "ticket_001", org_id)
    agent.print_response(
        "I can't log into my account. It says 'invalid credentials' "
        "even though I know my password is correct. I'm using Chrome.",
        stream=True,
    )

    # Customer confirms solution worked
    print("\n" + "=" * 60)
    print("TICKET 1: Solution confirmed")
    print("=" * 60 + "\n")

    agent.print_response(
        "Clearing the cache worked! Thanks so much!",
        stream=True,
    )

    # Verify learning was saved
    print("\n--- Checking saved learnings ---")
    agent.get_learning_machine().learned_knowledge_store.print(
        query="login chrome cache"
    )

    # Ticket 2: Different customer, similar issue
    print("\n" + "=" * 60)
    print("TICKET 2: Similar issue (should find prior solution)")
    print("=" * 60 + "\n")

    agent2 = create_support_agent("customer_2@example.com", "ticket_002", org_id)
    agent2.print_response(
        "Login not working in Chrome, says wrong password but I'm sure it's right.",
        stream=True,
    )
