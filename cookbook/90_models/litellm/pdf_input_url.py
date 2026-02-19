"""
Litellm Pdf Input Url
=====================

Cookbook example for `litellm/pdf_input_url.py`.
"""

from agno.agent import Agent
from agno.media import File
from agno.models.litellm import LiteLLM

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=LiteLLM(id="gpt-4o"),
    markdown=True,
    add_history_to_context=True,
)

agent.print_response(
    "Suggest me a recipe from the attached file.",
    files=[File(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf")],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
