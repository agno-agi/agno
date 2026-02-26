"""
Image Generation and Editing - Create and Modify Images
=========================================================
Generate and edit images natively with Gemini. No external tools needed.

Key concepts:
- response_modalities=["Text", "Image"]: Tells Gemini to output both text and images
- RunOutput.images: Access generated images from the response
- Image editing: Pass an existing image + instructions to modify it
- No system message: Image generation does not support system instructions

Example prompts to try:
- "Make me an image of a cat sitting in a tree"
- "Create a minimalist logo for a coffee shop called 'Bean Scene'"
- "Generate a fantasy landscape with mountains and a castle"
"""

from io import BytesIO
from pathlib import Path

from agno.agent import Agent, RunOutput
from agno.media import Image
from agno.models.google import Gemini

WORKSPACE = Path(__file__).parent.joinpath("workspace")
WORKSPACE.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Create Agent (no system message, required for image generation)
# ---------------------------------------------------------------------------
image_gen_agent = Agent(
    name="Image Generator",
    model=Gemini(
        id="gemini-3.1-flash-image-preview",
        # Enable both text and image output
        response_modalities=["Text", "Image"],
    ),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        from PIL import Image as PILImage
    except ImportError:
        raise ImportError("Install Pillow to run this example: pip install Pillow")

    # --- Generate an image ---
    print("Generating an image...")
    run_response = image_gen_agent.run("Make me an image of a cat sitting in a tree.")

    if run_response and isinstance(run_response, RunOutput) and run_response.images:
        for i, image_response in enumerate(run_response.images):
            image_bytes = image_response.content
            if image_bytes:
                image = PILImage.open(BytesIO(image_bytes))
                output_path = WORKSPACE / f"generated_{i}.png"
                image.save(str(output_path))
                print(f"Saved generated image to {output_path}")
    else:
        print("No images found in response")

    # --- Edit an existing image ---
    print("\nEditing the generated image...")
    generated_path = WORKSPACE / "generated_0.png"
    if generated_path.exists():
        edit_response = image_gen_agent.run(
            "Add a rainbow in the sky of this image.",
            images=[Image(filepath=str(generated_path))],
        )

        if (
            edit_response
            and isinstance(edit_response, RunOutput)
            and edit_response.images
        ):
            for i, image_response in enumerate(edit_response.images):
                image_bytes = image_response.content
                if image_bytes:
                    image = PILImage.open(BytesIO(image_bytes))
                    output_path = WORKSPACE / f"edited_{i}.png"
                    image.save(str(output_path))
                    print(f"Saved edited image to {output_path}")
        else:
            print("No edited images found in response")

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
Image generation tips:

1. Be specific in prompts
   "A watercolor painting of a sunset over the ocean with warm orange tones"
   is better than "sunset painting"

2. Image editing workflow
   # Generate
   result = agent.run("Create a logo for a tech startup")
   # Edit
   result = agent.run("Make the colors more vibrant", images=[...])
   # Iterate
   result = agent.run("Add the text 'ACME' below the logo", images=[...])

3. No system message allowed
   Image generation models don't support instructions=... on the agent.
   Put guidance directly in the prompt instead.

Use cases for music/film/gaming:
- Generate album cover concepts from descriptions
- Create character concept art for games
- Produce storyboard frames from scene descriptions
- Design promotional materials and posters
"""
