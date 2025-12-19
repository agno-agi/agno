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
# url = "https://openaiassets.blob.core.windows.net/$web/API/docs/audio/alloy.wav"
url = "https://agno-public.s3.us-east-1.amazonaws.com/demo_data/sample_audio.wav"

response = httpx.get(url)
response.raise_for_status()
wav_data = response.content

# Provide the agent with the audio file and get result as text
agent = Agent(
    model=OpenAIChat(id="gpt-4o-audio-preview", modalities=["text"]),
    markdown=True,
    instructions="""Your task is to accurately transcribe the audio into text. You will be given an audio file and you need to transcribe it into text. 
        In the transcript, make sure to identify the speakers. If a name is mentioned, use the name in the transcript. If a name is not mentioned, use a placeholder like 'Speaker 1', 'Speaker 2', etc.
        Make sure to include all the content of the audio in the transcript.
        For any audio that is not speech, use the placeholder 'background noise' or 'silence' or 'music' or 'other'.
        Only return the transcript, no other text or formatting.
        """,
    # output_schema=Transcription,
    # parser_model=OpenAIChat(
    #     id="gpt-5-mini"
    # ),  # We use a parser model here as gpt-4o-audio-preview cannot return structured output
)
agent.print_response(
    "Give a transcript of the audio conversation",
    audio=[Audio(content=wav_data, format="wav")],
)
