import httpx
from agno.agent import Agent, RunOutput  # noqa
from agno.media import Audio
from agno.models.google import Gemini
from pydantic import BaseModel, Field


class Transcription(BaseModel):
    transcript: str = Field(..., description="The transcript of the audio conversation")
    description: str = Field(..., description="A description of the audio conversation")
    speakers: list[str] = Field(
        ..., description="The speakers in the audio conversation"
    )


# Fetch the audio file and convert it to a base64 encoded string
url = "https://openaiassets.blob.core.windows.net/$web/API/docs/audio/alloy.wav"
response = httpx.get(url)
response.raise_for_status()
wav_data = response.content

# Provide the agent with the audio file and get result as text
agent = Agent(
    model=Gemini(id="gemini-3-flash-preview"),
    markdown=True,
    output_schema=Transcription,
)

agent.print_response(
    "Tell me about this audio",
    audio=[Audio(content=wav_data)],
)
