"""
Cross-Ticket Learning Demo
==========================
Demonstrates how the Learning Machine enables knowledge transfer across tickets.

This demo shows ALL THREE Learning Machine stores in action:
1. **Session Context**: Tracks goal/plan/progress within a ticket
2. **Entity Memory**: Captures facts about products and systems mentioned
3. **Learned Knowledge**: Saves reusable solutions for future tickets

Flow:
- Ticket 1: Customer reports issue, agent solves it
- Show: Session Context (goal detected), Entity Memory (Chrome captured)
- Customer confirms, agent saves learning
- Show: Learned Knowledge (solution saved!)
- Ticket 2: Different customer, similar issue
- Show: How learned knowledge helps the new ticket

Run:
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/examples/cross_ticket_learning.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import create_support_agent


def show_stores(agent, session_id: str, title: str = "Learning Machine State"):
    """Display what each Learning Machine store has captured."""
    lm = agent.get_learning_machine()

    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print(f"{'─' * 50}")

    # Session Context: goal, plan, progress
    print("\n[Session Context]")
    if lm.session_context_store:
        lm.session_context_store.print(session_id=session_id)
    else:
        print("  (not enabled)")

    # Entity Memory: products/systems mentioned
    print("\n[Entity Memory]")
    if lm.entity_memory_store:
        entities = lm.entity_memory_store.search(query="browser login", limit=5)
        if entities:
            for e in entities:
                name = getattr(e, "name", e.entity_id)
                facts = getattr(e, "facts", [])
                print(f"  - {name} ({e.entity_type})")
                for fact in facts[:3]:
                    content = (
                        fact.get("content", fact)
                        if isinstance(fact, dict)
                        else str(fact)
                    )
                    print(f"      * {content}")
        else:
            print("  (no entities captured yet)")
    else:
        print("  (not enabled)")

    # Learned Knowledge: solutions saved
    print("\n[Learned Knowledge]")
    if lm.learned_knowledge_store:
        lm.learned_knowledge_store.print(query="login chrome")
    else:
        print("  (not enabled)")

    print()


if __name__ == "__main__":
    # =========================================================================
    # Ticket 1: First customer with login issue
    # =========================================================================
    print("\n" + "=" * 60)
    print("TICKET 1: First login issue")
    print("=" * 60 + "\n")

    agent = create_support_agent("customer_1@example.com", "ticket_001")
    agent.print_response(
        "I can't log into my account. It says 'invalid credentials' "
        "even though I know my password is correct. I'm using Chrome.",
        stream=True,
    )

    # Show what the stores captured after first interaction
    show_stores(
        agent,
        session_id="ticket_001",
        title="After First Message (solution NOT confirmed yet)",
    )
   
    # =========================================================================
    # Ticket 2: Customer confirms solution worked
    # =========================================================================
    print("\n" + "=" * 60)
    print("TICKET 1: Solution confirmed")
    print("=" * 60 + "\n")

    agent.print_response(
        "Clearing the cache worked! Thanks so much!",
        stream=True,
    )

    # Show stores after confirmation - learned knowledge should be saved now
    show_stores(
        agent,
        session_id="ticket_001",
        title="After Confirmation (solution SAVED to learned knowledge)",
    )

    # Ticket 2: Second message
    agent.print_response(
        "Why is my Wifi not working? I'm using a Macbook Pro and I'm connected to the same Wifi network as my phone.",
        stream=True,
    )


    # =========================================================================
    # Ticket 3: Different customer, similar issue
    # =========================================================================
    print("\n" + "=" * 60)
    print("TICKET 3: Similar issue (different customer)")
    print("=" * 60 + "\n")

    print("The agent should find the prior solution and apply it...")
    print()

    agent2 = create_support_agent("customer_2@example.com", "ticket_002")
    agent2.print_response(
        "Login not working in Chrome, says wrong password but I'm sure it's right.",
        stream=True,
    )

    # Show that the new ticket can access prior learnings
    show_stores(
        agent2,
        session_id="ticket_002",
        title="Ticket 2 - Agent found prior solution via Learned Knowledge",
    )
