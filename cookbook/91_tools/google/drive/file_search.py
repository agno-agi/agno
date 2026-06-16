"""
Drive File Search
=================
Search and inspect Drive files with structured output.

The agent searches Drive, fetches metadata, and returns a structured report.

Key concepts:
- output_schema: Forces structured JSON matching FileSearchResult
- search_files: Returns full metadata including parents, description, and links

Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Google Drive API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent, saves token.json for reuse
"""

from typing import List, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.drive import GoogleDriveTools
from pydantic import BaseModel, Field


class FileInfo(BaseModel):
    file_id: str = Field(..., description="Google Drive file ID")
    name: str = Field(..., description="File name")
    mime_type: str = Field(..., description="MIME type")
    modified: str = Field(..., description="Last modified timestamp")
    owner: Optional[str] = Field(None, description="File owner name or email")
    parents: Optional[List[str]] = Field(None, description="Parent folder IDs")
    description: Optional[str] = Field(
        None, description="File description set by the owner"
    )
    web_link: Optional[str] = Field(None, description="Web view link")
    download_link: Optional[str] = Field(None, description="Direct download link")


class FileSearchResult(BaseModel):
    query: str = Field(..., description="The search query used")
    total_found: int = Field(..., description="Number of files found")
    files: List[FileInfo] = Field(default_factory=list, description="Matching files")


agent = Agent(
    name="Drive Search Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GoogleDriveTools()],
    instructions=[
        "Search for files matching the user's criteria.",
        "search_files returns full metadata including parents, description, and links.",
    ],
    output_schema=FileSearchResult,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response("Find all PDF files in my Drive")

    # Search by name pattern
    # agent.print_response("Search for files with 'report' in the name")

    # Search within a folder
    # agent.print_response("What files are inside the folder called 'Projects'?")
