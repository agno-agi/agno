"""
Example showing how to use the HuggingFaceImageTools toolkit with your Agno Agent.

Generates images from text prompts using the Hugging Face Inference API.
Supports any text-to-image model hosted on Hugging Face Hub (FLUX, Stable Diffusion, etc.).
Default model: black-forest-labs/FLUX.1-schnell (Apache 2.0, free tier compatible).

Usage:
- Set your Hugging Face token as environment variable: `export HF_TOKEN="hf_xxxxx"`
- Run `uv pip install agno huggingface_hub` to install dependencies
"""

from agno.agent import Agent
from agno.tools.huggingface_images import HuggingFaceImageTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Example 1: Basic image generation with default model (FLUX.1 Schnell)
agent = Agent(
    tools=[HuggingFaceImageTools()],
    name="HuggingFace Image Generator",
)

# Example 2: Custom model and provider
agent_custom = Agent(
    tools=[
        HuggingFaceImageTools(
            model="black-forest-labs/FLUX.1-dev",
            provider="hf-inference",
            image_format="png",
        )
    ],
    name="Custom HuggingFace Generator",
)

# Example 3: With explicit API key
agent_with_key = Agent(
    tools=[HuggingFaceImageTools(api_key="hf_xxxxx")],
    name="HuggingFace Generator with Key",
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Generate an image of a futuristic city with flying cars and tall skyscrapers",
        markdown=True,
    )

    response = agent_custom.run(
        "Create a peaceful mountain lake at sunset",
        markdown=True,
    )
    if response.images:
        for img in response.images:
            print(f"Image ID: {img.id}, Size: {len(img.content)} bytes")
