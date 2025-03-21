"""
Example script for using the Cartesia toolkit with an Agno agent for text-to-speech generation.
"""

from dotenv import load_dotenv
from agno.agent import Agent
from agno.tools.cartesia import CartesiaTools
import os
import sys

# Get Cartesia API key from environment or use a default for demo
cartesia_api_key = os.environ.get("CARTESIA_API_KEY", "sk_car_4y7Jz9aKsF6VeLpBKzKwJ")
load_dotenv()

agent = Agent(
    tools=[CartesiaTools(api_key=cartesia_api_key)],
    show_tool_calls=True,
    instructions="Use Cartesia for text-to-speech generation"
)

# Example TTS request
agent.print_response(
    "Generate speech for 'Welcome to Agno with Cartesia integration' using the sonic-2 model and save it as a high-quality MP3 file.",
    markdown=True,
    stream=False
)