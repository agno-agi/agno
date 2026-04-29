"""
Gmail Context Provider
======================

GmailContextProvider wraps GmailTools for read/write email access.
The calling agent gets `query_<id>` and optionally `update_<id>` tools
that route through sub-agents specialized for searching/reading vs
composing/sending.

Setup (OAuth - recommended for personal Gmail):
    1. Create OAuth credentials in Google Cloud Console
    2. Set env vars:
           export GOOGLE_CLIENT_ID=...
           export GOOGLE_CLIENT_SECRET=...
           export GOOGLE_PROJECT_ID=...
    3. On first run, a browser opens for consent. Token cached to gmail_token.json

Setup (Service Account - for workspace bots):
    1. Create service account with domain-wide delegation enabled
    2. Grant Gmail API scopes in Google Admin console
    3. Set env vars:
           export GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/sa.json
           export GOOGLE_DELEGATED_USER=user@domain.com

Requires:
    OPENAI_API_KEY
    + one of the auth methods above
"""

from __future__ import annotations

import asyncio

from agno.agent import Agent
from agno.context.gmail import GmailContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create the provider (auth method resolved from env)
# ---------------------------------------------------------------------------
gmail = GmailContextProvider(
    model=OpenAIResponses(id="gpt-5.4-mini"),
    read=True,
    write=False,
)

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=gmail.get_tools(),
    instructions=gmail.instructions(),
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"\ngmail.status() = {gmail.status()}\n")
    prompt = (
        "What are my 5 most recent emails? Summarize each in one sentence, "
        "including sender and subject."
    )
    print(f"> {prompt}\n")
    asyncio.run(agent.aprint_response(prompt))
