"""
Example demonstrating sending a notification to the user after an agent generates a response.

It uses a post-hook which executes right after the response is processed.
"""

import asyncio
from typing import Any, Dict

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput
from agno.tools.yfinance import YFinanceTools


def send_notification(run_output: RunOutput, metadata: Dict[str, Any]) -> None:
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
    # Agent with comprehensive output validation
    agent = Agent(
        name="Financial Report Agent",
        model=OpenAIChat(id="gpt-5-mini"),
        post_hooks=[send_notification],
        tools=[YFinanceTools()],
        instructions=[
            "You are a helpful financial report agent.",
            "Generate a financial report for the given company.",
            "Keep it short and concise.",
        ],
    )

    # Run the agent
    await agent.aprint_response(
        "Generate a financial report for Apple (AAPL).",
        user_id="user_123",
        metadata={"email": "test@example.com"},
        stream=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
