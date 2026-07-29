import time
import uuid
from os import getenv
from typing import Callable, Dict, List, Literal, Optional, TypedDict, Union

from agno.agent import Agent
from agno.media import Video
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import log_error, log_info, logger

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
        model: Literal["ray-2", "ray-flash-2"] = "ray-2",
        duration: Optional[Literal["5s", "9s"]] = None,
        resolution: Optional[Union[Literal["540p", "720p", "1080p", "4k"], str]] = None,
        wait_for_completion: bool = True,
        poll_interval: int = 3,
        max_wait_time: int = 300,
        generate_video: bool = True,
        image_to_video: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize LumaLab video generation toolkit.

        Args:
            api_key: LumaAI API key. Defaults to LUMAAI_API_KEY env var.
            model: Model to use for generation.
            duration: Default video duration. None lets API decide.
            resolution: Default video resolution. None lets API decide.
            wait_for_completion: Whether to wait for video generation to complete.
            poll_interval: Seconds between status checks.
            max_wait_time: Maximum seconds to wait for completion.
            generate_video: Enable the generate_video tool.
            image_to_video: Enable the image_to_video tool.
            all: Enable all tools.
        """
        self.model: Literal["ray-2", "ray-flash-2"] = model
        self.duration = duration
        self.resolution = resolution
        self.wait_for_completion = wait_for_completion
        self.poll_interval = poll_interval
        self.max_wait_time = max_wait_time
        self.api_key = api_key or getenv("LUMAAI_API_KEY")

        if not self.api_key:
            log_error("LUMAAI_API_KEY not set. Please set the LUMAAI_API_KEY environment variable.")

        self.client = LumaAI(auth_token=self.api_key)

        tools: List[Callable] = []
        if all or generate_video:
            tools.append(self.generate_video)
        if all or image_to_video:
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
        duration: Optional[Literal["5s", "9s"]] = None,
        resolution: Optional[str] = None,
    ) -> ToolResult:
        """Generate a video from one or two images with a prompt.

        Args:
            agent: The agent instance.
            prompt: Text description of the desired video.
            start_image_url: URL of the starting image.
            end_image_url: Optional URL of the ending image for transitions.
            loop: Whether the video should loop seamlessly.
            aspect_ratio: Output video aspect ratio.
            duration: Video duration (5s or 9s). Uses toolkit default if not specified.
            resolution: Video resolution (540p, 720p, 1080p, 4k). Uses toolkit default if not specified.

        Returns:
            ToolResult with generated video or error message.
        """
        try:
            keyframes: Dict[str, Dict[str, str]] = {"frame0": {"type": "image", "url": start_image_url}}

            if end_image_url:
                keyframes["frame1"] = {"type": "image", "url": end_image_url}

            params: Dict[str, object] = {
                "model": self.model,
                "prompt": prompt,
                "loop": loop,
                "aspect_ratio": aspect_ratio,
                "keyframes": keyframes,
            }
            actual_duration = duration or self.duration
            actual_resolution = resolution or self.resolution
            if actual_duration:
                params["duration"] = actual_duration
            if actual_resolution:
                params["resolution"] = actual_resolution

            generation = self.client.generations.create(**params)  # type: ignore

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
                        video_artifact = Video(id=video_id, url=video_url, eta="completed")
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
            logger.exception("Failed to generate video")
            return ToolResult(content=f"Error: {e}")

    def generate_video(
        self,
        agent: Agent,
        prompt: str,
        loop: bool = False,
        aspect_ratio: Literal["1:1", "16:9", "9:16", "4:3", "3:4", "21:9", "9:21"] = "16:9",
        duration: Optional[Literal["5s", "9s"]] = None,
        resolution: Optional[str] = None,
        keyframes: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> ToolResult:
        """Generate a video from a text prompt.

        Args:
            agent: The agent instance.
            prompt: Text description of the desired video.
            loop: Whether the video should loop seamlessly.
            aspect_ratio: Output video aspect ratio.
            duration: Video duration (5s or 9s). None lets API decide.
            resolution: Video resolution (540p, 720p, 1080p, 4k). None lets API decide.
            keyframes: Optional keyframe images for guided generation.

        Returns:
            ToolResult with generated video or error message.
        """
        try:
            generation_params: Dict[str, object] = {
                "model": self.model,
                "prompt": prompt,
                "loop": loop,
                "aspect_ratio": aspect_ratio,
            }
            actual_duration = duration or self.duration
            actual_resolution = resolution or self.resolution
            if actual_duration:
                generation_params["duration"] = actual_duration
            if actual_resolution:
                generation_params["resolution"] = actual_resolution
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
                        video_artifact = Video(id=video_id, url=video_url, state="completed")
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
            logger.exception("Failed to generate video")
            return ToolResult(content=f"Error: {e}")
