from agno.agent import Agent
from agno.media import Image
from agno.models.aws import Claude
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Claude(id="anthropic.claude-3-5-sonnet-20240620-v1:0"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

agent.print_response(
    "Tell me about this image and search the web for more information.",
    images=[
        Image(
            url="https://upload.wikimedia.org/wikipedia/commons/a/a7/Camponotus_flavomarginatus_ant.jpg"
        ),
    ],
    stream=True,
)
