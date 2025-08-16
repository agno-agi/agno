from agno.agent import Agent
from agno.media import Image
from agno.models.mistral.mistral import MistralChat

agent = Agent(
    model=MistralChat(id="pixtral-12b-2409"),
    markdown=True,
)

agent.print_response(
    "what are the differences between two images?",
    images=[
        Image(
            url="https://tripfixers.com/wp-content/uploads/2019/11/eiffel-tower-with-snow.jpeg"
        ),
        Image(
            url="https://assets.visitorscoverage.com/production/wp-content/uploads/2024/04/AdobeStock_626542468-min-1024x683.jpeg"
        ),
    ],
    stream=True,
)
