"""
MLX Transcribe: A tool for transcribing audio files using MLX Whisper

Requirements:
1. ffmpeg - Install using:
   - macOS: `brew install ffmpeg`
   - Ubuntu: `sudo apt-get install ffmpeg`
   - Windows: Download from https://ffmpeg.org/download.html

2. mlx-whisper library:
   pip install mlx-whisper

Example Usage:
- Place your audio files in the 'storage/audio' directory
    Eg: download https://www.ted.com/talks/reid_hoffman_and_kevin_scott_the_evolution_of_ai_and_how_it_will_impact_human_creativity
- Run this script to transcribe audio files
- Supports various audio formats (mp3, mp4, wav, etc.)
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mlx_transcribe import MLXTranscribeTools

# Get audio files from storage/audio directory
agno_root_dir = Path(__file__).parent.parent.parent.resolve()
audio_storage_dir = agno_root_dir.joinpath("storage/audio")
if not audio_storage_dir.exists():
    audio_storage_dir.mkdir(exist_ok=True, parents=True)

agent = Agent(
    name="Transcription Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[MLXTranscribeTools(base_dir=audio_storage_dir)],
    instructions=[
        "To transcribe an audio file, use the `transcribe` tool with the name of the audio file as the argument.",
        "You can find all available audio files using the `read_files` tool.",
    ],
    markdown=True,
)

agent.print_response(
    "Summarize the reid hoffman ted talk, split into sections", stream=True
)
