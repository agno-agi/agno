"""
Audio Understanding - Transcribe and Analyze Audio
====================================================
Pass audio files to Gemini for transcription, summarization, and analysis.

Key concepts:
- Audio(content=..., format=...): Pass audio bytes with format (mp3, wav, etc.)
- Native capability: No Whisper or speech-to-text APIs needed
- Multi-format: Supports MP3, WAV, FLAC, OGG, and more

Example prompts to try:
- "Transcribe and summarize this audio"
- "What language is being spoken?"
- "How many speakers are in this recording?"
- "What is the overall sentiment of this conversation?"
"""

import httpx
from agno.agent import Agent
from agno.media import Audio
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are an audio analysis expert. Transcribe and summarize audio content clearly.

## Rules

- Provide a complete transcription when asked
- Note speaker changes if multiple speakers
- Summarize key points after transcription\
"""

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
audio_agent = Agent(
    name="Audio Analyst",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
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

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
Audio input methods:

1. From URL (download first)
   import httpx
   response = httpx.get("https://example.com/audio.mp3")
   audio=[Audio(content=response.content, format="mp3")]

2. From local file
   audio_bytes = Path("recording.wav").read_bytes()
   audio=[Audio(content=audio_bytes, format="wav")]

3. Multiple audio files
   audio=[Audio(content=clip1, format="mp3"), Audio(content=clip2, format="mp3")]

Use cases for music/film/gaming:
- Transcribe podcast interviews for show notes
- Analyze music samples for mood and genre classification
- Extract dialogue from film clips for subtitle generation
- Analyze game audio for sound design review
"""
