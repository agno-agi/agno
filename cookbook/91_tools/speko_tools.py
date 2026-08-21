"""
Speko voice router tools: text-to-speech, speech-to-text, and voice discovery.

Requires the SPEKO_API_KEY environment variable.
Get an API key at https://platform.speko.ai (sign up, then mint a key under Keys).

Also requires GOOGLE_API_KEY for the agent's model. Use a model with audio input
support (Gemini here) so the agent can hear the audio it generates across multi-turn
conversations, instead of losing it after the first response.

Speko is a voice router: one API in front of many TTS/STT providers. Requests with
model="auto" (the default) are routed to the best provider by live benchmarks, with
automatic failover. Any routable "provider:model" ID can be pinned instead, and the
routing objective can be set to "latency", "quality", "cost", or "balanced".

Docs: https://speko.ai/docs (models and voices: GET https://api.speko.ai/v1/models)
"""

import base64
from textwrap import dedent

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.speko import SpekoTools
from agno.utils.media import save_base64_data

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


voice_agent = Agent(
    model=Gemini(id="gemini-pro-latest"),
    tools=[SpekoTools()],
    description="You are an AI agent that can generate and transcribe audio using the Speko voice router.",
    instructions=[
        dedent(
            """
            You have access to the Speko voice toolkit:
            - Use the `text_to_speech` tool to convert text into natural voice audio.
            - Use the `transcribe_audio` tool to transcribe an audio file to text.
            - Use the `list_voices` tool to see the available voices.
            Keep the audio prompt as defined by the user.
            """
        ),
    ],
    markdown=True,
)

# Pinned routing: a specific voice, latency-first objective
# pinned_voice_agent = Agent(
#     model=Gemini(id="gemini-pro-latest"),
#     tools=[
#         SpekoTools(
#             tts_model="deepgram:aura-2",
#             voice="aura-2-thalia-en",
#             objective="latency",
#         )
#     ],
#     description="You are an AI agent that generates audio with a pinned Speko voice.",
#     markdown=True,
# )

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    response = voice_agent.run(
        "Generate a short audio welcoming listeners to a podcast about the history of aviation.",
    )

    if response.audio:
        print("Agent response:", response.content)
        base64_audio = base64.b64encode(response.audio[0].content).decode("utf-8")
        save_base64_data(base64_audio, "tmp/podcast_welcome.wav")

    # response2 = voice_agent.run("Transcribe the audio file tmp/podcast_welcome.wav.")
    # print("Transcript:", response2.content)
