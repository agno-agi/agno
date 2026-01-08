"""
Azure OpenAI Responses API - Tool Use Example

This example demonstrates using tools with Azure OpenAI Responses API.

Required environment variables:
    AZURE_OPENAI_API_KEY: Your Azure OpenAI API key
    AZURE_OPENAI_ENDPOINT: Your Azure OpenAI endpoint (e.g., https://your-resource.openai.azure.com/)

Note: The `id` parameter should be your Azure deployment name (e.g., "gpt-4o").
"""

from agno.agent import Agent
from agno.models.azure import AzureOpenAIResponses
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=AzureOpenAIResponses(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

agent.print_response("What's the latest news about AI agents?", stream=True)
