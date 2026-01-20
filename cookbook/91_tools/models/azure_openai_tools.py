"""Example showing how to use Azure OpenAI Tools with Agno.

Requirements:
1. Azure OpenAI service setup with DALL-E deployment and chat model deployment
2. Environment variables:
   - AZURE_OPENAI_API_KEY - Your Azure OpenAI API key
   - AZURE_OPENAI_ENDPOINT - The Azure OpenAI endpoint URL
   - AZURE_OPENAI_DEPLOYMENT - The deployment name for the language model
   - AZURE_OPENAI_IMAGE_DEPLOYMENT - The deployment name for an image generation model
   - OPENAI_API_KEY (for standard OpenAI example)

The script will automatically run only the examples for which you have the necessary
environment variables set.
"""

import sys
from os import getenv

from agno.agent import Agent
from agno.models.azure import AzureOpenAI
from agno.models.openai import OpenAIChat
from agno.tools.models.azure_openai import AzureOpenAITools

# Check for base requirements first - needed for all examples
# Exit early if base requirements aren't met
if not bool(
    getenv("AZURE_OPENAI_API_KEY")
    and getenv("AZURE_OPENAI_ENDPOINT")
    and getenv("AZURE_OPENAI_IMAGE_DEPLOYMENT")
):
    print("Error: Missing base Azure OpenAI requirements.")
    print("Required for all examples:")
    print("- AZURE_OPENAI_API_KEY")
    print("- AZURE_OPENAI_ENDPOINT")
    print("- AZURE_OPENAI_IMAGE_DEPLOYMENT")
    sys.exit(1)


print("Running Example 1: Standard OpenAI model with Azure OpenAI Tools")
print(
    "This approach uses OpenAI for the agent's model but Azure for image generation.\n"
)

standard_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),  # Using standard OpenAI for the agent
    tools=[AzureOpenAITools()],  # Using Azure OpenAI for image generation
    name="Mixed OpenAI Generator",
    description="An AI assistant that uses standard OpenAI for chat and Azure OpenAI for image generation",
    instructions=[
        "You are an AI artist specializing in creating images based on user descriptions.",
        "Use the generate_image tool to create detailed visualizations of user requests.",
        "Provide creative suggestions to enhance the images if needed.",
    ],
    debug_mode=True,
)

# Generate an image with the standard OpenAI model and Azure tools
standard_agent.print_response(
    "Generate an image of a futuristic city with flying cars and tall skyscrapers",
    markdown=True,
)

print("\nRunning Example 2: Full Azure OpenAI setup")
print(
    "This approach uses Azure OpenAI for both the agent's model and image generation.\n"
)

# Create an AzureOpenAI model using Azure credentials
azure_endpoint = getenv("AZURE_OPENAI_ENDPOINT")
azure_api_key = getenv("AZURE_OPENAI_API_KEY")
azure_deployment = getenv("AZURE_OPENAI_DEPLOYMENT")

# Explicitly pass all parameters to make debugging easier
azure_model = AzureOpenAI(
    azure_endpoint=azure_endpoint,
    azure_deployment=azure_deployment,
    api_key=azure_api_key,
    id=azure_deployment,  # Using the deployment name as the model ID
)

# Create an agent with Azure OpenAI model and tools
azure_agent = Agent(
    model=azure_model,  # Using Azure OpenAI for the agent
    tools=[AzureOpenAITools()],  # Using Azure OpenAI for image generation
    name="Full Azure OpenAI Generator",
    description="An AI assistant that uses Azure OpenAI for both chat and image generation",
    instructions=[
        "You are an AI artist specializing in creating images based on user descriptions.",
        "Use the generate_image tool to create detailed visualizations of user requests.",
        "Provide creative suggestions to enhance the images if needed.",
    ],
)

# Generate an image with the full Azure setup
azure_agent.print_response(
    "Generate an image of a serene Japanese garden with cherry blossoms",
    markdown=True,
)
