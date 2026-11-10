from io import BytesIO

from agno.agent import Agent, RunOutput  # noqa
from agno.models.openrouter import OpenRouter
from PIL import Image

# Request both image and text modalities so OpenRouter returns generated images
agent = Agent(
    model=OpenRouter(
        id="google/gemini-2.5-flash-image",
        modalities=["image", "text"],
    )
)

run_response = agent.run("Make me an image of a cat in a tree.")

if run_response and isinstance(run_response, RunOutput) and run_response.images:
    for image_response in run_response.images:
        image_bytes = image_response.content
        if image_bytes:
            image = Image.open(BytesIO(image_bytes))
            image.show()
            # Save the image to a file
            # image.save("generated_image.png")
else:
    print("No images found in run response")
