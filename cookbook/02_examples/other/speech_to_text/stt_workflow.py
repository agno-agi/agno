"""
This cookbook demonstrates how to use an Agno Workflow with AgentOS to transcribe audio files. There are four steps in the workflow:
1. Echo the input file
2. Get the audio content
3. Transcribe the audio content
4. Convert the transcription to structured output
"""

import io
from textwrap import dedent
from typing import Optional

import httpx
import requests
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.media import Audio
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.utils.log import log_error, log_info
from agno.workflow import Step, Workflow
from agno.workflow.types import StepInput, StepOutput
from pydantic import BaseModel, Field
from pydub import AudioSegment

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(
    db_url=db_url,
    db_schema="ai",
    session_table="invoice_processing_sessions",
)


class Transcription(BaseModel):
    transcript: list[str] = Field(
        ...,
        description="The transcript of the audio conversation. Formatted as a list of strings with speaker labels and logical paragraphs and newlines.",
    )
    description: str = Field(..., description="A description of the audio conversation")
    speakers: list[str] = Field(
        ..., description="The speakers in the audio conversation"
    )


def get_transcription_agent(additional_instructions: Optional[str] = None):
    transcription_agent = Agent(
        model=Gemini(id="gemini-3-flash-preview"),
        markdown=True,
        description="Audio file transcription agent",
        instructions=dedent(f"""Your task is to accurately transcribe the audio into text. You will be given an audio file and you need to transcribe it into text. 
            In the transcript, make sure to identify the speakers. If a name is mentioned, use the name in the transcript. If a name is not mentioned, use a placeholder like 'Speaker 1', 'Speaker 2', etc.
            Make sure to include all the content of the audio in the transcript.
            For any audio that is not speech, use the placeholder 'background noise' or 'silence' or 'music' or 'other'.
            Only return the transcript, no other text or formatting.
            {additional_instructions if additional_instructions else ""}"""),
    )
    return transcription_agent


class TranscriptionRequest(BaseModel):
    audio_file: str = (
        "https://agno-public.s3.us-east-1.amazonaws.com/demo_data/sample_audio.wav"
    )
    model_id: str = "gpt-audio-2025-08-28"
    additional_instructions: Optional[str] = None


def echo_input_file(step_input: StepInput) -> StepOutput:
    request = step_input.input
    log_info(f"Echoing input file: {request.audio_file}")
    return StepOutput(
        content={
            "file_link": request.audio_file,
            "model_id": request.model_id,
        },
        success=True,
    )


# TODO: Find a cleaner way to create wav files
def get_audio_content(step_input: StepInput, session_state) -> StepOutput:
    request = step_input.input
    url = request.audio_file
    if url.endswith(".wav"):
        response = httpx.get(url)
        response.raise_for_status()
        wav_data = response.content
        session_state["audio_content"] = wav_data
        return StepOutput(
            success=True,
        )
    elif url.endswith(".mp3"):
        response = requests.get(url)
        response.raise_for_status()
        mp3_audio = io.BytesIO(response.content)
        audio_segment = AudioSegment.from_file(mp3_audio, format="mp3")
        # Ensure mono and standard sample rate for OpenAI compatibility
        if audio_segment.channels > 1:
            audio_segment = audio_segment.set_channels(1)
        if audio_segment.frame_rate != 16000:
            audio_segment = audio_segment.set_frame_rate(16000)
        wav_io = io.BytesIO()
        audio_segment.export(wav_io, format="wav")
        wav_io.seek(0)  # Reset to beginning before reading
        audio_content = wav_io.read()
        session_state["audio_content"] = audio_content
        return StepOutput(success=True)
    else:
        log_error(f"Unsupported file type: {url}")
        return StepOutput(success=False)


async def transcription_agent_executor(
    step_input: StepInput, session_state
) -> StepOutput:
    audio_content = session_state["audio_content"]
    transcription_agent = get_transcription_agent(
        additional_instructions=step_input.input.additional_instructions
    )
    response = await transcription_agent.arun(
        input="Give a transcript of the audio conversation",
        audio=[Audio(content=audio_content, format="wav")],
    )
    print(response.content)
    session_state["transcription"] = response.content
    return StepOutput(
        success=True,
    )


async def convert_transcription_to_output(
    step_input: StepInput, session_state
) -> StepOutput:
    transcription = session_state["transcription"]
    agent = Agent(
        model=OpenAIChat(id="gpt-5-mini"),
        instructions="""You are a helpful assistant that converts a transcription of an audio conversation into a structured output.""",
        output_schema=Transcription,
    )

    response = await agent.arun(input=transcription)

    return StepOutput(content=response.content, success=True)


# Define workflow steps
echo_input_step = Step(name="Echo Input", executor=echo_input_file)
get_audio_content_step = Step(name="Get Audio Content", executor=get_audio_content)
transcription_step = Step(name="Transcription", executor=transcription_agent_executor)
conversion_step = Step(name="Conversion", executor=convert_transcription_to_output)

# Workflow definition
speech_to_text_workflow = Workflow(
    name="Speech to text workflow",
    description="""
        Transcribe audio file using transcription agent
        """,
    input_schema=TranscriptionRequest,
    steps=[
        echo_input_step,
        get_audio_content_step,
        transcription_step,
        conversion_step,
    ],
    db=db,
)


agent_os = AgentOS(
    workflows=[speech_to_text_workflow],
)

app = agent_os.get_app()
if __name__ == "__main__":
    # Serves a FastAPI app exposed by AgentOS. Use reload=True for local dev.
    agent_os.serve(app="stt_workflow:app", reload=True)
