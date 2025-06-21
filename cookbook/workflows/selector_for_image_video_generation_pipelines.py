from typing import Any, Dict, List, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.tools.models.gemini import GeminiTools
from agno.tools.openai import OpenAITools
from agno.workflow.v2.condition import Condition
from agno.workflow.v2.step import Step
from agno.workflow.v2.steps import Steps
from agno.workflow.v2.types import StepInput
from agno.workflow.v2.workflow import Workflow
from pydantic import BaseModel


# Define the structured message data
class MediaRequest(BaseModel):
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


def media_sequence_selector(step_input: StepInput, steps: List[Steps], **kwargs) -> str:
    """
    Smart pipeline selector based on message_data fields.

    Args:
        message: The input message
        message_data: Structured data containing content_type and other parameters
        **kwargs: Additional context (user_id, session_id, etc.)

    Returns:
        Pipeline name to execute
    """
    image_sequence = steps[0]
    video_sequence = steps[1]

    # Default to image if no structured data provided
    if not step_input.message:
        return image_sequence

    # Select pipeline based on content type
    if step_input.message_data.content_type.lower() == "video":
        return video_sequence
    elif step_input.message_data.content_type.lower() == "image":
        return image_sequence
    else:
        # Default to image for unknown types
        return image_sequence


# Usage examples
if __name__ == "__main__":
    # Create the media generation workflow
    media_workflow = Workflow(
        name="AI Media Generation Workflow",
        description="Generate and analyze images or videos using AI agents",
        storage=SqliteStorage(
            table_name="media_workflows_v2",
            db_file="tmp/media_workflow_data_v2.db",
            mode="workflow_v2",
        ),
        steps=[
            Condition(
                evaluator=media_sequence_selector,
                steps=[image_sequence, video_sequence],
            )
        ],
    )

    print("=== Example 1: Image Generation (using message_data) ===")
    image_request = MediaRequest(
        content_type="image",
        prompt="A mystical forest with glowing mushrooms",
        style="fantasy art",
        resolution="1920x1080",
    )

    media_workflow.print_response(
        message="Create a magical forest scene",
        message_data=image_request,
        markdown=True,
    )

    # print("=== Example 2: Video Generation (using message_data) ===")
    # video_request = MediaRequest(
    #     content_type="video",
    #     prompt="A time-lapse of a city skyline from day to night",
    #     style="cinematic",
    #     duration=30,
    #     resolution="4K"
    # )

    # media_workflow.print_response(
    #     message="Create a cinematic video city timelapse",
    #     message_data=video_request,
    #     markdown=True,
    # )
