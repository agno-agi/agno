from agno.agent import Agent, RunOutput
from agno.models.openai import OpenAIChat
from agno.tools.dalle import DalleTools

image_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[DalleTools()],
    description="You are an AI agent that can generate images using DALL-E.",
    instructions="When the user asks you to create an image, use the `create_image` tool to create the image.",
    markdown=True,
)

image_agent.print_response("Generate an image of a white siamese cat")

# Retrieve and display generated images using get_last_run_output
run_response = image_agent.get_last_run_output()
if run_response and isinstance(run_response, RunOutput) and run_response.images:
    for image_response in run_response.images:
        image_url = image_response.url
        print(image_url)
else:
    print("No images found in run response")
