"""
Agno Gateway - audio output
===========================

Ask an audio-capable model to reply with speech. Set both ``text`` and ``audio``
modalities and the audio config with ``request_params``; the returned audio is decoded
onto ``response.response_audio`` and written to a file.

Requires:
- AGNO_API_KEY  (or a provider key for BYOK, e.g. OPENAI_API_KEY for "openai/...")
"""

from agno.agent import Agent
from agno.models.agno import Agno
from agno.utils.audio import write_audio_to_file

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Agno(
        id="openai/gpt-4o-audio-preview",
        request_params={
            "modalities": ["text", "audio"],
            "audio": {"voice": "alloy", "format": "wav"},
        },
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    response = agent.run("Tell me a 2 sentence horror story.")
    if response.response_audio is not None:
        write_audio_to_file(
            audio=response.response_audio.content, filename="tmp/horror_story.wav"
        )
        print("Audio saved to tmp/horror_story.wav")
