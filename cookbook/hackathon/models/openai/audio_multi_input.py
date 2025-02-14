import requests
from agno.agent import Agent, RunResponse  # noqa
from agno.media import Audio
from agno.models.openai import OpenAIChat

# Fetch the audio file and convert it to a base64 encoded string
url = "https://openaiassets.blob.core.windows.net/$web/API/docs/audio/alloy.wav"
response = requests.get(url)
response.raise_for_status()
wav_data = response.content

# Provide the agent with the audio file and get result as text
agent = Agent(
    model=OpenAIChat(
        id="gpt-4o-audio-preview",
        modalities=["text", "audio"],
        audio={"voice": "alloy", "format": "wav"},
    ),
    markdown=True,
    add_history_to_messages=True,
    num_history_responses=3,
    debug_mode=True,
)
agent.print_response(
    "What is in this audio?", audio=[Audio(content=wav_data, format="wav")]
)

agent.print_response("What else can you tell me about it?")
