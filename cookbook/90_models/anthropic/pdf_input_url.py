"""
Anthropic Pdf Input Url
=======================

Cookbook example for `anthropic/pdf_input_url.py`.
"""

from agno.agent import Agent
from agno.media import File
from agno.models.anthropic import Claude

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Claude(id="claude-sonnet-4-20250514"),
    markdown=True,
)

agent.print_response(
    "Summarize the contents of the attached file.",
    files=[
        File(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"),
    ],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
