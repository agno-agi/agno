"""
This example demonstrates how to use the OpenAITools to transcribe an audio file.
"""

import base64
from pathlib import Path

from agno.agent import Agent
from agno.run.agent import RunOutput
from agno.tools.openai import OpenAITools
from agno.utils.media import download_file, save_base64_data

# Example 1: Transcription
url = "https://agno-public.s3.amazonaws.com/demo_data/sample_conversation.wav"

local_audio_path = Path("tmp/sample_conversation.wav")
print(f"Downloading file to local path: {local_audio_path}")
download_file(url, local_audio_path)

transcription_agent = Agent(
    tools=[OpenAITools(transcription_model="gpt-4o-transcribe")],
    markdown=True,
)
transcription_agent.print_response(
    f"Transcribe the audio file for this file: {local_audio_path}"
)

# Example 2: Image Generation
agent = Agent(
    tools=[OpenAITools(image_model="gpt-image-1")],
    markdown=True,
)

response = agent.run(
    "Generate an image of a sports car and tell me its color.", debug_mode=True
)

if isinstance(response, RunOutput):
    print("Agent response:", response.content)
    if response.images:
        image_base64 = base64.b64encode(response.images[0].content).decode("utf-8")
        save_base64_data(image_base64, "tmp/sports_car.png")
