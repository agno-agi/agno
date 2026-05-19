"""
Company-Wide Document Search
=============================
Search across personal and shared drives to find documents organization-wide.

Useful for compliance audits, finding policy documents, or locating project
resources scattered across team drives. Uses allDrives corpus which may return
partial results if your organization has many shared drives.

Key concepts:
- corpora="allDrives": Search personal Drive AND all Shared Drives you can access
- incompleteSearch: API flag when Google couldn't search all drives (agent adds notice)
- output_schema: Structured results with owner/location for programmatic use

Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Google Drive API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent, saves token.json for reuse
"""

from typing import List, Optional

from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.drive import GoogleDriveTools


class DocumentResult(BaseModel):
    name: str = Field(..., description="File name")
    file_id: str = Field(..., description="Google Drive file ID")
    owner: Optional[str] = Field(None, description="File owner email")
    location: Optional[str] = Field(None, description="Shared drive name or 'My Drive'")
    web_link: Optional[str] = Field(None, description="Link to open in browser")


class CompanySearchResult(BaseModel):
    query: str = Field(..., description="The search query used")
    documents: List[DocumentResult] = Field(default_factory=list)
    total_found: int = Field(..., description="Number of documents found")
    notice: Optional[str] = Field(
        None,
        description="Warning if results are incomplete or other issues",
    )


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
        "If incompleteSearch is true in the search results, add a notice explaining "
        "that some shared drives could not be searched.",
        "Include the owner and location (shared drive name) when available.",
    ],
    output_schema=CompanySearchResult,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Find compliance documents across all drives
    result = agent.run("Find any documents with 'policy' or 'compliance' in the name")
    print(result.content)

    # Search for project resources
    # result = agent.run("Find spreadsheets related to Q4 planning")
    # print(result.content)
