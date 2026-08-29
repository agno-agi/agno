"""Run an Agno agent through Azure OpenAI's Responses API.

Required environment variables:
    AZURE_OPENAI_API_KEY
    AZURE_OPENAI_ENDPOINT
    OPENAI_API_VERSION
"""

from agno.agent import Agent
from agno.models.azure.openai_responses import AzureOpenAIResponses

agent = Agent(
    model=AzureOpenAIResponses(id="your-full-azure-deployment-name"),
    markdown=True,
)

agent.print_response("Explain why regression tests matter in one paragraph.")
