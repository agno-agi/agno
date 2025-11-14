"""Run `pip install openai agno` to install dependencies.

This example demonstrates how to use NebiusTools for text-to-image generation with Nebius Token Factory.
"""

import base64
import os
from pathlib import Path
from uuid import uuid4

from agno.agent import Agent
from agno.tools.models.nebius import NebiusTools
from agno.utils.media import save_base64_data

# Create an Agent with the Nebius text-to-image tool
agent = Agent(
    tools=[
        NebiusTools(
            # You can provide your API key here or set the NEBIUS_API_KEY environment variable
            api_key=os.getenv("NEBIUS_API_KEY"),
            image_model="black-forest-labs/flux-schnell",  # Fastest model
            image_size="1024x1024",
            image_quality="standard",
        )
    ],
    name="Nebius Image Generator",
    markdown=True,
)

# Example 1: Generate a basic image
response = agent.run(
    "Generate an image of a futuristic city with flying cars and tall skyscrapers",
)

if response.images:
    image_path = Path("tmp") / f"nebius_futuristic_city_{uuid4()}.png"
    Path("tmp").mkdir(exist_ok=True)
    image_base64 = base64.b64encode(response.images[0].content).decode("utf-8")
    save_base64_data(
        base64_data=image_base64,
        output_path=str(image_path),
    )
    print(f"Image saved to {image_path}")

# Example 2: Generate an image with the higher quality model
high_quality_agent = Agent(
    tools=[
        NebiusTools(
            api_key=os.getenv("NEBIUS_API_KEY"),
            image_model="black-forest-labs/flux-dev",  # Better quality model
            image_size="1024x1024",
            image_quality="hd",  # Higher quality setting
        )
    ],
    name="Nebius High-Quality Image Generator",
    markdown=True,
)

response = high_quality_agent.run(
    "Create a detailed portrait of a cyberpunk character with neon lights",
)

# Save the generated image
if response.images:
    image_path = Path("tmp") / f"nebius_cyberpunk_character_{uuid4()}.png"
    Path("tmp").mkdir(exist_ok=True)
    image_base64 = base64.b64encode(response.images[0].content).decode("utf-8")
    save_base64_data(
        base64_data=image_base64,
        output_path=str(image_path),
    )
    print(f"High-quality image saved to {image_path}")

# Example 3: Generate an image with the SDXL (Stability Diffusion XL model) model
sdxl_agent = Agent(
    tools=[
        NebiusTools(
            api_key=os.getenv("NEBIUS_API_KEY"),
            image_model="stability-ai/sdxl",  # Stability Diffusion XL model
            image_size="1024x1024",
        )
    ],
    name="Nebius SDXL Image Generator",
    markdown=True,
)

response = sdxl_agent.run(
    "Create a fantasy landscape with a castle on a floating island",
)

# Save the generated image
if response.images:
    image_path = Path("tmp") / f"nebius_fantasy_landscape_{uuid4()}.png"
    Path("tmp").mkdir(exist_ok=True)
    image_base64 = base64.b64encode(response.images[0].content).decode("utf-8")
    save_base64_data(
        base64_data=image_base64,
        output_path=str(image_path),
    )
    print(f"SDXL image saved to {image_path}")
