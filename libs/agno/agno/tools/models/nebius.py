import base64
from os import getenv
from typing import Optional
from uuid import uuid4

from agno.agent import Agent
from agno.media import ImageArtifact
from agno.models.nebius import Nebius
from agno.tools import Toolkit
from agno.utils.log import log_error, log_warning


class NebiusTools(Toolkit):
    """Tools for interacting with Nebius AI Studio's text-to-image API"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.studio.nebius.com/v1",
        image_model: str = "black-forest-labs/flux-schnell",
        image_quality: Optional[str] = "standard",
        image_size: Optional[str] = "1024x1024",
        image_style: Optional[str] = None,
        **kwargs,
    ):
        """Initialize Nebius AI Studio text-to-image tools.

        Args:
            api_key: Nebius API key. If not provided, will look for NEBIUS_API_KEY environment variable.
            base_url: The base URL for the Nebius AI Studio API. This should be configured according to Nebius's documentation.
            image_model: The model to use for generation. Options include:
                  - "black-forest-labs/flux-schnell" (fastest)
                  - "black-forest-labs/flux-dev" (balanced)
                  - "stability-ai/sdxl" (highest quality)
            image_quality: Image quality. Options: "standard", "hd".
            image_size: Image size in format "WIDTHxHEIGHT". Max supported: 2000x2000.
            image_style: Optional style preset to apply.
            **kwargs: Additional arguments to pass to Toolkit.
        """
        super().__init__(name="nebius_tools", tools=[self.generate_image], **kwargs)

        self.api_key = api_key or getenv("NEBIUS_API_KEY")
        if not self.api_key:
            raise ValueError("NEBIUS_API_KEY not set. Please set the NEBIUS_API_KEY environment variable.")

        self.base_url = base_url
        self.image_model = image_model
        self.image_quality = image_quality
        self.image_size = image_size
        self.image_style = image_style
        self._nebius_client: Optional[Nebius] = None

    def _get_client(self):
        if self._nebius_client is None:
            self._nebius_client = Nebius(api_key=self.api_key, base_url=self.base_url, id=self.image_model).get_client()  # type: ignore
        return self._nebius_client

    def generate_image(
        self,
        agent: Agent,
        prompt: str,
    ) -> str:
        """Generate images based on a text prompt using Nebius AI Studio.

        Args:
            agent: The agent instance for adding images
            prompt: The text prompt to generate images from.

        Returns:
            A message indicating success or failure.
        """
        try:
            extra_params = {
                "size": self.image_size,
                "quality": self.image_quality,
                "style": self.image_style,
            }
            extra_params = {k: v for k, v in extra_params.items() if v is not None}

            client = self._get_client()

            response = client.images.generate(
                model=self.image_model,
                prompt=prompt,
                response_format="b64_json",
                **extra_params,
            )

            data = None
            if hasattr(response, "data") and response.data:
                data = response.data[0]
            if data is None:
                log_warning("Nebius API did not return any data.")
                return "Failed to generate image: No data received from API."
            if hasattr(data, "b64_json") and data.b64_json:
                image_base64 = data.b64_json
                image_content_bytes = base64.b64decode(image_base64)
                media_id = str(uuid4())
                agent.add_image(
                    ImageArtifact(
                        id=media_id, content=image_content_bytes, mime_type="image/png", original_prompt=prompt
                    )
                )
                return "Image generated successfully."
            return "Failed to generate image: No content received from API."
        except Exception as e:
            log_error(f"Failed to generate image using {self.image_model}: {e}")
            return f"Failed to generate image: {e}"
