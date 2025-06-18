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
)

agent.print_response(
    f"Let's transcribe the audio file located at '{path}' and translate it to English. After that generate a new music audio file using the translated text."
)

response = agent.run_response

if response.audio:
    save_base64_data(response.audio[0].base64_audio, Path("tmp/sample-en.mp3"))
