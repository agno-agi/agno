from pathlib import Path
from textwrap import dedent

from agno.agent import Agent, RunOutput
from agno.models.google import Gemini
from agno.tools.nano_banana import NanoBananaTools
from db import demo_db

creative_studio_agent = Agent(
    name="Creative Studio",
    role="Generate stunning images from text descriptions",
    model=Gemini(id="gemini-3-pro-preview"),
    tools=[NanoBananaTools(model="gemini-2.5-flash-image")],
    description="You are an AI image generation agent that uses NanoBanana Tools to generate images.",
    instructions=dedent("""\
1. Proceed with generating images immediately when asked. Only ask for confirmation if the user query is not clear or you need more information.

2. Enhance prompts with: lighting, art style, mood, composition, colors. 

3. Keep prompts under 100 words for best results.

4. After the image is generated, briefly describe it. 
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

    run_response = creative_studio_agent.get_last_run_output()
    if run_response and isinstance(run_response, RunOutput) and run_response.images:
        save_images(run_response)
