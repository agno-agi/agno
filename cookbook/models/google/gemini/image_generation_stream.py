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

# Print the response in the terminal
response = agent.run("Make me an image of a cat in a tree.", stream=True)

for chunk in response:
    if chunk.images:
        images = chunk.images
        if images and isinstance(images, list):
            for image_response in images:
                image_bytes = image_response.content
                image = Image.open(BytesIO(image_bytes))
                image.show()
                # Save the image to a file
                # image.save("generated_image.png")
