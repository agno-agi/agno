"""🔧 Example: Using the GeminiTools Toolkit for Image Generation

An Agent using the Gemini image generation tool.

Example prompts to try:
- "Generate an image of a dog and tell me the color of the dog"
- "Create an image of a cat driving a car"

Run `pip install google-genai agno` to install the necessary dependencies.
"""

import base64

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.models.gemini import GeminiTools
from agno.utils.media import save_base64_data

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[GeminiTools()],
    debug_mode=True,
)

response = agent.run(
    "Generate an image of a dog and tell me the color of the dog",
)

if response and response.images:
    for image in response.images:
        if image.content:
            image_base64 = base64.b64encode(image.content).decode("utf-8")
            save_base64_data(
                base64_data=image_base64,
                output_path=f"tmp/dog_{image.id}.png",
            )
            print(f"Image saved to tmp/dog_{image.id}.png")
