import asyncio
from io import BytesIO

from agno.agent import Agent, RunResponse  # noqa
from agno.media import Image
from agno.models.google import Gemini
from PIL import Image as PILImage

# No system message should be provided
agent = Agent(
    model=Gemini(
        id="gemini-2.0-flash-exp-image-generation",
        response_modalities=["Text", "Image"],
    )
)


async def modify_image():
    # Print the response in the terminal - using arun instead of run
    response = await agent.arun(
        "Can you add a Llama in the background of this image?",
        images=[Image(filepath="generated_image.png")],
    )

    images = agent.get_images()
    if images and isinstance(images, list):
        for image_response in images:
            image_bytes = image_response.content
            image = PILImage.open(BytesIO(image_bytes))
            image.show()
            # Save the image to a file
            # image.save("generated_image.png")


if __name__ == "__main__":
    asyncio.run(modify_image())
