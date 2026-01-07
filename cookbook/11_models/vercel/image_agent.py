from agno.agent import Agent
from agno.media import Image
from agno.models.vercel import V0
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=V0(id="v0-1.0-md"),
    tools=[DuckDuckGoTools()],
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
