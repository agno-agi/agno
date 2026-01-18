"""Show special token metrics like audio, cached and reasoning tokens"""

import requests
from agno.agent import Agent
from agno.media import Audio
from agno.models.openai import OpenAIChat
from agno.utils.pprint import pprint_run_response

# Fetch the audio file and convert it to a base64 encoded string
url = "https://openaiassets.blob.core.windows.net/$web/API/docs/audio/alloy.wav"
response = requests.get(url)
response.raise_for_status()
wav_data = response.content

agent = Agent(
    model=OpenAIChat(
        id="gpt-4o-audio-preview",
        modalities=["text", "audio"],
        audio={"voice": "sage", "format": "wav"},
    ),
    markdown=True,
)
run_response = agent.run(
    "What's in these recording?",
    audio=[Audio(content=wav_data, format="wav")],
)
pprint_run_response(run_response)
# Showing input audio, output audio and total audio tokens metrics
print(f"Input audio tokens: {run_response.metrics.audio_input_tokens}")
print(f"Output audio tokens: {run_response.metrics.audio_output_tokens}")
print(f"Audio tokens: {run_response.metrics.audio_total_tokens}")

agent = Agent(
    model=OpenAIChat(id="o3-mini"),
    markdown=True,
    telemetry=False,
)
run_response = agent.run(
    "Solve the trolley problem. Evaluate multiple ethical frameworks. Include an ASCII diagram of your solution.",
    stream=False,
)
pprint_run_response(run_response)
# Showing reasoning tokens metrics
print(f"Reasoning tokens: {run_response.metrics.reasoning_tokens}")

agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), markdown=True, telemetry=False)
agent.run("Share a 2 sentence horror story" * 150)
run_response = agent.run("Share a 2 sentence horror story" * 150)
# Showing cached tokens metrics
print(f"Cached tokens: {run_response.metrics.cache_read_tokens}")
