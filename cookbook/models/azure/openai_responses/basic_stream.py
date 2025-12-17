"""
Azure OpenAI Responses API - Streaming Example

This example demonstrates streaming responses using Azure OpenAI Responses API.

Required environment variables:
    AZURE_OPENAI_API_KEY: Your Azure OpenAI API key
    AZURE_OPENAI_ENDPOINT: Your Azure OpenAI endpoint (e.g., https://your-resource.openai.azure.com/)
    AZURE_OPENAI_DEPLOYMENT: Your Azure deployment name
"""

from agno.agent import Agent
from agno.models.azure import AzureOpenAIResponses

agent = Agent(
    model=AzureOpenAIResponses(id="gpt-4o"),
    markdown=True,
)

# Print the response on the terminal with streaming
agent.print_response("Share a 2 sentence horror story", stream=True)
