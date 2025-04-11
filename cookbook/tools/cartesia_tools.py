"""
pip install cartesia
Get an API key from https://play.cartesia.ai/keys
"""

from agno.agent import Agent
from agno.tools.cartesia import CartesiaTools

# Initialize Agent with Cartesia tools
agent = Agent(
    name="Cartesia TTS Agent",
    description="An agent that uses Cartesia for text-to-speech.",
    tools=[CartesiaTools()],
)

# Example 1: Simple Text-to-Speech
agent.print_response(
    f"""Generate a simple greeting using Text-to-Speech:

    Say "Welcome to Cartesia, the advanced speech synthesis platform."

    Please use:
    - MP3 format with good quality
    - A natural speaking pace"""
)

# Example 2: Audiobook Production
# Uses streaming for longer content and voice control
# agent.print_response(
#     f"""Create an audiobook sample:

#     "Once upon a time, in a distant land, there lived a wise old dragon.
#     The dragon had guarded its mountain cave for centuries, watching as kingdoms
#     rose and fell in the valley below. One day, a young knight approached the
#     mountain, not with a sword, but with a book of poetry."

#     Focus on:
#     - MP3 format with high quality
#     - A moderate speaking pace
#     """,
#     markdown=True,
#     stream=False,
# )

# Example 7: Voice Emotion and Speed Control
# Demonstrates voice control parameters
# agent.print_response(
#     f"""Create three versions of this public safety announcement with different urgency levels:

#     "Please evacuate the building immediately and proceed to the nearest exit."

#     Generate:
#     1. Regular version - neutral tone at normal pace
#     2. Urgent version - faster pace with mild urgency
#     3. Emergency version - fastest pace with high urgency

#     Use:
#     - The sonic-turbo model for more natural emotional expression
#     """,
#     markdown=True,
#     stream=False,
# )
