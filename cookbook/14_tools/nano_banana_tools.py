"""
Example showing how to use the NanoBananaTools toolkit with your Agno Agent.

Usage:
- Set your Google API key as environment variable: `export GOOGLE_API_KEY="your_api_key"`
- Run `pip install agno google-genai Pillow` to install dependencies
"""

from pathlib import Path

from agno.agent import Agent
from agno.tools.nano_banana import NanoBananaTools

# Example 1: Basic NanoBanana agent with default settings
agent = Agent(tools=[NanoBananaTools()], name="NanoBanana Image Generator")

# Example 2: Custom aspect ratio generator
portrait_agent = Agent(
    tools=[
        NanoBananaTools(
            aspect_ratio="2:3",  # Portrait orientation
        )
    ],
    name="Portrait NanoBanana Generator",
)

# Example 3: Widescreen generator for panoramic images
widescreen_agent = Agent(
    tools=[
        NanoBananaTools(
            aspect_ratio="16:9"  # Widescreen format
        )
    ],
    name="Widescreen NanoBanana Generator",
)

# Test basic generation
agent.print_response(
    "Generate an image of a futuristic city with flying cars",
    markdown=True,
)

# Generate and save an image
response = widescreen_agent.run(
    "Create a panoramic nature scene with mountains and a lake at sunset",
    markdown=True,
)

# Save the generated image if available
if response.images and response.images[0].content:
    output_path = Path("generated_image.png")
    with open(output_path, "wb") as f:
        f.write(response.images[0].content)

    print(f"✅ Image was succesfully generated and saved to: {output_path}")
