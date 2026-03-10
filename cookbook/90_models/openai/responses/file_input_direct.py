"""
Openai File Input Direct
========================

Cookbook example for `openai/responses/file_input_direct.py`.
"""

from pathlib import Path

from agno.agent import Agent
from agno.media import File
from agno.models.openai.responses import OpenAIResponses
from agno.utils.media import download_file

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-4o"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # File via URL
    agent.print_response(
        "Summarize the key contribution of this paper in 2-3 sentences.",
        files=[File(url="https://arxiv.org/pdf/1706.03762")],
    )

    # File via local filepath
    pdf_path = Path(__file__).parent.joinpath("ThaiRecipes.pdf")
    download_file(
        "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf", str(pdf_path)
    )

    agent.print_response(
        "List the first 3 recipes from this cookbook.",
        files=[File(filepath=pdf_path, mime_type="application/pdf")],
    )

    # File via raw bytes
    csv_content = b"name,role,team\nAlice,Engineer,Platform\nBob,Designer,Product\nCharlie,PM,Growth"

    agent.print_response(
        "Describe the team structure from this CSV.",
        files=[File(content=csv_content, filename="team.csv", mime_type="text/csv")],
    )
