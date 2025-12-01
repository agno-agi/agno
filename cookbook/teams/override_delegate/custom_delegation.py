"""
Example: Custom Member Delegation with Media Filtering

This example demonstrates how to use a custom `member_delegation_function` to
route media (images/videos) to the appropriate specialist agent.

Use case:
- Image Processor agent only receives images
- Video Processor agent only receives videos
- The custom delegation function filters media based on the target agent
"""

from typing import Iterator, Union

from agno.agent import Agent
from agno.media import Image, Video
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput, RunOutputEvent
from agno.run.team import TeamRunOutput, TeamRunOutputEvent
from agno.team.team import MemberDelegationContext, Team


def media_filtering_delegation(
    context: MemberDelegationContext,
) -> Iterator[Union[RunOutputEvent, TeamRunOutputEvent, RunOutput, TeamRunOutput, str]]:
    """
    Custom delegation function that filters media based on the target agent.

    - Image Processor only receives images (videos are filtered out)
    - Video Processor only receives videos (images are filtered out)
    """
    member_agent = context.member_agent
    agent_name = member_agent.name or member_agent.id or "Unknown"

    # Filter media based on agent type
    images_to_send = context.images
    videos_to_send = context.videos
    
    if "image" in agent_name.lower():
        # Image processor: only send images, filter out videos
        videos_to_send = None

    elif "video" in agent_name.lower():
        # Video processor: only send videos, filter out images
        images_to_send = None
        
    run_response = member_agent.run(
        input=context.input,
        user_id=context.user_id,
        session_id=context.session_id,
        images=images_to_send,
        videos=videos_to_send,
        stream=False,
    )
    
    content = run_response.content
    if isinstance(content, str) and content.strip():
        yield content
    else:
        yield f"No response from {agent_name}"

    yield run_response


# Create specialist agents using Gemini for multimodal support
image_processor = Agent(
    name="Image Processor",
    role="Image analysis specialist",
    model=Gemini(id="gemini-2.5-flash"),
    instructions=[
        "You are an image analysis specialist.",
        "Analyze images in detail and provide descriptions.",
        "Identify objects, people, locations, and notable features.",
    ],
)

video_processor = Agent(
    name="Video Processor",
    role="Video analysis specialist",
    model=Gemini(id="gemini-2.5-flash"),
    instructions=[
        "You are a video analysis specialist.",
        "Analyze videos and provide summaries of the content.",
        "Describe key scenes, actions, and audio elements.",
    ],
)

# Create team with custom media-filtering delegation
team = Team(
    name="Media Analysis Team",
    members=[image_processor, video_processor],
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "You are a team leader coordinating media analysis tasks.",
        "For image analysis, delegate to the Image Processor.",
        "For video analysis, delegate to the Video Processor.",
        "Combine the results into a comprehensive media report.",
    ],
    send_media_to_model=False,  # Prevent the main model from receiving the media
    member_delegation_function=media_filtering_delegation,
    markdown=True,
)

if __name__ == "__main__":
    team.print_response(
        "Analyze both the image and video provided. Give me a summary of each.",
        images=[
            Image(url="https://fal.media/files/koala/Chls9L2ZnvuipUTEwlnJC.png"),
        ],
        videos=[
            Video(url="https://www.youtube.com/watch?v=XinoY2LDdA0"),
        ],
    )
