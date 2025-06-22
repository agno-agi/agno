import asyncio
from io import BytesIO

from agno.agent import Agent, RunResponse  # noqa
from agno.models.google import Gemini
from PIL import Image

# No system message should be provided
agent = Agent(
    model=Gemini(
        id="gemini-2.0-flash-exp-image-generation",
        response_modalities=["Text", "Image"],
    )
)


async def generate_image():
    response_stream = await agent.arun(
        "Make me an image of a cat in a tree.", stream=True
    )
    async for chunk in response_stream:
        if chunk.images:
            images = chunk.images
            if images and isinstance(images, list):
                for image_response in images:
                    image_bytes = image_response.content
                    image = Image.open(BytesIO(image_bytes))
                    image.show()
                    # image.save("generated_image.png")


if __name__ == "__main__":
    asyncio.run(generate_image())
