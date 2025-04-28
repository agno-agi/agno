# hello
"""🔧 Example: Using the GeminiTools Toolkit for Video Generation

An Agent using the Gemini video generation tool.

Make sure you have set the GOOGLE_API_KEY (or use Vertex AI credentials).
Example prompts to try:
- "Generate a 5-second video of a kitten playing a piano"
- "Create a short looping animation of a neon city skyline at dusk"

Run `pip install google-genai agno` to install the necessary dependencies.
"""

import base64
import os
from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.models.gemini import GeminiTools
from agno.utils.media import save_base64_data, download_video

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[GeminiTools()],
    show_tool_calls=True,
    debug_mode=True,
)

agent.print_response(
    "create a video of a cat driving at top speed",
)
response = agent.run_response
if response.videos:
    save_base64_data(response.videos[0].content, "tmp/cat_driving.mp4")
