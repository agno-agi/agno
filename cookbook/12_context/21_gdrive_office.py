"""
Google Drive Office Document Reading
=====================================

Demonstrates reading Microsoft Office files (.docx, .xlsx, .pptx) from
Google Drive with automatic text extraction. The GDrive provider uses
optional dependencies to extract text content:

- python-docx for Word documents
- openpyxl for Excel spreadsheets
- python-pptx for PowerPoint presentations

Without these packages, Office files return a clear error with install
instructions. Binary files (PDFs, images, etc.) are detected and rejected
with a helpful message rather than returning garbage UTF-8.

Setup:
    1. Create a service account in Google Cloud Console and download
       its JSON key.
    2. Share the Drive folders containing Office files with the SA email.
    3. Point the env at the key file:
           export GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/sa.json
    4. Install optional dependencies for Office support:
           pip install python-docx openpyxl python-pptx

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
        "Search for any .docx, .xlsx, or .pptx files in my Drive. "
        "Pick one, read its contents, and summarize what it contains."
    )
    print(f"> {prompt}\n")
    asyncio.run(agent.aprint_response(prompt))
