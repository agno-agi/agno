from agno.agent import Agent
from agno.media import Audio
from agno.models.openai import OpenAIChat

# Fetch the audio file and convert it to a base64 encoded string
url = "https://openaiassets.blob.core.windows.net/$web/API/docs/audio/alloy.wav"

# Provide the agent with the audio file and get result as text
agent = Agent(
    model=OpenAIChat(id="gpt-4o-audio-preview", modalities=["text"]),
    markdown=True,
)
agent.print_response("What is in this audio?", audio=[Audio(url=url, format="wav")])
