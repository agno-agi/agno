import io
from textwrap import dedent
from typing import Optional

import requests
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.media import Audio
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.utils.log import logger
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
    transcript: str = Field(..., description="The transcript of the audio conversation")
    description: str = Field(..., description="A description of the audio conversation")
    speakers: list[str] = Field(
        ..., description="The speakers in the audio conversation"
    )


def get_transcription_agent(additional_instructions: Optional[str] = None):
    transcription_agent = Agent(
        model=OpenAIChat(id="gpt-4o-audio-preview"),
        description="Audio file transcription agent",
        instructions=dedent(f"""You are an audio transcription agent. You are given an audio file and you need to transcribe it into text.
            You are an audio transcription agent. You are given an audio file and you need to transcribe it into text.
            Give a transcript of the audio conversation. Use speaker A, speaker B,  speaker C etc. to identify speakers.
            {additional_instructions}"""),
    )
    return transcription_agent


class TranscriptionRequest(BaseModel):
    audio_file: str = (
        "https://agno-public.s3.us-east-1.amazonaws.com/demo_data/QA-01.mp3"
    )
    model_id: str = "gpt-4o-audio-preview"
    additional_instructions: Optional[str] = None


def echo_input_file(step_input: StepInput) -> StepOutput:
    request = step_input.input
    logger.info(f"Echoing input file: {request.audio_file}")
    return StepOutput(
        content={
            "file_link": request.audio_file,
            "model_id": request.model_id,
        },
        success=True,
    )


# TODO: Find a cleaner way to create wav files. Probably need a step in the workflow to check file types first
def get_audio_content(step_input: StepInput, session_state) -> bytes:
    request = step_input.input
    url = request.audio_file
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
    return StepOutput(
        success=True,
    )


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
    return StepOutput(
        content=response.content,
        success=True,
    )


# Define workflow steps
echo_input_step = Step(name="Echo Input", executor=echo_input_file)
get_audio_content_step = Step(name="Get Audio Content", executor=get_audio_content)
transcription_step = Step(name="Transcription", executor=transcription_agent_executor)

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
    ],
    db=db,
)


agent_os = AgentOS(
    workflows=[speech_to_text_workflow],
)

app = agent_os.get_app()
if __name__ == "__main__":
    # Serves a FastAPI app exposed by AgentOS. Use reload=True for local dev.
    agent_os.serve(app="speech_to_text_workflow:app", reload=True)
