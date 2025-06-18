from typing import Any, Dict, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.tools.models.gemini import GeminiTools
from agno.tools.openai import OpenAITools
from agno.workflow.v2.pipeline import Pipeline
from agno.workflow.v2.task import Task
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
    When you receive an image (either as input or from a previous task), analyze and describe it in vivid detail, including:
    - Visual elements and composition
    - Colors, lighting, and mood
    - Artistic style and technique
    - Emotional impact and narrative
    
    If no image is provided, work with the image description or prompt from the previous task.
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

# Define tasks for image pipeline
generate_image_task = Task(
    name="generate_image",
    agent=image_generator,
    description="Generate a detailed image creation prompt based on the user's request",
)

describe_image_task = Task(
    name="describe_image",
    agent=image_describer,
    description="Analyze and describe the generated image concept in vivid detail",
)

# Define tasks for video pipeline
generate_video_task = Task(
    name="generate_video",
    agent=video_generator,
    description="Create a comprehensive video production plan and storyboard",
)

describe_video_task = Task(
    name="describe_video",
    agent=video_describer,
    description="Analyze and critique the video production plan with professional insights",
)

# Define the two distinct pipelines
image_pipeline = Pipeline(
    name="image_generation",
    description="Complete image generation and analysis workflow",
    tasks=[generate_image_task, describe_image_task],
)

video_pipeline = Pipeline(
    name="video_generation",
    description="Complete video production and analysis workflow",
    tasks=[generate_video_task, describe_video_task],
)


def media_pipeline_selector(
    message: str, message_data: Optional[Dict[str, Any]] = None, **kwargs
) -> str:
    """
    Smart pipeline selector based on message_data fields.

    Args:
        message: The input message
        message_data: Structured data containing content_type and other parameters
        **kwargs: Additional context (user_id, session_id, etc.)

    Returns:
        Pipeline name to execute
    """
    # Default to image if no structured data provided
    if not message_data:
        return "image_generation"

    # Select pipeline based on content type
    if message_data.content_type.lower() == "video":
        return "video_generation"
    elif message_data.content_type.lower() == "image":
        return "image_generation"
    else:
        # Default to image for unknown types
        return "image_generation"


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
        pipelines=[image_pipeline, video_pipeline],
    )

    print("=== Example 1: Image Generation (using message_data) ===")
    try:
        image_request = MediaRequest(
            content_type="image",
            prompt="A mystical forest with glowing mushrooms",
            style="fantasy art",
            resolution="1920x1080",
        )

        media_workflow.print_response(
            message="Create a magical forest scene",
            message_data=image_request,
            selector=media_pipeline_selector,  # Alternatively supply just the pipeline name string
            markdown=True,
        )
    except Exception as e:
        print(f"Image generation failed: {e}")

    print("\n" + "=" * 60 + "\n")

    # print("=== Example 2: Video Generation (using message_data) ===")
    # try:
    #     video_request = MediaRequest(
    #         content_type="video",
    #         prompt="A time-lapse of a city skyline from day to night",
    #         style="cinematic",
    #         duration=30,
    #         resolution="4K"
    #     )

    #     media_workflow.print_response(
    #         message="Create a cinematic video city timelapse",
    #         message_data=video_request,
    #         selector=media_pipeline_selector,
    #         markdown=True,
    #     )
    # except Exception as e:
    #     print(f"Video generation failed: {e}")

    # print("\n" + "="*60 + "\n")
