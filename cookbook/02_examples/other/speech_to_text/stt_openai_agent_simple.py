import httpx
from agno.agent import Agent, RunOutput  # noqa
from agno.media import Audio
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, Field

# Fetch the audio file and convert it to a base64 encoded string
url = "https://openaiassets.blob.core.windows.net/$web/API/docs/audio/alloy.wav"
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
)
agent.print_response(
    "What is in this audio?", audio=[Audio(content=wav_data, format="wav")]
)
