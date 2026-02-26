"""
10. Audio Understanding
=======================
Gemini can process audio files -- transcribe, summarize, and answer questions.
Pass audio as bytes content with the appropriate MIME type.

Run:
    python cookbook/gemini_3/10_audio_input.py

Note: Uses a sample audio file from a public URL.
"""

import httpx

from agno.agent import Agent
from agno.media import Audio
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
audio_agent = Agent(
    name="Audio Analyst",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions="You are an audio analysis expert. Transcribe and summarize audio content clearly.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Download a sample audio file
    url = "https://agno-public.s3.amazonaws.com/demo/sample-audio.mp3"
    response = httpx.get(url)

    audio_agent.print_response(
        "Transcribe and summarize this audio.",
        audio=[
            Audio(content=response.content, format="mp3"),
        ],
        stream=True,
    )
