from agno.agent import Agent
from agno.media import Image
from agno.models.aws import Claude
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Claude(id="global.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

agent.print_response(
    "Tell me about this image and search the web for more information.",
    images=[
        Image(
            url="https://fastly.picsum.photos/id/237/200/300.jpg?hmac=TmmQSbShHz9CdQm0NkEjx1Dyh_Y984R9LpNrpvH2D_U"
        ),
    ],
    stream=True,
)
