"""
FunASR Tools: transcribe audio files locally with FunASR (SenseVoice / Paraformer / Fun-ASR-Nano).

Requirements:
    pip install funasr

- Multilingual ASR (Chinese, Cantonese, English, Japanese, Korean and more), runs locally, no API key.
- SenseVoice (default) auto-detects the spoken language; built-in FSMN-VAD handles long audio.

Usage:
- Place your audio files in the base directory (e.g. `storage/audio`), then ask the agent to transcribe.
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.funasr import FunASRTools

audio_dir = Path(__file__).parent.joinpath("storage/audio")

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[FunASRTools(base_dir=audio_dir)],
    instructions=[
        "You transcribe audio files locally using FunASR.",
        "First list the available audio files, then transcribe the one the user asks for.",
    ],
    markdown=True,
)

agent.print_response("List the audio files, then transcribe the first one.", stream=True)
