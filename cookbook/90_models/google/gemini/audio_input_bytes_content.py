"""
Google Audio Input Bytes Content
================================

Cookbook example for `google/gemini/audio_input_bytes_content.py`.
"""

import requests
from agno.agent import Agent
from agno.media import Audio
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Gemini(id="gemini-3-flash-preview"),
    markdown=True,
)

url = "https://openaiassets.blob.core.windows.net/$web/API/docs/audio/alloy.wav"

# Download the audio file from the URL as bytes
response = requests.get(url)
audio_content = response.content

agent.print_response(
    "Tell me about this audio",
    audio=[Audio(content=audio_content)],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
