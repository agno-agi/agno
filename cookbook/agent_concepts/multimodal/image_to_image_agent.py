from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.fal import FalTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    id="image-to-image",
    name="Image to Image Agent",
    tools=[FalTools()],
    markdown=True,
    instructions=[
        "You have to use the `image_to_image` tool to generate the image.",
        "You are an AI agent that can generate images using the Fal AI API.",
        "You will be given a prompt and an image URL.",
        "You have to return the image URL as provided, don't convert it to markdown or anything else.",
    ],
)

agent.print_response(
    "a cat dressed as a wizard with a background of a mystic forest. Make it look like 'https://fal.media/files/koala/Chls9L2ZnvuipUTEwlnJC.png'",
    stream=True,
)
