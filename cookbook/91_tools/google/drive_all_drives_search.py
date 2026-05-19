"""
Company-Wide Document Search
=============================
Search across personal and shared drives to find documents organization-wide.

Useful for compliance audits, finding policy documents, or locating project
resources scattered across team drives. Uses allDrives corpus which may return
partial results if your organization has many shared drives.

Key concepts:
- corpora="allDrives": Search personal Drive AND all Shared Drives you can access
- incompleteSearch: Flag when Google couldn't search all drives (inform the user)
- supports_all_drives: Required for accessing Shared Drive items

Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Google Drive API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent, saves token.json for reuse
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.drive import GoogleDriveTools

agent = Agent(
    name="Company Search Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        GoogleDriveTools(
            corpora="allDrives",
            supports_all_drives=True,
            include_items_from_all_drives=True,
        )
    ],
    instructions=[
        "Search across all drives the user has access to.",
        "If incompleteSearch is true, tell the user results may be partial.",
        "Group results by shared drive or owner when possible.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Find compliance documents across all drives
    agent.print_response(
        "Find any documents with 'policy' or 'compliance' in the name",
        stream=True,
    )

    # Search for project resources
    # agent.print_response(
    #     "Find spreadsheets related to Q4 planning across all team drives",
    #     stream=True,
    # )

    # Find recent presentations
    # agent.print_response(
    #     "What presentations were created in the last month?",
    #     stream=True,
    # )
