"""Audio understanding with a vLLM-served model that supports audio.

We use Ultravox v0.5 (1-B) which is fully open and speaks the OpenAI Audio
schema.  Start the server first:

    vllm serve fixie-ai/ultravox-v0_5-llama-3_2-1b \
      --dtype float32

Then execute this script – it streams an audio file to the model and prints the
transcript / description.
"""

import requests
from agno.agent import Agent
from agno.media import Audio
from agno.models.vllm import Vllm

# Download a small WAV sample (same one used in OpenAI docs)
audio_url = "https://openaiassets.blob.core.windows.net/$web/API/docs/audio/alloy.wav"
resp = requests.get(audio_url, timeout=30)
resp.raise_for_status()

agent = Agent(
    model=Vllm(id="fixie-ai/ultravox-v0_5-llama-3_2-1b", modalities=["text"]),
    markdown=True,
)

agent.print_response(
    "What is in this audio?",
    audio=[Audio(content=resp.content, format="wav")],
    stream=True,
)
