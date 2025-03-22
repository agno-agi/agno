"""
Example script for using the Cartesia toolkit with an Agno agent for text-to-speech generation.
"""

import os
import sys

from agno.agent import Agent
from agno.tools.cartesia import CartesiaTools
from dotenv import load_dotenv

# Get Cartesia API key from environment or use a default for demo
cartesia_api_key = os.environ.get("CARTESIA_API_KEY", "sk_car_4y7Jz9aKsF6VeLpBKzKwJ")
load_dotenv()

# Create the agent with CartesiaTools
agent = Agent(
    tools=[CartesiaTools(api_key=cartesia_api_key)],
    show_tool_calls=True,
    instructions="""You are an expert assistant that uses Cartesia for high-quality speech synthesis.

MODELS:
- "sonic-2": Standard high-quality speech model - good for most general use cases
- "sonic-turbo": Enhanced model with better prosody and expression - use for premium quality

CAPABILITIES:
1. Generate speech (text_to_speech) - Convert text to spoken audio
2. Stream speech (text_to_speech_stream) - Generate speech with streaming output
3. Batch processing (batch_text_to_speech) - Convert multiple texts to speech at once
4. Voice management (list_voices, get_voice) - Browse and select voice options

PARAMETER GUIDELINES:
- Always specify a voice_id parameter when generating speech
- Use language codes (e.g., "en" for English, "fr" for French)
- For output formats, valid options include:
  * MP3: container="mp3", sample_rate=44100, bit_rate=128000
  * WAV: container="wav", sample_rate=44100, encoding="pcm_s16le"

EXAMPLES:
- For basic TTS: text_to_speech(transcript="Hello world", model_id="sonic-2", voice_id="[VOICE_ID]")
- For streaming: text_to_speech_stream(transcript="Hello world", model_id="sonic-2", voice_id="[VOICE_ID]")
- To list voices: list_voices()
- To get voice details: get_voice(voice_id="[VOICE_ID]")

Always check if operations succeeded by examining the "success" field in responses.
""",
)

# Choose which example to run (uncomment the one you want to try)

# Example 1: Basic TTS - Generate speech for a simple phrase
# agent.print_response(
#     "Generate speech for 'Welcome to Agno with Cartesia integration' using the sonic-2 model and save it as a high-quality MP3 file.",
#     markdown=True,
#     stream=False
# )

# Example 2: List available voices
# agent.print_response(
#     "List all available voices in Cartesia and show their IDs and descriptions.",
#     markdown=True,
#     stream=False
# )

# Example 3: Get details about a specific voice
# agent.print_response(
#     "Get information about the voice with ID 'f9836c6e-a0bd-460e-9d3c-f7299fa60f94'.",
#     markdown=True,
#     stream=False
# )

# Example 4: Batch TTS - Convert multiple text phrases to speech
# agent.print_response(
#     """Convert the following phrases to speech using the sonic-2 model and voice ID 'f9836c6e-a0bd-460e-9d3c-f7299fa60f94':
#     1. "Hello, welcome to our application."
#     2. "This is the second audio sample."
#     3. "Thank you for trying our speech synthesis."
#     """,
#     markdown=True,
#     stream=False
# )

# Example 5: Stream TTS - Generate speech with streaming capabilities
agent.print_response(
    "Generate streaming speech for 'This is a demonstration of streaming text-to-speech capabilities' using the sonic-turbo model.",
    markdown=True,
    stream=False,
)

# Example 6: TTS with different audio formats (WAV)
# agent.print_response(
#     "Generate speech for 'This is a WAV format audio sample' using sonic-2 model and save it as a WAV file with PCM 16-bit encoding.",
#     markdown=True,
#     stream=False
# )

# Example 7: TTS with a longer passage of text
# agent.print_response(
#     """Generate speech for the following paragraph using the sonic-turbo model:
#     'Artificial intelligence has transformed how we interact with technology.
#     Voice synthesis, in particular, has made remarkable progress, creating natural-sounding speech
#     that's almost indistinguishable from human voices. This technology enables
#     accessibility features, audiobook creation, and voice assistants that enrich our daily lives.'
#     """,
#     markdown=True,
#     stream=False
# )
