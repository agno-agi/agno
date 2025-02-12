import requests
from agno.agent import Agent
from agno.media import Audio
from agno.models.google import Gemini

agent = Agent(
  model=Gemini(id="gemini-2.0-flash-exp"),
  markdown=True,
)

url = "https://storage.googleapis.com/github-repo/generative-ai/gemini/use-cases/multimodal-sentiment-analysis/sample_conversation.wav"

response = requests.get(url)
audio_content = response.content

# Give a sentiment analysis of this audio conversation. Use speaker A, speaker B to identify speakers.

agent.print_response(
  "Give a sentiment analysis of this audio conversation. Use speaker A, speaker B to identify speakers.",
  audio=[Audio(content=audio_content)],
  stream=True,
)
