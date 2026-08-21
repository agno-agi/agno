"""
Agno Gateway - PDF input
========================

Attach a PDF with ``files=[File(...)]``. The class formats the file into the OpenAI
chat-completions content schema, which the gateway forwards to the provider. Use a
model that accepts file input.

Requires:
- AGNO_API_KEY  (or a provider key for BYOK, e.g. OPENAI_API_KEY for "openai/...")
"""

from agno.agent import Agent
from agno.media import File
from agno.models.agno import Agno

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Agno(id="openai/gpt-5.4"),
    markdown=True,
    add_history_to_context=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Suggest me a recipe from the attached file.",
        files=[
            File(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf")
        ],
    )
