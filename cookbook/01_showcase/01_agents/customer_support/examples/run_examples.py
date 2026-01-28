"""
Customer Support Agent Examples
================================

Examples demonstrating different ways to use the Customer Support Agent.

Run this script to see the agent in action:
    python examples/run_examples.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import customer_support_agent

# ============================================================================
# Sample Support Tickets
# ============================================================================

BILLING_TICKET = """\
Customer: Sarah Johnson
Order #: ORD-2026-78432
Account: sarah.johnson@email.com

Message:
Hi, I just noticed that I was charged TWICE for my monthly subscription this
month. I see two charges of $29.99 on my credit card statement dated January
15th and January 16th. This is unacceptable! I've been a loyal customer for
over 2 years and this is the second time this has happened. I need this
resolved immediately and I want a refund for the duplicate charge.
"""

TECHNICAL_TICKET = """\
Customer: Mike Chen
Account: mike.chen@company.com

Message:
I keep getting a "Error 503: Service Unavailable" when trying to access the
dashboard. I've tried clearing my cache, using a different browser, and even
a different computer. Nothing works. This has been going on since yesterday
afternoon. I have a critical presentation tomorrow morning and I need to
pull reports from the dashboard. Please help ASAP.
"""

ACCOUNT_TICKET = """\
Customer: Emily Rodriguez

Message:
I've been trying to reset my password for the past hour but I never receive
the reset email. I've checked my spam folder and everything. I really need to
access my account because I have important documents stored there. I've tried
three times already. Can someone please help me get back into my account?
My email is emily.rodriguez@email.com
"""

ANGRY_CUSTOMER_TICKET = """\
Customer: James Wilson
Order #: ORD-2026-91205

Message:
THIS IS ABSOLUTELY RIDICULOUS!!! I ordered a laptop 3 weeks ago and it STILL
hasn't arrived. Your tracking page says "in transit" for the past 10 days.
I paid for express shipping and this is what I get?! I want a FULL REFUND
including shipping costs. If I don't hear back within 24 hours, I'm going to
post about this experience on every social media platform and file a complaint
with the BBB. I'm also considering contacting my lawyer. This is the WORST
customer service I've ever experienced.
"""

PRODUCT_INQUIRY = """\
Customer: Lisa Park

Message:
Hi there! I'm currently on the Basic plan and I'm thinking about upgrading to
the Pro plan. Could you tell me exactly what additional features I'd get? Also,
if I upgrade mid-cycle, how does the billing work? Do I get charged the full
price or is it prorated? And is there a trial period for the Pro features?
Thanks!
"""


# ============================================================================
# Example Functions
# ============================================================================


def example_billing_issue():
    """Handle a billing/duplicate charge ticket."""
    print("\n" + "=" * 60)
    print("Example 1: Billing Issue - Duplicate Charge")
    print("=" * 60)

    customer_support_agent.print_response(
        f"Handle this customer support ticket:\n\n{BILLING_TICKET}",
        stream=True,
    )


def example_technical_issue():
    """Handle a technical/service outage ticket."""
    print("\n" + "=" * 60)
    print("Example 2: Technical Issue - Service Unavailable")
    print("=" * 60)

    customer_support_agent.print_response(
        f"Handle this customer support ticket:\n\n{TECHNICAL_TICKET}",
        stream=True,
    )


def example_account_issue():
    """Handle an account access ticket."""
    print("\n" + "=" * 60)
    print("Example 3: Account Issue - Password Reset")
    print("=" * 60)

    customer_support_agent.print_response(
        f"Handle this customer support ticket:\n\n{ACCOUNT_TICKET}",
        stream=True,
    )


def example_angry_customer():
    """Handle an angry customer with escalation potential."""
    print("\n" + "=" * 60)
    print("Example 4: Angry Customer - Shipping Delay")
    print("=" * 60)

    customer_support_agent.print_response(
        f"Handle this customer support ticket:\n\n{ANGRY_CUSTOMER_TICKET}",
        stream=True,
    )


def example_product_inquiry():
    """Handle a product/plan upgrade inquiry."""
    print("\n" + "=" * 60)
    print("Example 5: Product Inquiry - Plan Upgrade")
    print("=" * 60)

    customer_support_agent.print_response(
        f"Handle this customer support ticket:\n\n{PRODUCT_INQUIRY}",
        stream=True,
    )


def interactive_mode():
    """Run the agent in interactive CLI mode."""
    print("\n" + "=" * 60)
    print("Interactive Mode")
    print("=" * 60)
    print("Starting interactive CLI...")
    print("Type 'exit' or 'quit' to stop\n")

    customer_support_agent.cli_app(stream=True)


# ============================================================================
# Main
# ============================================================================


def show_menu():
    """Display the main menu."""
    print("\n" + "=" * 60)
    print("  Customer Support Agent - Examples")
    print("=" * 60)
    print()
    print("  1. Billing Issue (Duplicate Charge)")
    print("  2. Technical Issue (Service Unavailable)")
    print("  3. Account Issue (Password Reset)")
    print("  4. Angry Customer (Shipping Delay + Escalation)")
    print("  5. Product Inquiry (Plan Upgrade)")
    print("  6. Interactive Mode")
    print()
    print("  0. Exit")
    print()


def main():
    """Run the CLI menu."""
    while True:
        show_menu()

        choice = input("Select an option: ").strip()

        if choice == "1":
            example_billing_issue()
        elif choice == "2":
            example_technical_issue()
        elif choice == "3":
            example_account_issue()
        elif choice == "4":
            example_angry_customer()
        elif choice == "5":
            example_product_inquiry()
        elif choice == "6":
            interactive_mode()
        elif choice == "0":
            print("\nGoodbye!")
            break
        else:
            print("\nInvalid option. Please try again.")

        input("\nPress Enter to continue...")


if __name__ == "__main__":
    main()
