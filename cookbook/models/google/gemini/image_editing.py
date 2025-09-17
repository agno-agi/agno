from io import BytesIO

from agno.agent import Agent, RunOutput  # noqa
from agno.media import Image
from agno.models.google import Gemini
from PIL import Image as PILImage

# No system message should be provided (Gemini requires only the image)
agent = Agent(
    model=Gemini(
        id="gemini-2.0-flash-exp-image-generation",
        response_modalities=["Text", "Image"],
    )
)

# Print the response in the terminal
response = agent.run(
    "Can you add a Llama in the background of this image?",
    images=[Image(filepath="tmp/test_photo.png")],
)

# Retrieve and display generated images using get_last_run_output
run_response = agent.get_last_run_output()
if run_response and isinstance(run_response, RunOutput) and run_response.images:
    for image_response in run_response.images:
        image_bytes = image_response.content
        if image_bytes:
            image = PILImage.open(BytesIO(image_bytes))
            image.show()
            # Save the image to a file
            # image.save("generated_image.png")
else:
    print("No images found in run response")
