"""
pip install elevenlabs
"""

import base64
from textwrap import dedent

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.eleven_labs import ElevenLabsTools
from agno.utils.media import save_base64_data

audio_agent = Agent(
    model=Gemini(id="gemini-2.5-pro"),
    tools=[
        ElevenLabsTools(
            voice_id="21m00Tcm4TlvDq8ikWAM",
            model_id="eleven_multilingual_v2",
        )
    ],
    description="You are an AI agent that can generate audio using the ElevenLabs API.",
    instructions=[
        dedent(
            """
            You have access to the ElevenLabs toolkit:
            - Use the `text_to_speech` tool to convert text or speech content into natural voice audio.
            - Use the `generate_sound_effect` tool to create sound effects from text descriptions.
            Keep the audio prompt as defined by the user.
            """
        ),
    ],
    markdown=True,
)

response = audio_agent.run(
    "Generate a very long audio of history of french revolution and tell me which subject it belongs to.",
)

if response.audio:
    print("Agent response:", response.content)
    base64_audio = base64.b64encode(response.audio[0].content).decode("utf-8")
    save_base64_data(base64_audio, "tmp/french_revolution.mp3")

# response2 = audio_agent.run("Generate a glass breaking sound effect" , debug_mode=True)
# if response2.audio:
#     print("Agent response:", response2.content)
#     base64_audio = base64.b64encode(response2.audio[0].content).decode("utf-8")
#     save_base64_data(base64_audio, "tmp/glass_breaking_sound_effect.mp3")
