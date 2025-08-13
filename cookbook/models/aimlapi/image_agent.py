from agno.agent import Agent
from agno.media import Image
from agno.models.aimlapi import AIMLApi

agent = Agent(
    model=AIMLApi(id="meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo"),
    markdown=True,
)

agent.print_response(
    "Tell me about this image",
    images=[
        Image(
            url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
        )
    ],
    stream=True,
)
