"""
Stream Hook
=============================

Demonstrates post-hook notifications after team response generation.
"""

import asyncio

from agno.models.openai import OpenAIResponses
from agno.run import RunContext
from agno.run.team import TeamRunOutput
from agno.team import Team
from agno.tools.yfinance import YFinanceTools


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
def send_email(email: str, content: str) -> None:
    """Send an email to the user. Mock implementation for example purposes."""
    print(f"Sending email to {email}: {content}")


def send_notification(run_output: TeamRunOutput, run_context: RunContext) -> None:
    """Post-hook: Send a notification to the user."""
    if run_context.metadata is None:
        return
    email = run_context.metadata.get("email")
    if email:
        send_email(email, run_output.content)


# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="Financial Report Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[],
    post_hooks=[send_notification],
    tools=[YFinanceTools()],
    instructions=[
        "You are a helpful financial report team of agents.",
        "Generate a financial report for the given company.",
        "Keep it short and concise.",
    ],
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
async def main() -> None:
    await team.aprint_response(
        "Generate a financial report for Apple (AAPL).",
        user_id="user_123",
        metadata={"email": "test@example.com"},
        stream=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
