"""
Google Docs Tools
=================
Create, read, and update Google Docs documents.

The agent can create new documents, fetch their full structure or plain text,
apply batched edit requests, append content, export to PDF via Drive, and
optionally delete documents.

Key concepts:
- create_document: creates a new blank document, returns documentId + url
- get_document_text: extracts plain text from a document body
- batch_update: the workhorse for any structural change (insertText, replaceAllText, etc.)
- append_text: convenience for adding content at the end of a doc
- export_as_pdf: saves a PDF via the Drive API; original doc unchanged

Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Docs API + Drive API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent, saves token.json for reuse
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.google.docs import GoogleDocsTools

agent = Agent(
    name="Docs Assistant",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        GoogleDocsTools(
            # delete_document=True,  # Destructive, enable if needed
        )
    ],
    instructions=[
        "You are a Google Docs assistant.",
        "Always return the documentId and url when you create a document.",
        "Prefer get_document_text for read-only summarization tasks.",
        "Use append_text for simple end-of-document additions; reach for batch_update for structural edits.",
    ],
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response(
        "Create a new Google Doc titled 'Q3 2026 Launch Plan'. "
        "Then append the following section to it:\n\n"
        "## Goals\n"
        "1. Ship the new dashboard by end of August\n"
        "2. Migrate 100% of customers to the new auth flow\n"
        "3. Reduce p95 latency below 400ms\n",
        stream=True,
    )

    # Example 2: read a document's text
    # agent.print_response(
    #     "Fetch the plain text of document 1AbC...xyz and summarise the first 3 sections.",
    #     stream=True,
    # )

    # Example 3: structured edit
    # agent.print_response(
    #     "In document 1AbC...xyz, replace every instance of 'Q3' with 'Q4 2026'.",
    #     stream=True,
    # )
