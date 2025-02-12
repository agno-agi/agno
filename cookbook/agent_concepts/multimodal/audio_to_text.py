import requests
from agno.agent import Agent
from agno.media import Audio
from agno.models.google import Gemini

agent = Agent(
    model=Gemini(id="gemini-2.0-flash-exp"),
    markdown=True,
)

url = "https://res.cloudinary.com/djs9vdcla/video/upload/v1739365268/QA-01_gfhi37.mp3"

response = requests.get(url)
audio_content = response.content

# Give a transcript of this audio conversation. Use speaker A, speaker B to identify speakers.

agent.print_response(
    "Give a transcript of this audio conversation. Use speaker A, speaker B to identify speakers.",
    audio=[Audio(content=audio_content)],
    stream=True,
)
