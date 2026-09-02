"""
pip install wavespeed
"""

from os import getenv
from typing import Any, List, Optional, Union
from uuid import uuid4

from agno.agent import Agent
from agno.media import Image, Video
from agno.team.team import Team
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import log_error, logger

try:
    from wavespeed import Client as WaveSpeedClient
except ImportError:
    raise ImportError("`wavespeed` not installed. Please install using `pip install wavespeed`")


class WaveSpeedTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        image_model: str = "bytedance/seedream-v5.0-pro",
        video_model: str = "bytedance/seedance-2.5/text-to-video",
        poll_interval: float = 1.0,
        timeout: float = 600.0,
        generate_image: bool = True,
        generate_video: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("WAVESPEED_API_KEY")
        if not self.api_key:
            log_error("WAVESPEED_API_KEY not set. Please set the WAVESPEED_API_KEY environment variable.")
        self.image_model = image_model
        self.video_model = video_model
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.client = WaveSpeedClient(api_key=self.api_key)

        tools: List[Any] = []
        if all or generate_image:
            tools.append(self.generate_image)
        if all or generate_video:
            tools.append(self.generate_video)

        super().__init__(name="wavespeed_tools", tools=tools, **kwargs)

    def _run_model(self, model: str, arguments: dict) -> List[str]:
        """Run a WaveSpeed model and wait for its output URLs."""
        result = self.client.run(
            model,
            arguments,
            timeout=self.timeout,
            poll_interval=self.poll_interval,
        )
        return result.get("outputs", []) or []

    def generate_image(self, agent: Union[Agent, Team], prompt: str, model: Optional[str] = None) -> ToolResult:
        """
        Use this function to generate an image from a text prompt using a WaveSpeed model.
        See https://wavespeed.ai/models for the full model catalog.

        Args:
            prompt (str): A text description of the image to generate.
            model (str): Optional WaveSpeed model id to use instead of the default image model.

        Returns:
            ToolResult: Contains the generated image(s) and success message.
        """
        try:
            outputs = self._run_model(model or self.image_model, {"prompt": prompt})
            if not outputs:
                return ToolResult(content="No output received from the model.")

            images = [Image(id=str(uuid4()), url=url) for url in outputs]
            urls_text = ", ".join(outputs)
            return ToolResult(content=f"Generated {len(images)} image(s) successfully: {urls_text}", images=images)
        except Exception as e:
            logger.exception("Failed to generate image")
            return ToolResult(content=f"Error: {e}")

    def generate_video(self, agent: Union[Agent, Team], prompt: str, model: Optional[str] = None) -> ToolResult:
        """
        Use this function to generate a video from a text prompt using a WaveSpeed model.
        See https://wavespeed.ai/models for the full model catalog.

        Args:
            prompt (str): A text description of the video to generate.
            model (str): Optional WaveSpeed model id to use instead of the default video model.

        Returns:
            ToolResult: Contains the generated video(s) and success message.
        """
        try:
            outputs = self._run_model(model or self.video_model, {"prompt": prompt})
            if not outputs:
                return ToolResult(content="No output received from the model.")

            videos = [Video(id=str(uuid4()), url=url) for url in outputs]
            urls_text = ", ".join(outputs)
            return ToolResult(content=f"Generated {len(videos)} video(s) successfully: {urls_text}", videos=videos)
        except Exception as e:
            logger.exception("Failed to generate video")
            return ToolResult(content=f"Error: {e}")
