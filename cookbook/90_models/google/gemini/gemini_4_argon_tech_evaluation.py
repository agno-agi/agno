"""Technology Evaluation with Gemini 4 Argon.

Compare technologies using Google Search, URL context, and structured output.

Run `uv pip install -U google-genai agno` to install dependencies.
Export `GOOGLE_API_KEY` with access to `gemini-4-argon` before running.
"""

from typing import List

from agno.agent import Agent
from agno.models.google import Gemini
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Output Schema
# ---------------------------------------------------------------------------


class TechnologyBrief(BaseModel):
    comparison: List[str] = Field(
        description="Key strengths and limitations of each technology"
    )
    recommendation: str = Field(
        description="Recommended technology and why it fits the requirements"
    )
    risks: List[str] = Field(
        description="Risks and unknowns to resolve before adoption"
    )
    sources: List[str] = Field(
        description="URLs of official documentation used in the comparison"
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Gemini(id="gemini-4-argon", search=True, url_context=True),
    output_schema=TechnologyBrief,
    instructions=[
        "Search for current official documentation and read the relevant pages.",
        "Compare each technology against the user's requirements and cite sources.",
        "Separate documented facts from assumptions. Do not invent benchmarks.",
    ],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "Compare PostgreSQL with pgvector and Qdrant for a multi-tenant RAG "
        "service with 10 million document chunks. We already use PostgreSQL "
        "and need hybrid keyword/vector search with tenant filtering. "
        "Recommend an option, explain the tradeoffs, and identify risks."
    )
