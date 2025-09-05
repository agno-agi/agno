import time
import uuid
from os import getenv
from typing import Any, Dict, List, Literal, Optional, TypedDict

from agno.agent import Agent
from agno.media import VideoArtifact
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import log_info, logger

try:
    from lumaai import LumaAI  # type: ignore
except ImportError:
    raise ImportError("`lumaai` not installed. Please install using `pip install lumaai`")


# Define types for keyframe structure
class KeyframeImage(TypedDict):
    type: Literal["image"]
    url: str


Keyframes = Dict[str, KeyframeImage]


class LumaLabTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        wait_for_completion: bool = True,
        poll_interval: int = 3,
        max_wait_time: int = 300,  # 5 minutes
        enable_generate_video: bool = True,
        enable_image_to_video: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.wait_for_completion = wait_for_completion
        self.poll_interval = poll_interval
        self.max_wait_time = max_wait_time
        self.api_key = api_key or getenv("LUMAAI_API_KEY")

        if not self.api_key:
            logger.error("LUMAAI_API_KEY not set. Please set the LUMAAI_API_KEY environment variable.")

        self.client = LumaAI(auth_token=self.api_key)

        tools: List[Any] = []
        if all or enable_generate_video:
            tools.append(self.generate_video)
        if all or enable_image_to_video:
            tools.append(self.image_to_video)

        super().__init__(name="luma_lab", tools=tools, **kwargs)

    def image_to_video(
        self,
        agent: Agent,
        prompt: str,
        start_image_url: str,
        end_image_url: Optional[str] = None,
        loop: bool = False,
        aspect_ratio: Literal["1:1", "16:9", "9:16", "4:3", "3:4", "21:9", "9:21"] = "16:9",
    ) -> ToolResult:
        """Generate a video from one or two images with a prompt.

        Args:
            agent: The agent instance
            prompt: Text description of the desired video
            start_image_url: URL of the starting image
            end_image_url: Optional URL of the ending image
            loop: Whether the video should loop
            aspect_ratio: Aspect ratio of the output video

        Returns:
            ToolResult: A ToolResult containing the generated video or error message.
        """

        try:
            # Construct keyframes
            keyframes: Dict[str, Dict[str, str]] = {"frame0": {"type": "image", "url": start_image_url}}

            # Add end image if provided
            if end_image_url:
                keyframes["frame1"] = {"type": "image", "url": end_image_url}

            # Create generation with keyframes
            generation = self.client.generations.create(
                prompt=prompt,
                loop=loop,
                aspect_ratio=aspect_ratio,
                keyframes=keyframes,  # type: ignore
            )

            video_id = str(uuid.uuid4())

            if not self.wait_for_completion:
                return ToolResult(content="Async generation unsupported")

            # Poll for completion
            seconds_waited = 0
            while seconds_waited < self.max_wait_time:
                if not generation or not generation.id:
                    return ToolResult(content="Failed to get generation ID")

                generation = self.client.generations.get(generation.id)

                if generation.state == "completed" and generation.assets:
                    video_url = generation.assets.video
                    if video_url:
                        video_artifact = VideoArtifact(id=video_id, url=video_url, eta="completed")
                        return ToolResult(
                            content=f"Video generated successfully: {video_url}",
                            videos=[video_artifact],
                        )
                elif generation.state == "failed":
                    return ToolResult(content=f"Generation failed: {generation.failure_reason}")

                log_info(f"Generation in progress... State: {generation.state}")
                time.sleep(self.poll_interval)
                seconds_waited += self.poll_interval

            return ToolResult(content=f"Video generation timed out after {self.max_wait_time} seconds")

        except Exception as e:
            logger.error(f"Failed to generate video: {e}")
            return ToolResult(content=f"Error: {e}")

    def generate_video(
        self,
        agent: Agent,
        prompt: str,
        loop: bool = False,
        aspect_ratio: Literal["1:1", "16:9", "9:16", "4:3", "3:4", "21:9", "9:21"] = "16:9",
        keyframes: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> ToolResult:
        """Use this function to generate a video given a prompt."""

        try:
            generation_params: Dict[str, Any] = {
                "prompt": prompt,
                "loop": loop,
                "aspect_ratio": aspect_ratio,
            }

            if keyframes is not None:
                generation_params["keyframes"] = keyframes

            generation = self.client.generations.create(**generation_params)  # type: ignore

            video_id = str(uuid.uuid4())
            if not self.wait_for_completion:
                return ToolResult(content="Async generation unsupported")

            # Poll for completion
            seconds_waited = 0
            while seconds_waited < self.max_wait_time:
                if not generation or not generation.id:
                    return ToolResult(content="Failed to get generation ID")

                generation = self.client.generations.get(generation.id)

                if generation.state == "completed" and generation.assets:
                    video_url = generation.assets.video
                    if video_url:
                        video_artifact = VideoArtifact(id=video_id, url=video_url, state="completed")
                        return ToolResult(
                            content=f"Video generated successfully: {video_url}",
                            videos=[video_artifact],
                        )
                elif generation.state == "failed":
                    return ToolResult(content=f"Generation failed: {generation.failure_reason}")

                log_info(f"Generation in progress... State: {generation.state}")
                time.sleep(self.poll_interval)
                seconds_waited += self.poll_interval

            return ToolResult(content=f"Video generation timed out after {self.max_wait_time} seconds")

        except Exception as e:
            logger.error(f"Failed to generate video: {e}")
            return ToolResult(content=f"Error: {e}")
