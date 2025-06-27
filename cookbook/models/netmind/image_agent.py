from agno.agent import Agent
from agno.media import Image
from agno.models.netmind import NetMind

agent = Agent(
    model=NetMind(id="google/gemma-3-27b-it"),
    markdown=True,
)

agent.print_response(
    "Tell me about this image",
    images=[
        Image(
            url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
        )
    ],
    stream=False,
)
