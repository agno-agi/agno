"""
HITL Demo
=========
Human-in-the-loop demonstration using UserControlFlowTools.
The agent asks for clarification when queries are ambiguous.

Run:
    .venvs/demo/bin/python cookbook/01_showcase/01_agents/customer_support/examples/hitl_demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import create_support_agent
from agno.tools.user_control_flow import UserControlFlowTools

SESSION_ID = "hitl_demo"


def run_hitl_demo():
    """Run agent with HITL - it will ask for clarification when needed."""
    agent = create_support_agent(
        customer_id="demo@example.com",
        ticket_id=SESSION_ID,
    )

    # Add HITL tools
    agent.tools.append(UserControlFlowTools(add_instructions=True))

    print("=" * 60)
    print("HITL Demo - Human-in-the-Loop")
    print("=" * 60)
    print("\nThe agent will ask for clarification on ambiguous queries.\n")

    # Ambiguous query that should trigger HITL
    response = agent.run(
        "The search isn't working properly. Can you help?",
        session_id=SESSION_ID,
    )

    # Handle HITL if triggered
    while response.is_paused:
        for req in response.active_requirements:
            if req.needs_user_input:
                print(
                    f"\nAgent asks: {req.tool_execution.tool_args.get('question', '')}"
                )
                user_input = input("Your answer: ").strip()
                req.provide_user_input(user_input)

        response = agent.continue_run(
            run_id=response.run_id,
            requirements=response.requirements,
            session_id=SESSION_ID,
        )

    print("\n--- Response ---")
    print(response.content)


if __name__ == "__main__":
    run_hitl_demo()
