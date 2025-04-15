"""🔊 Example: Using the OpenAITools Toolkit for Text-to-Speech

This script demonstrates how to use an agent to generate speech from a given text input and optionally save it to a specified audio file.

Run `pip install openai agno` to install the necessary dependencies.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.openai import OpenAITools

# Create a simple agent using the GPT-4o model and the OpenAI toolkit
agent: Agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[OpenAITools()],
    markdown=True,
    show_tool_calls=True,  # Show tool calls for clarity
)

text_to_synthesize: str = "Hello from Agno! This is a demonstration of the text-to-speech capability using OpenAI"
output_file: str = "speech_output.mp3"

agent.print_response(
    f"Please generate speech for the following text and save it to '{output_file}'. Text: \"{text_to_synthesize}\""
)
