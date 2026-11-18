"""
Openai Generate Images
======================

Cookbook example for `openai/chat/generate_images.py`.
"""

from pathlib import Path

from agno.agent import Agent, RunOutput
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIChat
from agno.tools.openai import OpenAITools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

image_agent = Agent(
    model=OpenAIChat(id="gpt-5.6-luna", reasoning_effort="none"),
    db=InMemoryDb(),
    tools=[OpenAITools(enable_transcription=False, enable_speech_generation=False)],
    description="You are an AI agent that can generate images.",
    instructions="When the user asks you to create an image, use the `generate_image` tool to create the image.",
    markdown=True,
)

image_agent.print_response("Generate an image of a white siamese cat")

# Retrieve and display generated images using get_last_run_output
run_response = image_agent.get_last_run_output()
if run_response and isinstance(run_response, RunOutput) and run_response.images:
    for image_response in run_response.images:
        if image_response.content:
            # GPT Image models return the image bytes directly
            output_path = Path(__file__).parent.joinpath(f"tmp/{image_response.id}.png")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(image_response.content)
            print(f"Image saved to {output_path}")
        else:
            print(image_response.url)
else:
    print("No images found in run response")

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
