"""🔊 Example: Using the OpenAITools Toolkit for Text-to-Speech

This script demonstrates how to use an agent to generate speech from a given text input and optionally save it to a specified audio file.

Run `pip install openai agno` to install the necessary dependencies.
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.openai import OpenAITools
from agno.utils.media import save_base64_data

output_file: str = Path("tmp/speech_output.mp3")

agent: Agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[OpenAITools()],
    markdown=True,
    show_tool_calls=True,
)

# Ask the agent to generate speech, but not save it
response = agent.run(
    f'Please generate speech for the following text: "Hello from Agno! This is a demonstration of the text-to-speech capability using OpenAI"'
)

print(f"Agent response: {response.get_content_as_string()}")

if response.audio:
    save_base64_data(response.audio[0].base64_audio, output_file)
    print(f"Successfully saved generated speech to{output_file}")
