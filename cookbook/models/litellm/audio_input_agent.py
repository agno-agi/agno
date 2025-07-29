import requests
from agno.agent import Agent
from agno.media import Audio
from agno.models.litellm import LiteLLM

# Fetch the QA audio file and convert it to a base64 encoded string
url = "https://agno-public.s3.us-east-1.amazonaws.com/demo_data/QA-01.mp3"
response = requests.get(url)
response.raise_for_status()
mp3_data = response.content

# Audio input requires specific audio-enabled models like gpt-4o-audio-preview
agent = Agent(
    model=LiteLLM(id="gpt-4o-audio-preview"),
    markdown=True,
)
agent.print_response(
    "What's the audio about?",
    audio=[Audio(content=mp3_data, format="mp3")],
    stream=True,
)
