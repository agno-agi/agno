"""Example showing how to use Azure OpenAI Tools with Agno.

Requirements:
1. Azure OpenAI service setup with DALL-E deployment and chat model deployment
2. Environment variables:
   - AZURE_OPENAI_API_KEY - Your Azure OpenAI API key
   - AZURE_OPENAI_ENDPOINT - The Azure OpenAI endpoint URL
   - AZURE_OPENAI_IMAGE_DEPLOYMENT - The deployment name for DALL-E
   - AZURE_OPENAI_LLM_DEPLOYMENT - The deployment name for the language model
   - OPENAI_API_KEY (for standard OpenAI example)

The script will automatically run only the examples for which you have the necessary
environment variables set.

Run `pip install agno` to install dependencies.
"""

from pathlib import Path
from os import getenv
import sys

from agno.agent import Agent
from agno.models.azure import AzureOpenAI
from agno.models.openai import OpenAIChat
from agno.tools.azure_openai import AzureOpenAITools
from agno.utils.media import download_image

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

common_instructions = [
    "You are an AI artist specializing in creating images based on user descriptions.",
    "Use the generate_image tool to create detailed visualizations of user requests.",
    "Provide creative suggestions to enhance the images if needed.",
]

# Example 1: Standard OpenAI model with Azure OpenAI Tools
if bool(getenv("OPENAI_API_KEY")):
    print("Running Example 1: Standard OpenAI model with Azure OpenAI Tools")
    print(
        "This approach uses OpenAI for the agent's model but Azure for image generation.\n"
    )

    standard_agent = Agent(
        model=OpenAIChat(id="gpt-4o"),  # Using standard OpenAI for the agent
        tools=[AzureOpenAITools()],  # Using Azure OpenAI for image generation
        name="Mixed OpenAI Generator",
        description="An AI assistant that uses standard OpenAI for chat and Azure OpenAI for image generation",
        instructions=common_instructions,
        show_tool_calls=True,
    )

    # Generate an image with the standard OpenAI model and Azure tools
    try:
        standard_agent.print_response(
            "Generate an image of a futuristic city with flying cars and tall skyscrapers",
            markdown=True,
        )
    except Exception as e:
        print(f"Error in Example 1: {e}")
else:
    print("Skipping Example 1: Missing required environment variables.")
    print("Required: OPENAI_API_KEY")

if bool(getenv("AZURE_OPENAI_LLM_DEPLOYMENT")):
    print("\nRunning Example 2: Full Azure OpenAI setup")
    print(
        "This approach uses Azure OpenAI for both the agent's model and image generation.\n"
    )

    # Create an AzureOpenAI model using Azure credentials
    azure_endpoint = getenv("AZURE_OPENAI_ENDPOINT")
    azure_api_key = getenv("AZURE_OPENAI_API_KEY")
    azure_deployment = getenv("AZURE_OPENAI_LLM_DEPLOYMENT")

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
        instructions=common_instructions,
        show_tool_calls=True,
    )

    # Generate an image with the full Azure setup
    try:
        azure_agent.print_response(
            "Generate an image of a serene Japanese garden with cherry blossoms",
            markdown=True,
        )
    except Exception as e:
        print(f"Error in Example 2: {e}")

    print("\nRunning Example 3: Automatic parameter enforcement demo")
    print(
        "This example demonstrates how invalid parameters are automatically corrected.\n"
    )

    # Print available image properties for reference
    print("Valid image properties:")
    print("- Models: dall-e-3, dall-e-2")
    print("- Sizes: 256x256, 512x512, 1024x1024, 1792x1024, 1024x1792")
    print("- Styles: vivid, natural\n")

    # Create AzureOpenAITools with explicit parameters
    azure_tools = AzureOpenAITools(
        api_key=getenv("AZURE_OPENAI_API_KEY"),
        azure_endpoint=getenv("AZURE_OPENAI_ENDPOINT"),
        dalle_deployment=getenv("AZURE_OPENAI_IMAGE_DEPLOYMENT"),
        dalle_model="dall-e-3",  # Explicitly set the model
    )

    # Create custom Azure OpenAI model
    custom_model = AzureOpenAI(
        azure_endpoint=getenv("AZURE_OPENAI_ENDPOINT"),
        azure_deployment=getenv("AZURE_OPENAI_LLM_DEPLOYMENT"),
        api_key=getenv("AZURE_OPENAI_API_KEY"),
        id=getenv("AZURE_OPENAI_LLM_DEPLOYMENT"),
    )

    custom_agent = Agent(
        model=custom_model,  # Using Azure OpenAI for the agent model
        tools=[azure_tools],
        name="Parameter Enforcement Demo",
        description="An AI assistant demonstrating automatic parameter enforcement",
        instructions=common_instructions,
        show_tool_calls=True,
    )

    # Generate an image - we'll instruct about invalid parameters in the prompt
    try:
        prompt = """Create a panoramic nature scene showing a peaceful mountain lake at sunset.

For this example, try using a mix of valid and invalid parameters to demonstrate enforcement:
1. Use a valid size='512x512' (this will work as-is)
2. Try using model='dall-e-4' (invalid model that will be corrected to dall-e-3)
3. Try using n=3 (invalid for dall-e-3, will be corrected to n=1)

This demonstrates how the tool intelligently handles parameters - it keeps valid ones you specify
while automatically correcting invalid ones to ensure the request succeeds.

Note: The tool has built-in parameter enforcement that will automatically correct
any invalid parameters to valid values, so your requests will still work."""

        response = custom_agent.run(prompt, markdown=True)

        # Save the generated image
        if response.images:
            output_dir = Path(__file__).parent.joinpath("tmp")
            output_dir.mkdir(exist_ok=True)
            download_image(
                url=response.images[0].url,
                output_path=output_dir.joinpath("azure_nature.jpg"),
            )
            print(f"Image saved to {output_dir.joinpath('azure_nature.jpg')}")

            # Verify the number of images generated
            print(f"Number of images generated: {len(response.images)}")
    except Exception as e:
        print(f"Error in Example 3: {e}")
else:
    print("\nSkipping Example 2 and 3: Missing required environment variables.")
    print("Required: AZURE_OPENAI_LLM_DEPLOYMENT\n")
