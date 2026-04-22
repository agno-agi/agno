"""
Google Drive Context Provider
=============================

GDriveContextProvider wraps a read-only slice of `GoogleDriveTools`
(via an `AllDrivesGoogleDriveTools` subclass that injects
`corpora=allDrives` so a service account can see folders shared with
it and files in Shared Drives). The calling agent gets a single
`query_<id>` tool that routes through a sub-agent trained to
escalate searches when the naive query comes back empty.

Setup:
    1. Create a service account in Google Cloud Console and download
       its JSON key.
    2. Share the Drive folders you want the agent to see with the SA
       email (found in the JSON key as `client_email`).
    3. Point the env at the key file:
           export GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/sa.json

Requires:
    OPENAI_API_KEY
    GOOGLE_SERVICE_ACCOUNT_FILE
"""

from __future__ import annotations

import asyncio

from agno.agent import Agent
from agno.context.gdrive import GDriveContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create the provider (service-account path from env)
# ---------------------------------------------------------------------------
gdrive = GDriveContextProvider(model=OpenAIResponses(id="gpt-5.4-mini"))

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=gdrive.get_tools(),
    instructions=gdrive.instructions(),
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"\ngdrive.status() = {gdrive.status()}\n")
    prompt = (
        "What Google Docs can you see? Find the most recently modified "
        "one, read it, and summarize it in three bullets. Cite its "
        "webViewLink."
    )
    print(f"> {prompt}\n")
    asyncio.run(agent.aprint_response(prompt))
