"""Use a self-hosted FunASR server as an OpenAI-compatible transcription backend.

Start the official FunASR example server first:

    cd examples/openai_api
    pip install funasr fastapi uvicorn python-multipart
    python server.py --model sensevoice --device cuda --port 8000

See https://github.com/modelscope/FunASR/tree/main/examples/openai_api for
CPU, Docker, security, and other model options. SenseVoice supports Chinese,
Cantonese, English, Japanese, and Korean, plus emotion and audio-event output.
The OpenAITools transcription method returns the transcript text.
"""

from pathlib import Path

from agno.agent import Agent
from agno.tools.openai import OpenAITools
from agno.utils.media import download_file

audio_url = "https://agno-public.s3.amazonaws.com/demo_data/sample_conversation.wav"
audio_path = Path("tmp/sample_conversation.wav")

agent = Agent(
    tools=[
        OpenAITools(
            base_url="http://localhost:8000/v1",
            transcription_model="sensevoice",
            enable_image_generation=False,
            enable_speech_generation=False,
        )
    ],
    markdown=True,
)

if __name__ == "__main__":
    download_file(audio_url, audio_path)
    agent.print_response(f"Transcribe the audio file at {audio_path}")
