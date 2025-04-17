import requests
from agno.agent import Agent
from agno.media import Audio
from agno.models.openai import OpenAIChat

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
agent.run(
    "What's in these recording?",
    audio=[Audio(content=wav_data, format="wav")],
)
# Showing input audio, output audio and total audio tokens metrics
print(f"Input audio tokens: {agent.run_response.metrics['input_audio_tokens']}")
print(f"Output audio tokens: {agent.run_response.metrics['output_audio_tokens']}")
print(f"Audio tokens: {agent.run_response.metrics['audio_tokens']}")

agent = Agent(
    model=OpenAIChat(id="o3-mini"), markdown=True, telemetry=False, monitoring=False
)
response = agent.run(
    "Solve the trolley problem. Evaluate multiple ethical frameworks. Include an ASCII diagram of your solution.",
    stream=False,
)
# Showing reasoning tokens metrics
print(f"Reasoning tokens: {agent.run_response.metrics['reasoning_tokens']}")


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"), markdown=True, telemetry=False, monitoring=False
)
agent.run("Share a 2 sentence horror story" * 150)
response = agent.run("Share a 2 sentence horror story" * 150)
# Showing cached tokens metrics
print(f"Cached tokens: {agent.run_response.metrics['cached_tokens']}")
