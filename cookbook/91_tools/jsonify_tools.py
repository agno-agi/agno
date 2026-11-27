"""
Jsonify Tools
=============================

Reads rows from a Jsonify dataset. Jsonify pipelines run on a schedule and repair
themselves when a source changes, so the agent reads maintained data instead of
scraping.

Prerequisites:
- Create a dataset at https://www.jsonify.com and open Integrations > REST API
- Set the serve URL as an environment variable:
    export JSONIFY_SERVE_URL=https://factory.jsonify.com/api/serve/<id>

The serve URL below is a public demo dataset: current API pricing for text and
chat models from OpenAI, Anthropic, Google, Mistral and DeepSeek.
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.jsonify import JsonifyTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


agent = Agent(
    model=Claude(id="claude-sonnet-4-5"),
    tools=[
        JsonifyTools(
            datasets={
                "llm_api_pricing": "https://factory.jsonify.com/api/serve/4f4980ec5c28",
            }
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Which models cost under $1 per million input tokens? Show provider, model and price.",
        stream=True,
    )
