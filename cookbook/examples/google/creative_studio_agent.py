from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.nano_banana import NanoBananaTools
from db import demo_db

creative_studio_agent = Agent(
    name="Creative Studio",
    role="Generate stunning images from text descriptions",
    model=Gemini(id="gemini-2.0-flash"),
    tools=[NanoBananaTools()],
    description="AI image generation using Google's NanoBanana toolkit.",
    instructions=dedent("""\
        Generate images immediately when asked. Never ask for confirmation.

        Enhance prompts with: lighting, art style, mood, composition, colors.
        Keep prompts under 50 words for best results.

        Example prompt: "Cyberpunk samurai in neon rain, dramatic rim lighting, 
        detailed armor with glowing accents, rain reflections, cinematic composition"

        After generating, briefly describe what was created.
        """),
    db=demo_db,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=3,
    enable_agentic_memory=True,
    markdown=True,
)


def save_images(response, output_dir: str = "generated_images"):
    """Save generated images from response to disk."""
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    if response.images:
        for img in response.images:
            if img.content:
                filename = output_path / f"image_{img.id[:8]}.png"
                with open(filename, "wb") as f:
                    f.write(img.content)
                print(f"Saved: {filename}")


if __name__ == "__main__":
    creative_studio_agent.print_response(
        "Create an image of a futuristic city at sunset with flying vehicles and neon lights",
        stream=True,
    )

    if creative_studio_agent.run_response and creative_studio_agent.run_response.images:
        save_images(creative_studio_agent.run_response)
