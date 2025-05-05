"""
This example demonstrates how to use the OpenAITools to transcribe an audio file.
"""

from pathlib import Path

from agno.agent import Agent
from agno.tools.openai import OpenAITools
from agno.utils.media import download_file

url = "https://agno-public.s3.amazonaws.com/demo_data/sample_conversation.wav"


local_audio_path = Path("tmp/sample_conversation.wav")
print(f"Downloading file to local path: {local_audio_path}")
download_file(url, local_audio_path)

transcription_agent = Agent(
    tools=[OpenAITools(transcription_model="gpt-4o-transcribe")],
    show_tool_calls=True,
    markdown=True,
)
transcription_agent.print_response(
    f"Transcribe the audio file for this file: {local_audio_path}"
)
