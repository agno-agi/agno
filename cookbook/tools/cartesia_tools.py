from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.cartesia import CartesiaTools

"""
Requirements:
- Cartesia API key (Get from https://play.cartesia.ai/keys)
- pip install cartesia

Usage:
- Set the following environment variable:
    export CARTEISIA_API_KEY="your_api_key"

- Or provide it when creating the CartesiaTools instance
"""

agent = Agent(
    name="Cartesia Voice Assistant",
    model=OpenAIChat(id="gpt-4o"),
    tools=[CartesiaTools()],
    show_tool_calls=True,
    markdown=True,
)

agent.print_response("List all available voices in Cartesia.")
# agent.print_response("Generate speech for the text 'Welcome to Cartesia voice technology' using an english female voice")
# agent.print_response("How can I clone a voice from an audio file?")

