from agno.agent import Agent
from agno.media import Image
from agno.models.litellm import LiteLLM
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=LiteLLM(id="gpt-4o"),
    tools=[WebSearchTools()],
    markdown=True,
)

agent.print_response(
    "Tell me about this image and give me the latest news about it.",
    images=[
        Image(
            url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
        )
    ],
    stream=True,
)
