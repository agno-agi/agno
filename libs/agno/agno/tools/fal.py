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
        **kwargs,
    ):
        super().__init__(name="fal", **kwargs)

        self.api_key = api_key or getenv("FAL_KEY")
        if not self.api_key:
            logger.error("FAL_KEY not set. Please set the FAL_KEY environment variable.")
        self.model = model
        self.seen_logs: set[str] = set()
        self.register(self.generate_media)

    def on_queue_update(self, update):
        if isinstance(update, fal_client.InProgress) and update.logs:
            for log in update.logs:
                message = log["message"]
                if message not in self.seen_logs:
                    log_info(message)
                    self.seen_logs.add(message)

    def generate_media(self, agent: Union[Agent, Team], prompt: str) -> str:
        """
        Use this function to run a model with a given prompt.

        Args:
            prompt (str): A text description of the task.
        Returns:
            str: Return the result of the model.
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
                agent.add_image(
                    ImageArtifact(
                        id=media_id,
                        url=url,
                    )
                )
                media_type = "image"
            elif "video" in result:
                url = result.get("video", {}).get("url", "")
                agent.add_video(
                    VideoArtifact(
                        id=media_id,
                        url=url,
                    )
                )
                media_type = "video"
            else:
                logger.error(f"Unsupported type in result: {result}")
                return f"Unsupported type in result: {result}"

            return f"{media_type.capitalize()} generated successfully at {url}"
        except Exception as e:
            logger.error(f"Failed to run model: {e}")
            return f"Error: {e}"

    def image_to_image(self, agent: Union[Agent, Team], prompt: str, image_url: Optional[str] = None) -> str:
        """
        Use this function to transform an input image based on a text prompt using the Fal AI image-to-image model.
        The model takes an existing image and generates a new version modified according to your prompt.
        See https://fal.ai/models/fal-ai/flux/dev/image-to-image/api for more details about the image-to-image capabilities.

        Args:
            prompt (str): A text description of the task.
            image_url (str): The URL of the image to use for the generation.

        Returns:
            str: Return the result of the model.
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
            agent.add_image(
                ImageArtifact(
                    id=media_id,
                    url=url,
                )
            )

            return f"Image generated successfully at {url}"

        except Exception as e:
            logger.error(f"Failed to generate image: {e}")
            return f"Error: {e}"
