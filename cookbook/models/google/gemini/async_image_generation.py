import asyncio
import base64
from io import BytesIO

from agno.agent import Agent, RunOutput  # noqa
from agno.db.in_memory import InMemoryDb
from agno.models.google import Gemini
from PIL import Image

# No system message should be provided
agent = Agent(
    model=Gemini(
        id="gemini-2.0-flash-exp-image-generation",
        response_modalities=["Text", "Image"],
    ),
    db=InMemoryDb(),
)


async def generate_image():
    # Print the response in the terminal - using arun instead of run
    _ = await agent.arun("Make me an image of a cat in a tree.")

    # Retrieve and display generated images using get_last_run_output
    run_response = agent.get_last_run_output()
    if run_response and isinstance(run_response, RunOutput) and run_response.images:
        for image_response in run_response.images:
            image_bytes = image_response.content
            if image_bytes:
                if isinstance(image_bytes, bytes):
                    image_bytes = base64.b64decode(image_bytes)

                image = Image.open(BytesIO(image_bytes))
                image.show()
                # Save the image to a file
                # image.save("generated_image.png")
    else:
        print("No images found in run response")


if __name__ == "__main__":
    asyncio.run(generate_image())
