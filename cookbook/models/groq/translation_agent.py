import base64
from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.models.groq import GroqTools
from agno.utils.media import save_base64_data

path = "tmp/sample-fr.mp3"

agent = Agent(
    name="Groq Translation Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[GroqTools()],
    cache_session=True,
)

response = agent.run(
    f"Let's transcribe the audio file located at '{path}' and translate it to English. After that generate a new music audio file using the translated text."
)

if response and response.audio:
    base64_audio = base64.b64encode(response.audio[0].content).decode("utf-8")
    save_base64_data(base64_audio, Path("tmp/sample-en.mp3"))  # type: ignore
