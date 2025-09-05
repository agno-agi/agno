import requests
from agno.agent import Agent
from agno.media import Audio
from agno.models.openai import OpenAIChat
from agno.utils.audio import write_audio_to_file
from rich.pretty import pprint

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

if run_response.response_audio is not None:
    pprint(run_response.content)
    write_audio_to_file(
        audio=run_response.response_audio.content, filename="tmp/result.wav"
    )
