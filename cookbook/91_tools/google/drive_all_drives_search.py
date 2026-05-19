"""
Drive All-Drives Search
=======================
Search across all drives (personal + shared) with incomplete result handling.

When searching with corpora="allDrives", Google may return incompleteSearch=true
if it cannot search all drives within performance limits. This cookbook shows
how to configure the toolkit and handle partial results.

Key concepts:
- corpora="allDrives": Search personal Drive AND all Shared Drives
- incompleteSearch: Flag indicating some drives could not be searched
- Agent guidance: Inform user about partial results, don't retry blindly

Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Google Drive API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent, saves token.json for reuse

Note: incompleteSearch typically occurs in organizations with many Shared Drives.
For personal accounts with few drives, it usually returns False.
"""

from typing import List, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.drive import GoogleDriveTools
from pydantic import BaseModel, Field


class SearchResultFile(BaseModel):
    file_id: str = Field(..., description="Google Drive file ID")
    name: str = Field(..., description="File name")
    mime_type: str = Field(..., description="MIME type")


class AllDrivesSearchResult(BaseModel):
    query: str = Field(..., description="The search query used")
    total_found: int = Field(..., description="Number of files found")
    incomplete_search: bool = Field(
        ...,
        description="True if some drives could not be searched (results may be partial)",
    )
    files: List[SearchResultFile] = Field(default_factory=list)
    user_notice: Optional[str] = Field(
        None,
        description="Notice to user if results are incomplete",
    )


agent = Agent(
    name="All-Drives Search Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        GoogleDriveTools(
            corpora="allDrives",
            supports_all_drives=True,
            include_items_from_all_drives=True,
        )
    ],
    instructions=[
        "Search across all drives (personal and shared) for files matching user criteria.",
        "IMPORTANT: Check the incompleteSearch field in results.",
        "If incompleteSearch is true, inform the user that results may be partial.",
        "Do NOT retry the same query - the limitation is server-side, not your query.",
    ],
    output_schema=AllDrivesSearchResult,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    result = agent.run("Search for any spreadsheet files across all drives")
    print(result.content)

    # If you have many shared drives, try a broad search to trigger incompleteSearch:
    # agent.print_response("Find all files modified in the last year")
