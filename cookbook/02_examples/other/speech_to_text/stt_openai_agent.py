import httpx
from agno.agent import Agent, RunOutput  # noqa
from agno.media import Audio
from agno.models.openai import OpenAIChat
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
    model=OpenAIChat(id="gpt-4o-audio-preview", modalities=["text"]),
    markdown=True,
    output_schema=Transcription,
    parser_model=OpenAIChat(
        id="gpt-5-mini"
    ),  # We use a parser model here as gpt-4o-audio-preview cannot return structured output
)
agent.print_response(
    "What is in this audio?", audio=[Audio(content=wav_data, format="wav")]
)
