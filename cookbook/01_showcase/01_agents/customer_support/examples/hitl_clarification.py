"""
HITL Clarification Demo
=======================

Demonstrates Human-in-the-Loop (HITL) using UserControlFlowTools.
The agent will use get_user_input() when it needs clarification.

This example shows scenarios where the agent needs human input:
1. Ambiguous queries that could mean multiple things
2. Missing information needed to resolve the issue
3. Escalation decisions that require human judgment

Prerequisites:
    1. PostgreSQL running: ./cookbook/scripts/run_pgvector.sh
    2. Knowledge loaded: python scripts/load_knowledge.py

Usage:
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/examples/hitl_clarification.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import support_agent  # noqa: E402

# ============================================================================
# Ambiguous Scenarios That Trigger HITL
# ============================================================================
HITL_SCENARIOS = [
    {
        "name": "Ambiguous Product Reference",
        "query": """
        Customer ticket: "The search isn't working"

        This is ambiguous - they could mean:
        - Knowledge base search
        - Web search tool
        - Vector database search
        - UI search functionality

        Process this ticket and get clarification if needed.
        """,
        "explanation": "The agent should use get_user_input() to clarify which search feature.",
    },
    {
        "name": "Missing Technical Details",
        "query": """
        Customer ticket: "Getting an error when I run my agent"

        No error message, no code, no environment details provided.

        Draft a response that gathers the needed information.
        """,
        "explanation": "The agent should identify what information is missing and either ask the customer or use HITL to determine what to ask.",
    },
    {
        "name": "Escalation Decision",
        "query": """
        Customer ticket (VIP Enterprise customer, very frustrated):

        "This is the THIRD time I'm reporting this issue. Your team promised
        it would be fixed last week. This is completely unacceptable and we're
        considering canceling our contract."

        Previous tickets show the same issue was reported twice before.
        What should we do?
        """,
        "explanation": "The agent should recognize this needs escalation and may use HITL to confirm the escalation path.",
    },
]


def run_hitl_demo():
    """Run scenarios that may trigger HITL clarification."""
    print("=" * 60)
    print("HITL Clarification Demo")
    print("=" * 60)
    print()
    print("This demo shows scenarios where the agent needs human input.")
    print("Watch for the agent using get_user_input() to request clarification.")
    print()

    for i, scenario in enumerate(HITL_SCENARIOS, 1):
        print(f"Scenario {i}: {scenario['name']}")
        print("-" * 40)
        print(f"Expected: {scenario['explanation']}")
        print()
        print("Query:")
        print(scenario["query"].strip())
        print()
        print("Agent Response:")
        print("-" * 20)

        try:
            # The agent may pause here waiting for user input if it uses HITL
            response = support_agent.run(scenario["query"])
            print(response.content if response.content else "(No content)")

            # Check if HITL was triggered
            if response.tool_calls:
                for tc in response.tool_calls:
                    if tc.function and tc.function.name == "get_user_input":
                        print()
                        print("HITL TRIGGERED - Agent requested user input")
        except Exception as e:
            print(f"Error: {e}")

        print()
        print("=" * 60)
        print()

        # Ask if user wants to continue
        if i < len(HITL_SCENARIOS):
            try:
                input("Press Enter to continue to next scenario...")
            except KeyboardInterrupt:
                print("\nExiting...")
                return
            print()


def explain_hitl():
    """Explain how HITL works in this agent."""
    print("""
HITL (Human-in-the-Loop) in Customer Support
=============================================

The support agent uses UserControlFlowTools to pause and request
human input when it encounters:

1. AMBIGUOUS QUERIES
   - "Search isn't working" - which search?
   - "Error on page" - which page?
   - Customer uses internal jargon

2. MISSING INFORMATION
   - No error message provided
   - No reproduction steps
   - Environment not specified

3. ESCALATION DECISIONS
   - Frustrated VIP customer
   - Repeated issue
   - Policy exception needed

4. CONFIDENCE THRESHOLD
   - Multiple possible answers
   - Conflicting information
   - No knowledge base match

How It Works:
-------------
When the agent calls get_user_input(), the agent run pauses and
returns control to the calling application. The application can
then prompt the human for input and resume the agent with the
response.

Example:
    agent.run("ambiguous query")
    # Agent pauses, requests: "Which search feature: KB, web, or vector?"
    # Human provides: "Knowledge base search"
    # Agent resumes with clarification

This is NATIVE HITL - no external tools or APIs needed.
    """)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="HITL Clarification Demo")
    parser.add_argument("--explain", action="store_true", help="Explain how HITL works")
    args = parser.parse_args()

    if args.explain:
        explain_hitl()
    else:
        run_hitl_demo()
