"""
Pre-hooks on continue_run
=========================

Demonstrates @hook(run_on_continue=True) for HITL (Human-in-the-Loop) flows.

- Regular pre-hooks only run on initial run()
- Hooks with @hook(run_on_continue=True) run on BOTH run() and continue_run()

Use this for security checks or audit logging that must run on every execution.
"""

from agno.agent import Agent
from agno.hooks import hook
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunInput, RunRequirement
from agno.tools import tool


# Regular pre-hook - only runs on initial run()
def log_request(run_input: RunInput) -> None:
    """Logs initial request. Skipped on continue_run."""
    print(f"[log_request] Input: {run_input.input_content[:50]}...")


# Pre-hook with @hook(run_on_continue=True) - runs on BOTH
@hook(run_on_continue=True)
def security_check(run_input: RunInput, user_id: str = None) -> None:
    """Security check that runs on every execution."""
    print(f"[security_check] User: {user_id}")


@tool(requires_confirmation=True)
def transfer_funds(amount: float, to_account: str) -> str:
    """Transfer funds to another account."""
    return f"Transferred ${amount:.2f} to account {to_account}"


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Banking Agent",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[transfer_funds],
    pre_hooks=[log_request, security_check],
    instructions=["You help users with banking operations."],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Initial run - both hooks execute, then pauses for confirmation
    run = agent.run(
        input="Transfer $100 to account 12345",
        user_id="user-123",
    )
    print(f"Status: {run.status}")

    # Continue after approval - only security_check runs (has @hook decorator)
    if run.requirements:
        for req in run.requirements:
            if isinstance(req, RunRequirement):
                req.confirmation = True

        run = agent.continue_run(run_response=run, user_id="user-123")
        print(f"Status: {run.status}")
        print(run.content)
