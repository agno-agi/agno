from agno.agent import Agent
from agno.media import Image
from agno.models.dashscope import DashScope
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=DashScope(id="qwen-vl-plus"),
    tools=[WebSearchTools()],
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
