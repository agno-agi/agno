# groq transcription agent

import asyncio
import os
from pathlib import Path

from agno.agent import Agent
from agno.models.groq import Groq
from agno.models.openai import OpenAIChat
from agno.tools.model_tools.groq import GroqTools
from agno.utils.media import save_audio

path = "christmas-fr.mp3"

agent = Agent(
    name="Groq Translation Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[GroqTools()],
)

agent.print_response(
    f"Please transcribe the audio file located at '{path}' and translate it to English and generate a new music audio file."
)

response = agent.run_response

if response.audio:
    save_audio(response.audio[0].base64_audio, Path("tmp/christmas-en.mp3"))
