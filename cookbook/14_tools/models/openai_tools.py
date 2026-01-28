"""
This example demonstrates how to use the OpenAITools to transcribe an audio file.
"""

import base64
from pathlib import Path

from agno.agent import Agent
from agno.run.agent import RunOutput
from agno.tools.openai import OpenAITools
from agno.media import Image
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
generation_agent = Agent(
    tools=[OpenAITools(image_model="gpt-image-1")],
    markdown=True,
)

response = generation_agent.run(
    "Generate an image of a sports car and tell me its color.", debug_mode=True
)

if isinstance(response, RunOutput):
    print("Agent response:", response.content)
    if response.images:
        image_base64 = base64.b64encode(response.images[0].content).decode("utf-8")
        save_base64_data(image_base64, "tmp/sports_car.png")

# Example 3: Image Editing
# 1. Prepare image
image_url = "https://images.pexels.com/photos/34040355/pexels-photo-34040355.jpeg"

local_image_path = Path("tmp/sample_image.jpg")
print(f"Downloading file to local path: {local_image_path}")
download_file(image_url, local_image_path)

image_bytes = local_image_path.read_bytes()

# 2. Setup Agent & Tool
edit_tools = OpenAITools(
    enable_image_edit=True,
    image_model="gpt-image-1",
    image_bytes=image_bytes,
    image_mime_type="image/jpeg",
)

edit_agent = Agent(
    tools=[edit_tools],
    markdown=False,
    instructions="Follow the edit instructions and return the edited image.",
    description="You are an image editing assistant. You can edit the image based on the instructions.",
)

# 3. Run Edit
edit_response = edit_agent.run(
    "Adjust the image's brightness and contrast.",
    images=[Image(content=image_bytes)],
)

if isinstance(edit_response, RunOutput):
    print("Agent response:", edit_response.content)
    if edit_response.images:
        image_base64 = base64.b64encode(edit_response.images[0].content).decode("utf-8")
        save_base64_data(image_base64, "tmp/sample_image_edited.png")
        print("Edited image saved to tmp/sample_image_edited.png")
