"""
Openai File Input Direct
========================

Pass files directly to OpenAI Responses API without requiring the
file_search tool or vector stores.

Files are embedded inline as input_file content blocks. Three sources
are supported: URL (server-side fetch), local filepath (base64), and
raw bytes (base64). This is the simplest way to give the model access
to a document.
"""

from pathlib import Path

from agno.agent import Agent
from agno.media import File
from agno.models.openai.responses import OpenAIResponses
from agno.utils.media import download_file

# ---------------------------------------------------------------------------
# Create Agent — no file_search tool needed
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-4o"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Example 1: File via URL (most efficient — OpenAI fetches server-side)
# ---------------------------------------------------------------------------

print("\n--- Example 1: File via URL ---\n")
agent.print_response(
    "Summarize the key contribution of this paper in 2-3 sentences.",
    files=[File(url="https://arxiv.org/pdf/1706.03762")],
)

# ---------------------------------------------------------------------------
# Example 2: File via local filepath (base64 encoded)
# ---------------------------------------------------------------------------

print("\n--- Example 2: File via local filepath ---\n")
pdf_path = Path(__file__).parent.joinpath("ThaiRecipes.pdf")
download_file(
    "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf", str(pdf_path)
)

agent.print_response(
    "List the first 3 recipes from this cookbook.",
    files=[File(filepath=pdf_path, mime_type="application/pdf")],
)

# ---------------------------------------------------------------------------
# Example 3: File via raw bytes content
# ---------------------------------------------------------------------------

print("\n--- Example 3: File via raw bytes ---\n")
csv_content = (
    b"name,role,team\nAlice,Engineer,Platform\nBob,Designer,Product\nCharlie,PM,Growth"
)

agent.print_response(
    "Describe the team structure from this CSV.",
    files=[File(content=csv_content, filename="team.csv", mime_type="text/csv")],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
