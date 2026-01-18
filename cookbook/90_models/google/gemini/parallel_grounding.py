"""Grounding with Parallel Web Search on Vertex AI.

Parallel Web Systems offers a search API optimized for LLM grounding,
providing access to live web data from billions of pages. This is available
exclusively on Vertex AI through a native first-party integration.

Note: This uses the dedicated `parallelAiSearch` tool type in Vertex AI,
which is different from the generic `ExternalApi` approach. Parallel has
a native integration with Google Cloud that handles authentication and
API communication automatically.

Requirements:
- Set up Google Cloud credentials: `gcloud auth application-default login`
- Get a Parallel API key from https://parallel.ai
- Set environment variables:
  - GOOGLE_CLOUD_PROJECT: Your GCP project ID
  - GOOGLE_CLOUD_LOCATION: Your GCP region (e.g., us-central1)
  - PARALLEL_API_KEY: Your Parallel API key

Run `pip install google-genai` to install dependencies.

For more information, see:
- https://docs.cloud.google.com/vertex-ai/generative-ai/docs/grounding/grounding-with-parallel
- https://docs.parallel.ai/integrations/google-vertex
"""

from agno.agent import Agent
from agno.models.google import Gemini

# Create an agent with Parallel web search grounding
agent = Agent(
    model=Gemini(
        id="gemini-2.0-flash",
        vertexai=True,  # Required for Parallel grounding
        parallel_search=True,
        # Optional: provide API key directly instead of env var
        # parallel_api_key="your-api-key",
    ),
    add_datetime_to_context=True,
    markdown=True,
)

# Ask questions that benefit from real-time web information
agent.print_response(
    "What are the latest developments in quantum computing this week?",
    stream=True,
)

# The response will include citations from Parallel's web search results
agent.print_response(
    "What are the top trending topics in AI research today?",
    stream=True,
)
