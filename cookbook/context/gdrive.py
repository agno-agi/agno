"""
Google Drive Context Provider
=============================

Read-only Google Drive access via a service account.

The agent authenticates as a dedicated service account — its own
identity, not yours. Whatever folders you share with the service
account's email, the agent can read. Nothing else. No OAuth consent,
no user impersonation.

Setup:
1. Create a service account in Google Cloud Console and download the
   JSON key.
2. Share Drive folders/files with the service account's email (role:
   Viewer). Uncheck "Notify people" — service accounts have no inbox.
3. Set `GOOGLE_SERVICE_ACCOUNT_FILE` to the JSON key path.

Run: pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
Env: GOOGLE_SERVICE_ACCOUNT_FILE, OPENAI_API_KEY
"""

from agno.agent import Agent
from agno.context.gdrive import GDriveContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Build Provider
# ---------------------------------------------------------------------------
provider = GDriveContextProvider()

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=provider.get_tools(),
    instructions=[
        "You answer questions about files in Google Drive.",
        provider.instructions(),
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Status:", provider.status())
    agent.print_response(
        "List the five most recently modified Google Docs.",
        stream=True,
    )
