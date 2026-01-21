import asyncio
from typing import List, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.models.gemini import GeminiTools
from agno.tools.openai import OpenAITools
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.steps import Steps
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow
from pydantic import BaseModel


# Define the structured message data
class MediaRequest(BaseModel):
    topic: str
    content_type: str  # "image" or "video"
    prompt: str
    style: Optional[str] = "realistic"
    duration: Optional[int] = None  # For video, duration in seconds
    resolution: Optional[str] = "1024x1024"  # For image resolution


# Define specialized agents for different media types
image_generator = Agent(
    name="Image Generator",
    model=OpenAIChat(id="gpt-4o"),
    tools=[OpenAITools(image_model="gpt-image-1")],
    instructions="""You are an expert image generation specialist.
    When users request image creation, you should ACTUALLY GENERATE the image using your available image generation tools.

    Always use the generate_image tool to create the requested image based on the user's specifications.
    Include detailed, creative prompts that incorporate style, composition, lighting, and mood details.

    After generating the image, provide a brief description of what you created.""",
)

image_describer = Agent(
    name="Image Describer",
    model=OpenAIChat(id="gpt-4o"),
    instructions="""You are an expert image analyst and describer.
    When you receive an image (either as input or from a previous step), analyze and describe it in vivid detail, including:
    - Visual elements and composition
    - Colors, lighting, and mood
    - Artistic style and technique
    - Emotional impact and narrative

    If no image is provided, work with the image description or prompt from the previous step.
    Provide rich, engaging descriptions that capture the essence of the visual content.""",
)

video_generator = Agent(
    name="Video Generator",
    model=OpenAIChat(id="gpt-4o"),
    # Video Generation only works on VertexAI mode
    tools=[GeminiTools(vertexai=True)],
    instructions="""You are an expert video production specialist.
    Create detailed video generation prompts and storyboards based on user requests.
    Include scene descriptions, camera movements, transitions, and timing.
    Consider pacing, visual storytelling, and technical aspects like resolution and duration.
    Format your response as a comprehensive video production plan.""",
)

video_describer = Agent(
    name="Video Describer",
    model=OpenAIChat(id="gpt-4o"),
    instructions="""You are an expert video analyst and critic.
    Analyze and describe videos comprehensively, including:
    - Scene composition and cinematography
    - Narrative flow and pacing
    - Visual effects and production quality
    - Audio-visual harmony and mood
    - Technical execution and artistic merit
    Provide detailed, professional video analysis.""",
)

# Define steps for image pipeline
generate_image_step = Step(
    name="generate_image",
    agent=image_generator,
    description="Generate a detailed image creation prompt based on the user's request",
)

describe_image_step = Step(
    name="describe_image",
    agent=image_describer,
    description="Analyze and describe the generated image concept in vivid detail",
)

# Define steps for video pipeline
generate_video_step = Step(
    name="generate_video",
    agent=video_generator,
    description="Create a comprehensive video production plan and storyboard",
)

describe_video_step = Step(
    name="describe_video",
    agent=video_describer,
    description="Analyze and critique the video production plan with professional insights",
)

# Define the two distinct pipelines
image_sequence = Steps(
    name="image_generation",
    description="Complete image generation and analysis workflow",
    steps=[generate_image_step, describe_image_step],
)

video_sequence = Steps(
    name="video_generation",
    description="Complete video production and analysis workflow",
    steps=[generate_video_step, describe_video_step],
)


def media_sequence_selector(step_input: StepInput) -> List[Step]:
    """
    Simple pipeline selector based on keywords in the message.

    Args:
        step_input: StepInput containing message

    Returns:
        List of Steps to execute
    """

    # Check if message exists and is a string
    if not step_input.input or not isinstance(step_input.input, str):
        return [image_sequence]  # Default to image sequence

    # Convert message to lowercase for case-insensitive matching
    message_lower = step_input.input.lower()

    # Check for video keywords
    if "video" in message_lower:
        return [video_sequence]
    # Check for image keywords
    elif "image" in message_lower:
        return [image_sequence]
    else:
        # Default to image for any other case
        return [image_sequence]


# Usage examples
if __name__ == "__main__":
    # Create the media generation workflow
    media_workflow = Workflow(
        name="AI Media Generation Workflow",
        description="Generate and analyze images or videos using AI agents",
        steps=[
            Router(
                name="Media Type Router",
                description="Routes to appropriate media generation pipeline based on content type",
                selector=media_sequence_selector,
                choices=[image_sequence, video_sequence],
            )
        ],
    )

    print("=== Example 1: Image Generation (using message_data) ===")
    image_request = MediaRequest(
        topic="Create an image of magical forest for a movie scene",
        content_type="image",
        prompt="A mystical forest with glowing mushrooms",
        style="fantasy art",
        resolution="1920x1080",
    )

    asyncio.run(
        media_workflow.aprint_response(
            input="Create an image of magical forest for a movie scene",
            markdown=True,
        )
    )

    # print("\n=== Example 2: Video Generation (using message_data) ===")
    # video_request = MediaRequest(
    #     topic="Create a cinematic video city timelapse",
    #     content_type="video",
    #     prompt="A time-lapse of a city skyline from day to night",
    #     style="cinematic",
    #     duration=30,
    #     resolution="4K"
    # )

    # asyncio.run(media_workflow.aprint_response(
    #     input="Create a cinematic video city timelapse",
    #     markdown=True,
    # ))
