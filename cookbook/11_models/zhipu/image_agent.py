from agno.agent import Agent
from agno.media import Image
from agno.models.zhipu import Zhipu
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Zhipu(id="glm-4.6v"),
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
