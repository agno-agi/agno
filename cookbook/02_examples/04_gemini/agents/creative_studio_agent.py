from pathlib import Path
from textwrap import dedent

from agno.agent import Agent, RunOutput
from agno.models.google import Gemini
from agno.tools.nano_banana import NanoBananaTools
from db import gemini_agents_db

creative_studio_agent = Agent(
    name="Creative Studio Agent",
    model=Gemini(id="gemini-3-flash-preview"),
    tools=[NanoBananaTools(model="gemini-2.5-flash-image")],
    instructions=dedent("""\
    You are a creative image generation agent.
    Your task is to transform short user ideas into high-quality, visually coherent images using the image generation tool.

    When generating images:
    1. Act immediately. Only ask clarifying questions if the request is ambiguous or missing a critical detail.
    2. Expand the prompt internally to include:
        - Subject and environment
        - Composition and camera framing
        - Lighting and color palette
        - Mood or atmosphere
        - Art style or visual reference (when appropriate)
    3. Keep the final image prompt under 100 words.
    4. Prefer concrete visual details over abstract language.
    5. Avoid contradictory styles or overcrowded scenes.

    After image generation:
    1. Provide a brief 1–2 sentence caption describing the image.
    2. Do not explain the prompt engineering or internal steps unless explicitly asked.\
    """),
    db=gemini_agents_db,
    # Add the current date and time to the context
    add_datetime_to_context=True,
    # Add the history of the agent's runs to the context
    add_history_to_context=True,
    # Number of historical runs to include in the context
    num_history_runs=3,
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
        "A surreal desert landscape with floating monoliths, golden hour lighting, dreamlike atmosphere",
        stream=True,
    )

    run_response = creative_studio_agent.get_last_run_output()
    if run_response and isinstance(run_response, RunOutput) and run_response.images:
        save_images(run_response)
