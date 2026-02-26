"""
9. Image Generation and Editing
================================
Gemini can generate and edit images using response_modalities=["Text", "Image"].
No external tools needed -- this is a native model capability.

Note: Do not provide a system message when using image generation.

Run:
    python cookbook/gemini_3/9_image_generation.py
"""

from io import BytesIO
from pathlib import Path

from agno.agent import Agent, RunOutput
from agno.media import Image
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------
WORKSPACE = Path(__file__).parent.joinpath("workspace")
WORKSPACE.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Create Agent (no system message for image generation)
# ---------------------------------------------------------------------------
image_gen_agent = Agent(
    name="Image Generator",
    model=Gemini(
        id="gemini-3-flash-preview",
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

        run_output = image_gen_agent.get_last_run_output()
        if run_output and isinstance(run_output, RunOutput) and run_output.images:
            for i, image_response in enumerate(run_output.images):
                image_bytes = image_response.content
                if image_bytes:
                    image = PILImage.open(BytesIO(image_bytes))
                    output_path = WORKSPACE / f"edited_{i}.png"
                    image.save(str(output_path))
                    print(f"Saved edited image to {output_path}")
        else:
            print("No edited images found in response")
