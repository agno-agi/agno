import base64
import io
from os import getenv
from typing import Optional
from uuid import uuid4

from agno.agent import Agent
from agno.media import ImageArtifact
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_warning

try:
    from google.genai import Client
except (ModuleNotFoundError, ImportError):
    raise ImportError("`google-genai` not installed. Please install using `pip install google-genai`")


class GeminiTools(Toolkit):
    """Tools for interacting with Google Gemini API (including Imagen for images)"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_image_generation: bool = True,
        image_generation_model: str = "imagen-3.0-generate-002", 
        **kwargs,
    ):
        super().__init__(name="gemini_tools", **kwargs)

        self.api_key = api_key or getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "GOOGLE_API_KEY not set. Please provide api_key or set the GOOGLE_API_KEY environment variable."
            )

        try:
            self.client = Client(api_key=self.api_key)
            log_debug("Google GenAI Client created successfully.")
        except Exception as e:
            log_error(f"Failed to create Google GenAI Client: {e}", exc_info=True)
            raise ValueError(f"Failed to create Google GenAI Client. Error: {e}")

        self.image_model = image_generation_model

        if enable_image_generation:
            self.register(self.generate_image)

    def generate_image(
        self,
        agent: Agent,
        prompt: str,
    ) -> str:
        """Generate images based on a text prompt using Google Imagen.

        Args:
            agent (Agent): The agent instance to add the artifact to.
            prompt (str): The text prompt to generate the image from.
        Returns:
            str: A message indicating success (including media ID) or failure.
        """

        try:
            response = self.client.models.generate_images(
                model=self.image_model,
                prompt=prompt,
            )

            log_debug(f"DEBUG: Raw Gemini API response")

            image_bytes = None
            actual_mime_type = "image/png"

            
            if response.generated_images and response.generated_images[0].image.image_bytes:
                image_bytes = response.generated_images[0].image.image_bytes
            else:
                log_error(f"DEBUG: Error accessing image_bytes attribute: {e}")
                return f"Failed to generate image: No valid image data extracted."

            base64_encoded_image = base64.b64encode(image_bytes).decode("utf-8")

            media_id = str(uuid4())
            agent.add_image(
                ImageArtifact(
                    id=media_id,
                    content=base64_encoded_image,
                    prompt=prompt,
                    model=self.image_model,
                    mime_type=actual_mime_type,
                )
            )
            log_debug(f"Successfully generated image {media_id} with model {self.image_model}")
            return f"Image generated successfully with ID: {media_id}"

        except Exception as e:
            log_error(f"Failed to generate image: Client or method not available ({e})")
            return f"Failed to generate image: Client or method not available ({e})"
