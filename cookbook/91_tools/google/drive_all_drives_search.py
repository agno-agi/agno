"""
Company-Wide Document Search
=============================
Search across personal and shared drives to find documents organization-wide.

Example scenario: A compliance officer preparing for an external audit needs to
locate policy documents across the company, regardless of which team drive
they're stored in. The structured output makes it easy to generate a report.

Key concepts:
- corpora="allDrives": Search personal Drive AND all Shared Drives you can access
- incompleteSearch: API flag when Google couldn't search all drives (agent adds notice)

Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Google Drive API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent, saves token.json for reuse
"""

from typing import List, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.google.drive import GoogleDriveTools
from pydantic import BaseModel, Field


class DocumentResult(BaseModel):
    name: str = Field(..., description="File name")
    file_id: str = Field(..., description="Google Drive file ID")
    owner: Optional[str] = Field(None, description="File owner email")
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
    name="Compliance Document Finder",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GoogleDriveTools(
            corpora="allDrives",
            supports_all_drives=True,
            include_items_from_all_drives=True,
        )
    ],
    instructions=[
        "Search across all drives the user has access to.",
        "If incompleteSearch is true, add a notice that some shared drives could not be searched.",
        "Include owner email when available from the owners field.",
    ],
    output_schema=CompanySearchResult,
)

# ---------------------------------------------------------------------------
# Run: Pre-Audit Policy Document Discovery
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Scenario: Compliance officer preparing for external audit
    result = agent.run(
        "Find Google Docs with 'policy' in the name. "
        "I need to review our company policies before next week's audit."
    )

    # Generate a simple audit report
    search_result: CompanySearchResult = result.content
    print("Policy Document Audit Report")
    print(f"{'=' * 40}")
    print(f"Search: {search_result.query}")
    print(f"Found: {search_result.total_found} documents\n")

    if search_result.notice:
        print(f"Notice: {search_result.notice}\n")

    for doc in search_result.documents:
        print(f"- {doc.name}")
        print(f"  Owner: {doc.owner or 'Unknown'}")
        print(f"  Link: {doc.web_link or 'N/A'}\n")
