from agno.agent import Agent
from agno.media import Image
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    markdown=True,
)

agent.print_response(
    "What's in these images",
    images=[
        Image(
            url="https://upload.wikimedia.org/wikipedia/commons/thumb/d/dd/Gfp-wisconsin-madison-the-nature-boardwalk.jpg/2560px-Gfp-wisconsin-madison-the-nature-boardwalk.jpg",
            detail="high",
        )
    ],
)
