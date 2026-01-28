"""
Escalation Policy
=================

Demonstrates strict escalation rules for customer support:
1. Automatic escalation triggers (billing, security, VIP)
2. Sentiment-based escalation (frustrated/urgent customers)
3. Repeat issue detection and escalation path

The agent follows escalation guidelines from the knowledge base.

Prerequisites:
    1. PostgreSQL running: ./cookbook/scripts/run_pgvector.sh
    2. Knowledge loaded: python scripts/load_knowledge.py

Usage:
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/examples/escalation_policy.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import support_agent  # noqa: E402

# ============================================================================
# Escalation Scenarios
# ============================================================================
ESCALATION_SCENARIOS = [
    {
        "name": "Security Concern - Auto Escalate",
        "ticket": """
        Subject: Possible unauthorized access to my account

        I noticed login attempts from an IP address I don't recognize.
        Someone may have accessed my account without authorization.
        I need this investigated immediately.
        """,
        "expected_action": "Immediate escalation to security team (Tier 2+)",
        "triggers": ["security", "unauthorized", "account access"],
    },
    {
        "name": "Billing Issue - Finance Escalation",
        "ticket": """
        Subject: Incorrect charge on my invoice

        I was charged $500 instead of $50 on my last invoice.
        This is clearly a billing error. I need a refund processed
        and an explanation of what happened.
        """,
        "expected_action": "Escalate to billing/finance team",
        "triggers": ["billing", "charge", "invoice", "refund"],
    },
    {
        "name": "VIP Customer - Priority Handling",
        "ticket": """
        Subject: Critical issue with enterprise deployment
        Customer: Acme Corp (Enterprise tier, $50k ARR)

        Our production deployment is experiencing intermittent failures.
        This is affecting our end users and we have a board presentation
        tomorrow. Need immediate attention from a senior engineer.
        """,
        "expected_action": "P1 priority, senior engineer assignment",
        "triggers": ["enterprise", "production", "critical", "VIP"],
    },
    {
        "name": "Repeat Issue - Escalation Required",
        "ticket": """
        Subject: RE: RE: RE: Knowledge base search still broken

        This is my FOURTH time contacting support about this issue.
        Every time I'm told it will be fixed, but nothing changes.
        I've been a customer for 3 years and this is unacceptable.
        I want to speak with a manager.
        """,
        "expected_action": "Immediate manager escalation, acknowledge history",
        "triggers": ["repeat", "multiple times", "manager", "escalate"],
    },
    {
        "name": "Angry Customer - Careful Handling",
        "ticket": """
        Subject: COMPLETELY UNACCEPTABLE SERVICE

        I am absolutely FURIOUS. Your product crashed and deleted
        all my work. I've lost HOURS of progress. This is the worst
        experience I've ever had with any software. I demand compensation.
        """,
        "expected_action": "Empathy first, then escalate if needed",
        "triggers": ["angry", "furious", "compensation", "escalate"],
    },
]


def run_escalation_scenarios():
    """Process tickets that require escalation decisions."""
    print("=" * 60)
    print("Escalation Policy Demo")
    print("=" * 60)
    print()
    print("This demo shows how the agent handles escalation scenarios:")
    print("- Security issues -> Security team")
    print("- Billing issues -> Finance team")
    print("- VIP customers -> Priority handling")
    print("- Repeat issues -> Manager escalation")
    print("- Angry customers -> Empathy + escalation path")
    print()

    for i, scenario in enumerate(ESCALATION_SCENARIOS, 1):
        print(f"Scenario {i}: {scenario['name']}")
        print("-" * 40)
        print(f"Expected: {scenario['expected_action']}")
        print(f"Triggers: {', '.join(scenario['triggers'])}")
        print()
        print("Ticket:")
        print(scenario["ticket"].strip())
        print()
        print("Agent Response:")
        print("-" * 20)

        query = f"""
        Process this support ticket and determine the appropriate action.
        Follow escalation guidelines strictly.

        {scenario["ticket"]}

        Explain your escalation decision and what action should be taken.
        """

        try:
            support_agent.print_response(query, stream=True)
        except Exception as e:
            print(f"Error: {e}")

        print()
        print("=" * 60)
        print()

        # Pause between scenarios
        if i < len(ESCALATION_SCENARIOS):
            try:
                input("Press Enter for next scenario...")
            except KeyboardInterrupt:
                print("\nExiting...")
                return
            print()


def show_escalation_matrix():
    """Display the escalation decision matrix."""
    print("""
Escalation Decision Matrix
==========================

AUTOMATIC ESCALATION (no judgment required):
  - Security concerns -> Security Team immediately
  - Billing disputes over $100 -> Finance Team
  - Legal/compliance mentions -> Legal Team
  - Data breach suspicion -> Security + Legal

PRIORITY ESCALATION:
  - VIP/Enterprise customers -> P1 priority, senior engineer
  - Production down -> P1, on-call escalation
  - Repeat issues (3+) -> Manager notification

SENTIMENT-BASED ESCALATION:
  - FRUSTRATED customer -> Acknowledge + offer escalation
  - URGENT + FRUSTRATED -> Immediate manager involvement
  - Compensation requests -> Manager approval required

STANDARD FLOW (no escalation):
  - Questions -> Knowledge base + response
  - Feature requests -> Log + acknowledge
  - Minor bugs -> Document + standard response

HITL TRIGGERS:
  - Unsure about escalation path -> Ask supervisor
  - Multiple valid escalation paths -> Clarify priority
  - Customer explicitly requests manager -> Honor request
    """)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Escalation Policy Demo")
    parser.add_argument(
        "--matrix", action="store_true", help="Show escalation decision matrix"
    )
    args = parser.parse_args()

    if args.matrix:
        show_escalation_matrix()
    else:
        run_escalation_scenarios()
