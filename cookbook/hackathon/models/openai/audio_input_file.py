from pathlib import Path

from agno.agent import Agent
from agno.media import Audio
from agno.models.openai import OpenAIChat

audio_path = Path(__file__).parent.parent.parent.joinpath("data/sample_audio.wav")

agent = Agent(
    model=OpenAIChat(id="gpt-4o-audio-preview", modalities=["text"]),
    markdown=True,
)
agent.print_response(
    "What is in this audio?", audio=[Audio(filepath=audio_path, format="wav")]
)
