"""
Gmail Context Provider
======================

GmailContextProvider gives agents read/write access to Gmail through
specialized sub-agents. The calling agent receives:

- ``query_gmail`` — search emails, read threads, list labels
- ``update_gmail`` — draft emails, send replies, manage labels (when write=True)

This example demonstrates:
1. Read-only mode: searching and summarizing emails
2. Read-write mode: drafting a follow-up based on email content

Compare with: 19_calendar.py for calendar operations
See also: 20_google_workspace.py for multi-provider workflows

Setup (OAuth - recommended for personal Gmail):
    1. Create OAuth credentials in Google Cloud Console
       - APIs & Services > Credentials > Create OAuth Client ID
       - Application type: Desktop app
       - Download the JSON or note the client ID and secret
    2. Enable the Gmail API in your project
    3. Set environment variables::

           export GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
           export GOOGLE_CLIENT_SECRET=GOCSPX-...
           export GOOGLE_PROJECT_ID=your-project-id

    4. First run opens browser for consent, token cached to gmail_token.json

Setup (Service Account - for Google Workspace):
    1. Create service account with domain-wide delegation
    2. Grant Gmail scopes in Google Admin > Security > API Controls
    3. Set environment variables::

           export GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/service-account.json
           export GOOGLE_DELEGATED_USER=user@yourdomain.com

Requires: OPENAI_API_KEY + one of the auth methods above
"""

from __future__ import annotations

import asyncio

from agno.agent import Agent
from agno.context.gmail import GmailContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Example 1: Read-Only Gmail Access
# ---------------------------------------------------------------------------
# Use read=True, write=False when you only need to search and read emails.
# The agent gets query_gmail but NOT update_gmail.


async def demo_read_only():
    print("\n" + "=" * 60)
    print("DEMO 1: Read-Only Gmail Access")
    print("=" * 60)

    gmail = GmailContextProvider(
        model=OpenAIResponses(id="gpt-5.4-mini"),
        read=True,
        write=False,
    )

    agent = Agent(
        model=OpenAIResponses(id="gpt-5.4"),
        tools=gmail.get_tools(),
        instructions=gmail.instructions(),
        markdown=True,
    )

    print(f"\nProvider status: {gmail.status()}")
    print("\n--- Query: Find unread emails from the last 3 days ---\n")

    await agent.aprint_response(
        "Find my unread emails from the last 3 days. "
        "Group them by sender and summarize what each person is asking about.",
        stream=True,
    )


# ---------------------------------------------------------------------------
# Example 2: Read-Write Gmail Access
# ---------------------------------------------------------------------------
# Use write=True when the agent needs to draft or send emails.
# The agent gets both query_gmail and update_gmail tools.


async def demo_read_write():
    print("\n" + "=" * 60)
    print("DEMO 2: Read-Write Gmail Access")
    print("=" * 60)

    gmail = GmailContextProvider(
        model=OpenAIResponses(id="gpt-5.4-mini"),
        read=True,
        write=True,
    )

    agent = Agent(
        model=OpenAIResponses(id="gpt-5.4"),
        tools=gmail.get_tools(),
        instructions=gmail.instructions(),
        markdown=True,
    )

    print(f"\nProvider status: {gmail.status()}")
    print("\n--- Query: Draft a follow-up email ---\n")

    await agent.aprint_response(
        "Find the most recent email thread where I haven't replied yet. "
        "Draft a brief follow-up response and save it as a draft.",
        stream=True,
    )


# ---------------------------------------------------------------------------
# Run Demos
# ---------------------------------------------------------------------------


async def main():
    await demo_read_only()
    await demo_read_write()


if __name__ == "__main__":
    asyncio.run(main())
