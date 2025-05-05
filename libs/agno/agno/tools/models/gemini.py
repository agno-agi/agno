import base64
import time
from os import getenv
from typing import Any, Optional
from uuid import uuid4

from agno.agent import Agent
from agno.media import ImageArtifact, VideoArtifact
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_info

try:
    from google.genai import Client
    from google.genai.types import GenerateImagesResponse, GenerateVideosOperation
except (ModuleNotFoundError, ImportError):
    raise ImportError("`google-genai` not installed. Please install using `pip install google-genai`")


class GeminiTools(Toolkit):
    """Tools for interacting with Google Gemini API"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        vertexai: bool = False,
        project_id: Optional[str] = None,
        location: Optional[str] = None,
        image_generation_model: str = "imagen-3.0-generate-002",
        video_generation_model: str = "veo-2.0-generate-001",
        **kwargs,
    ):
        super().__init__(name="gemini_tools", tools=[self.generate_image, self.generate_video], **kwargs)

        # Set mode and credentials: use only provided vertexai parameter
        self.vertexai = vertexai
        self.project_id = project_id
        self.location = location

        # Load API key from argument or environment
        self.api_key = api_key or getenv("GOOGLE_API_KEY")
        if not self.vertexai and not self.api_key:
            log_error("GOOGLE_API_KEY not set. Please set the GOOGLE_API_KEY environment variable.")
            raise ValueError("GOOGLE_API_KEY not set. Please provide api_key or set the environment variable.")

        # Prepare client parameters
        client_params: dict[str, Any] = {}
        if self.vertexai:
            log_info("Using Vertex AI API")
            client_params["vertexai"] = True
            client_params["project"] = self.project_id or getenv("GOOGLE_CLOUD_PROJECT")
            client_params["location"] = self.location or getenv("GOOGLE_CLOUD_LOCATION")
        else:
            log_info("Using Gemini API")
            client_params["api_key"] = self.api_key

        try:
            self.client = Client(**client_params)
            log_debug("Google GenAI Client created successfully.")
        except Exception as e:
            log_error(f"Failed to create Google GenAI Client: {e}", exc_info=True)
            raise ValueError(f"Failed to create Google GenAI Client. Error: {e}")

        self.image_model = image_generation_model
        self.video_model = video_generation_model

    def generate_image(
        self,
        agent: Agent,
        prompt: str,
    ) -> str:
        """Generate images based on a text prompt using Google Imagen.

        Args:
            prompt (str): The text prompt to generate the image from.
        Returns:
            str: A message indicating success (including media ID) or failure.
        """

        try:
            response: GenerateImagesResponse = self.client.models.generate_images(
                model=self.image_model,
                prompt=prompt,
            )

            log_debug("DEBUG: Raw Gemini API response")

            # Extract image bytes
            image_bytes = response.generated_images[0].image.image_bytes
            for generated_image in response.generated_images:
                image_bytes = generated_image.image.image_bytes
                if not image_bytes:
                    log_error("No valid image data extracted.")
                    return "Failed to generate image: No valid image data extracted."
                base64_encoded_image_bytes = base64.b64encode(image_bytes)
                actual_mime_type = "image/png"

                media_id = str(uuid4())
                agent.add_image(
                    ImageArtifact(
                        id=media_id,
                        content=base64_encoded_image_bytes,
                        original_prompt=prompt,
                        mime_type=actual_mime_type,
                    )
                )
                log_debug(f"Successfully generated image {media_id} with model {self.image_model}")
            return "Image generated successfully"

        except Exception as e:
            log_error(f"Failed to generate image: Client or method not available ({e})")
            return f"Failed to generate image: Client or method not available ({e})"

    def generate_video(
        self,
        agent: Agent,
        prompt: str,
    ) -> str:
        """Generate a video based on a text prompt.
        Args:
            prompt (str): The text prompt to generate the video from.
        Returns:
            str: A message indicating success or failure.
        """
        # Video generation requires Vertex AI mode.
        if not self.vertexai:
            log_error("Video generation requires Vertex AI mode. Please enable Vertex AI mode.")
            return (
                "Video generation requires Vertex AI mode. "
                "Please set `vertexai=True` or environment variable `GOOGLE_GENAI_USE_VERTEXAI=true`."
            )

        from google.genai.types import GenerateVideosConfig

        try:
            operation: GenerateVideosOperation = self.client.models.generate_videos(
                model=self.video_model,
                prompt=prompt,
                config=GenerateVideosConfig(
                    enhance_prompt=True,
                ),
            )

            while not operation.done:
                time.sleep(5)
                operation = self.client.operations.get(operation=operation)

            for video in operation.result.generated_videos:
                generated_video = video.video

                media_id = str(uuid4())
                encoded_video = base64.b64encode(generated_video.video_bytes).decode("utf-8")

                agent.add_video(
                    VideoArtifact(
                        id=media_id,
                        content=encoded_video,
                        original_prompt=prompt,
                        mime_type=generated_video.mime_type,
                    )
                )
                log_debug(f"Successfully generated video {media_id} with model {self.video_model}")
            return "Video generated successfully"
        except Exception as e:
            log_error(f"Failed to generate video: {e}")
            return f"Failed to generate video: {e}"
