"""
Gemini Interactions - Deep Research with File Search
=====================================================

Ground the Deep Research agent on your own documents.

This cookbook is self-contained: it creates a File Search store, uploads a
sample document, waits for indexing, then runs a Deep Research task that
searches that store alongside the public web.

Setup steps (done here in code so the example runs end to end):
  1. client.file_search_stores.create(...)            -> store with .name
  2. client.file_search_stores.upload_to_file_search_store(store, file)
  3. poll client.operations.get(op) until op.done
  4. pass store.name to GeminiInteractions(file_search_store_names=[...])

In production you would create/populate the store once (offline) and only
reference it by name at query time.
"""

import tempfile
import time
from pathlib import Path

from agno.agent import Agent
from agno.models.google import GeminiInteractions
from google import genai

# ---------------------------------------------------------------------------
# 1-3. Create a File Search store and upload a document
# ---------------------------------------------------------------------------
client = genai.Client()

store = client.file_search_stores.create(
    config={"display_name": "agno-deep-research-demo"}
)
print(f"Created store: {store.name}")

# A small sample document to ground the research on.
sample = Path(tempfile.gettempdir()) / "agno_fy2025_summary.txt"
sample.write_text(
    "Agno FY2025 internal summary.\n"
    "Revenue grew 240% year over year, driven by AgentOS adoption.\n"
    "Headcount doubled. The flagship launch was the Antigravity integration.\n"
)

operation = client.file_search_stores.upload_to_file_search_store(
    file_search_store_name=store.name,
    file=str(sample),
    config={"display_name": "fy2025-summary"},
)
print("Uploading + indexing document...")
while not operation.done:
    time.sleep(3)
    operation = client.operations.get(operation)
print("Document indexed.")

# ---------------------------------------------------------------------------
# 4. Run Deep Research grounded on the store
# ---------------------------------------------------------------------------
agent = Agent(
    model=GeminiInteractions(
        agent="deep-research-preview-04-2026",
        thinking_summaries="auto",
        file_search_store_names=[store.name],
    ),
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "Using our internal FY2025 summary, compare our reported growth drivers "
        "against current public news about the AI agent framework market."
    )
