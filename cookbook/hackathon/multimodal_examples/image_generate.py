from agno.agent import Agent, RunResponse
from agno.models.openai import OpenAIChat
from agno.tools.dalle import DalleTools
from agno.utils.log import logger
from rich.pretty import pprint

image_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[DalleTools()],
    instructions="Use the `create_image` tool to generate images.",
    show_tool_calls=True,
    markdown=True,
)

if __name__ == "__main__":
    run_response: RunResponse = image_agent.run(
        "Generate an image of a white siamese cat"
    )

    images = image_agent.get_images()
    if images and isinstance(images, list):
        for i, image_response in enumerate(images, 1):
            logger.info(f"Image {i}: {image_response.url}")
    else:
        logger.info("No images were generated.")

    print("---" * 20)
    pprint(run_response.images)
