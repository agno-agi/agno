"""
pip install fal-client
"""

from os import getenv
from typing import Optional, Union
from uuid import uuid4

from agno.agent import Agent
from agno.media import ImageArtifact, VideoArtifact
from agno.team.team import Team
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import log_info, logger

try:
    import fal_client  # type: ignore
except ImportError:
    raise ImportError("`fal_client` not installed. Please install using `pip install fal-client`")


class FalTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "fal-ai/hunyuan-video",
        enable_generate_media: bool = True,
        enable_image_to_image: bool = False,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("FAL_API_KEY")
        if not self.api_key:
            logger.error("FAL_API_KEY not set. Please set the FAL_API_KEY environment variable.")
        self.model = model
        self.seen_logs: set[str] = set()

        tools = []
        if all or enable_generate_media:
            tools.append(self.generate_media)
        if all or enable_image_to_image:
            tools.append(self.image_to_image)

        super().__init__(name="fal-tools", tools=tools, **kwargs)

    def on_queue_update(self, update):
        if isinstance(update, fal_client.InProgress) and update.logs:
            for log in update.logs:
                message = log["message"]
                if message not in self.seen_logs:
                    log_info(message)
                    self.seen_logs.add(message)

    def generate_media(self, agent: Union[Agent, Team], prompt: str) -> ToolResult:
        """
        Use this function to run a model with a given prompt.

        Args:
            prompt (str): A text description of the task.
        Returns:
            ToolResult: Contains the generated media and success message.
        """
        try:
            result = fal_client.subscribe(
                self.model,
                arguments={"prompt": prompt},
                with_logs=True,
                on_queue_update=self.on_queue_update,
            )

            media_id = str(uuid4())

            if "image" in result:
                url = result.get("image", {}).get("url", "")
                image_artifact = ImageArtifact(
                    id=media_id,
                    url=url,
                )
                return ToolResult(content=f"Image generated successfully at {url}", images=[image_artifact])
            elif "video" in result:
                url = result.get("video", {}).get("url", "")
                video_artifact = VideoArtifact(
                    id=media_id,
                    url=url,
                )
                return ToolResult(content=f"Video generated successfully at {url}", videos=[video_artifact])
            else:
                logger.error(f"Unsupported type in result: {result}")
                return ToolResult(content=f"Unsupported type in result: {result}")

        except Exception as e:
            logger.error(f"Failed to run model: {e}")
            return ToolResult(content=f"Error: {e}")

    def image_to_image(self, agent: Union[Agent, Team], prompt: str, image_url: Optional[str] = None) -> ToolResult:
        """
        Use this function to transform an input image based on a text prompt using the Fal AI image-to-image model.
        The model takes an existing image and generates a new version modified according to your prompt.
        See https://fal.ai/models/fal-ai/flux/dev/image-to-image/api for more details about the image-to-image capabilities.

        Args:
            prompt (str): A text description of the task.
            image_url (str): The URL of the image to use for the generation.

        Returns:
            ToolResult: Contains the generated image and success message.
        """

        try:
            result = fal_client.subscribe(
                "fal-ai/flux/dev/image-to-image",
                arguments={"image_url": image_url, "prompt": prompt},
                with_logs=True,
                on_queue_update=self.on_queue_update,
            )
            url = result.get("images", [{}])[0].get("url", "")
            media_id = str(uuid4())
            image_artifact = ImageArtifact(
                id=media_id,
                url=url,
            )

            return ToolResult(content=f"Image generated successfully at {url}", images=[image_artifact])

        except Exception as e:
            logger.error(f"Failed to generate image: {e}")
            return ToolResult(content=f"Error: {e}")
