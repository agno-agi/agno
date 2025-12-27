"""
Example demonstrating sending a notification to the user after a team generates a response.

It uses a post-hook which executes right after the response is processed.
"""

import asyncio
from typing import Any, Dict

from agno.models.openai import OpenAIChat
from agno.run.team import TeamRunOutput
from agno.team import Team
from agno.tools.yfinance import YFinanceTools


def send_notification(run_output: TeamRunOutput, metadata: Dict[str, Any]) -> None:
    """
    Post-hook: Send a notification to the user.
    """
    email = metadata.get("email")
    if email:
        send_email(email, run_output.content)


def send_email(email: str, content: str) -> None:
    """
    Send an email to the user. Mock, just for the example.
    """
    print(f"Sending email to {email}: {content}")


async def main():
    # Team equipped with a post-hook to send email notifications
    team = Team(
        name="Financial Report Team",
        model=OpenAIChat(id="gpt-5-mini"),
        members=[],
        post_hooks=[send_notification],
        tools=[YFinanceTools()],
        instructions=[
            "You are a helpful financial report team of agents.",
            "Generate a financial report for the given company.",
            "Keep it short and concise.",
        ],
    )

    # Run the team
    await team.aprint_response(
        "Generate a financial report for Apple (AAPL).",
        user_id="user_123",
        metadata={"email": "test@example.com"},
        stream=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
