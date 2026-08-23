"""
Agno Gateway - audio input
==========================

Send audio with ``audio=[Audio(...)]`` to an audio-capable model and get a text answer.
The class encodes audio into the OpenAI chat-completions content schema. The audio
model expects ``modalities`` set, which is passed through with ``request_params``.

Requires:
- AGNO_API_KEY  (or a provider key for BYOK, e.g. OPENAI_API_KEY for "openai/...")
"""

import requests
from agno.agent import Agent
from agno.media import Audio
from agno.models.agno import Agno

# ---------------------------------------------------------------------------
# Fetch a sample audio file
# ---------------------------------------------------------------------------

url = "https://openaiassets.blob.core.windows.net/$web/API/docs/audio/alloy.wav"
response = requests.get(url)
response.raise_for_status()
wav_data = response.content

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Agno(
        id="openai/gpt-4o-audio-preview",
        request_params={"modalities": ["text"]},
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "What is in this audio?",
        audio=[Audio(content=wav_data, format="wav")],
    )
