from agno.agent import Agent
from agno.media import Image
from agno.models.zai import ZAI
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=ZAI(id="glm-4.6v"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

agent.print_response(
    "Analyze this image in detail and tell me what you see. Also search for more information about the subject.",
    images=[
        Image(
            url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
        )
    ],
    stream=True,
)
