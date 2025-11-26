from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.nano_banana import NanoBananaTools
from db import demo_db

visual_storyteller_agent = Agent(
    name="Visual Storyteller",
    role="Create manga-style illustrated stories",
    model=Gemini(id="gemini-2.0-flash"),
    tools=[NanoBananaTools()],
    description="Create manga panels with text/dialogue embedded in the images.",
    instructions=dedent("""\
        Create manga panels with TEXT AND SPEECH BUBBLES EMBEDDED IN THE IMAGES.

        Each image should include:
        - The scene in anime/manga art style
        - Speech bubbles with SHORT dialogue (1-5 words)
        - Sound effects as stylized text (e.g., "WHOOSH!", "CRASH!")

        Image prompt format:
        "manga panel, anime style, [scene], speech bubble with text '[DIALOGUE]', 
        [character emotion], dramatic lighting, vibrant colors"

        Example:
        "manga panel, anime style, young astronaut discovering alien garden, 
        speech bubble with text 'WOW!', eyes wide with wonder, golden lighting, Mars landscape"

        Generate 3-5 panels. Keep speech bubble text VERY SHORT so it renders clearly.
        """),
    db=demo_db,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    enable_agentic_memory=True,
    enable_session_summaries=True,
    markdown=True,
)


def save_story_images(response, story_name: str = "story"):
    """Save generated images from the story to disk."""
    output_path = Path("story_output")
    output_path.mkdir(exist_ok=True)

    if response.images:
        for i, img in enumerate(response.images):
            if img.content:
                filename = output_path / f"{story_name}_scene_{i + 1}.png"
                with open(filename, "wb") as f:
                    f.write(img.content)
                print(f"Saved illustration: {filename}")


if __name__ == "__main__":
    story_prompt = """Create a 3-scene manga about:
    "A young pilot discovers her mech has a soul"

    Use anime art style with dramatic poses and expressions.
    Keep dialogue minimal and impactful."""

    visual_storyteller_agent.print_response(story_prompt, stream=True)

    if (
        visual_storyteller_agent.run_response
        and visual_storyteller_agent.run_response.images
    ):
        save_story_images(
            visual_storyteller_agent.run_response, "mars_garden_adventure"
        )
