from agno.agent import Agent
from agno.media import Image
from agno.models.groq import Groq

agent = Agent(model=Groq(id="meta-llama/llama-4-scout-17b-16e-instruct"))

agent.print_response(
    "Tell me about this image",
    images=[
        Image(url="https://upload.wikimedia.org/wikipedia/commons/f/f2/LPU-v1-die.jpg"),
    ],
    stream=True,
)
