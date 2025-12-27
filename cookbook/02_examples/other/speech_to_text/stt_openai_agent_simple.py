"""
Speech to text example using OpenAI. This cookbook demonstrates how to transcribe audio files using OpenAI and obtain simple transcription.
"""

import httpx
from agno.agent import Agent, RunOutput  # noqa
from agno.media import Audio
from agno.models.openai import OpenAIChat

INSTRUCTIONS = """
Transcribe the audio accurately and completely.

Speaker identification:
- Use the speaker's name if mentioned in the conversation
- Otherwise use 'Speaker 1', 'Speaker 2', etc. consistently

Non-speech audio:
- Note significant non-speech elements (e.g., [long pause], [music], [background noise]) only when relevant to understanding the conversation
- Ignore brief natural pauses

Include everything spoken, even false starts and filler words (um, uh, etc.).
"""

# Fetch the audio file and convert it to a base64 encoded string
# Simple audio file with a single speaker
# url = "https://openaiassets.blob.core.windows.net/$web/API/docs/audio/alloy.wav"
# Audio file with multiple speakers
url = "https://agno-public.s3.us-east-1.amazonaws.com/demo_data/sample_audio.wav"

try:
    response = httpx.get(url)
    response.raise_for_status()
    wav_data = response.content
except httpx.HTTPStatusError as e:
    raise ValueError(f"Error fetching audio file: {url}") from e

# Provide the agent with the audio file and get result as text
agent = Agent(
    model=OpenAIChat(id="gpt-audio-2025-08-28", modalities=["text"]),
    markdown=True,
    instructions=INSTRUCTIONS,
)
agent.print_response(
    "What is in this audio?", audio=[Audio(content=wav_data, format="wav")]
)
