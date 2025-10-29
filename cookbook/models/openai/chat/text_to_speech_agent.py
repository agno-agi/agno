"""🔊 Example: Using the OpenAITools Toolkit for Text-to-Speech

This script demonstrates how to use an agent to generate speech from a given text input and optionally save it to a specified audio file.

Run `pip install openai agno` to install the necessary dependencies.
"""

import base64
from pathlib import Path

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.openai import OpenAITools
from agno.utils.media import save_base64_data

output_file: str = str(Path("tmp/speech_output.mp3"))

agent: Agent = Agent(
    model=Gemini(id="gemini-2.5-pro"),
    tools=[OpenAITools(enable_speech_generation=True)],
    markdown=True,
)

# Ask the agent to generate speech, but not save it
response = agent.run(
    'Please generate speech for the following text: "Hello from Agno! This is a demonstration of the text-to-speech capability using OpenAI"'
)

print(f"Agent response: {response.get_content_as_string()}")

if response.audio:
    base64_audio = base64.b64encode(response.audio[0].content).decode("utf-8")
    save_base64_data(base64_audio, output_file)
    print(f"Successfully saved generated speech to{output_file}")
