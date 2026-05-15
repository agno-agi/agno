"""
Gemini Interactions - Image Generation
=======================================

Example showing image generation with the Interactions API.
Uses response_modalities=["text", "image"] to enable image output.

Note: Image generation support depends on the model.
Not all models support image output through the Interactions API.
Check the Google AI docs for the latest supported models.
"""

from agno.agent import Agent
from agno.models.google import GeminiInteractions

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=GeminiInteractions(
        id="gemini-3-flash-preview",
        response_modalities=["text", "image"],
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    response = agent.run("Generate an image of a sunset over mountains")

    if response.images:
        for i, img in enumerate(response.images):
            filepath = f"generated_image_{i}.png"
            content = img.get_content_bytes()
            if content:
                with open(filepath, "wb") as f:
                    f.write(content)
                print(f"Saved image to {filepath}")
    else:
        print("No images generated (model may not support image output)")

    if response.content:
        print(f"Response: {response.content}")
