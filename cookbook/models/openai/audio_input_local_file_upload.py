from pathlib import Path

from agno.agent import Agent
from agno.media import Audio
from agno.models.openai import OpenAIChat

# Provide the agent with the audio file and get result as text
agent = Agent(
    model=OpenAIChat(id="gpt-4o-audio-preview", modalities=["text"]),
    markdown=True,
)

# Please download a sample audio file to test this Agent and upload using:
audio_path = Path(__file__).parent.joinpath("sample.mp3")

agent.print_response(
    "Tell me about this audio",
    audio=[Audio(filepath=audio_path, format="mp3")],
    stream=True,
)
