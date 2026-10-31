"""Run an Agno agent through Azure OpenAI's Responses API.

Required environment variables:
    AZURE_OPENAI_API_KEY
    AZURE_OPENAI_ENDPOINT

Optional environment variables:
    OPENAI_API_VERSION (defaults to 2025-04-01-preview)
"""

from agno.agent import Agent
from agno.models.azure.openai_responses import AzureOpenAIResponses

agent = Agent(
    model=AzureOpenAIResponses(
        id="gpt-5.6-luna"
    ),  # Set to your Azure deployment name (deployments are often named after the model)
    markdown=True,
)

agent.print_response("Explain why regression tests matter in one paragraph.")
