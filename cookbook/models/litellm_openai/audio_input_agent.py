"""
Please first install litellm[proxy] by running: pip install 'litellm[proxy]'

Before running this script, you need to start the LiteLLM server:

litellm --model gpt-4o-audio-preview --host 127.0.0.1 --port 4000
"""

import requests
from agno.agent import Agent, RunResponse  # noqa
from agno.media import Audio
from agno.models.litellm import LiteLLMOpenAI

# Fetch the QA audio file and convert it to a base64 encoded string
url = "https://agno-public.s3.us-east-1.amazonaws.com/demo_data/QA-01.mp3"
response = requests.get(url)
response.raise_for_status()
mp3_data = response.content

# Provide the agent with the audio file and get result as text
# Note: Audio input requires specific audio-enabled models like gpt-4o-audio-preview
agent = Agent(
    model=LiteLLMOpenAI(id="gpt-4o-audio-preview"),
    markdown=True,
)
agent.print_response(
    "What is in this audio?", audio=[Audio(content=mp3_data, format="mp3")], stream=True
)
