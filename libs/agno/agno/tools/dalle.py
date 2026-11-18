import base64
from os import getenv
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from agno.media import Image
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import log_debug, log_error, log_warning, logger

try:
    from openai import OpenAI
    from openai.types.images_response import ImagesResponse
except ImportError:
    raise ImportError("`openai` not installed. Please install using `pip install openai`")

from agno.tools.openai import IMAGE_MODEL_OPTIONS, STYLE_DEPRECATION, validate_image_options


class DalleTools(Toolkit):
    """Deprecated: use OpenAITools(enable_transcription=False, enable_speech_generation=False) instead."""

    def __init__(
        self,
        model: str = "gpt-image-2",
        n: int = 1,
        size: Optional[str] = "1024x1024",
        quality: Literal["auto", "low", "medium", "high"] = "auto",
        style: Optional[Literal["vivid", "natural"]] = None,
        api_key: Optional[str] = None,
        enable_create_image: bool = True,
        all: bool = False,
        **kwargs,
    ):
        log_warning(
            "DalleTools is deprecated and will be removed in a future release, as OpenAI has retired the DALL-E models. "
            "Use OpenAITools(enable_transcription=False, enable_speech_generation=False) instead."
        )
        self.model = model
        self.n = n
        self.size = size
        self.quality = quality
        self.style = style
        self.api_key = api_key or getenv("OPENAI_API_KEY")

        # Validations
        if model not in IMAGE_MODEL_OPTIONS:
            raise ValueError(f"Invalid model. Please choose from {', '.join(IMAGE_MODEL_OPTIONS)}.")
        validate_image_options(model, n, size, quality)
        if style is not None:
            log_warning(STYLE_DEPRECATION)

        if not self.api_key:
            log_error("OPENAI_API_KEY not set. Please set the OPENAI_API_KEY environment variable.")

        tools: List[Any] = []
        if all or enable_create_image:
            tools.append(self.create_image)

        super().__init__(name="dalle", tools=tools, **kwargs)

        # TODO:
        # - Add support for response_format
        # - Add support for saving images
        # - Add support for editing images

    def create_image(self, prompt: str) -> ToolResult:
        """Use this function to generate an image for a prompt.

        Args:
            prompt (str): A text description of the desired image.

        Returns:
            ToolResult: Result containing the message and generated images.
        """
        if not self.api_key:
            return ToolResult(content="Please set the OPENAI_API_KEY")

        try:
            client = OpenAI(api_key=self.api_key)
            log_debug(f"Generating image using prompt: {prompt}")
            request_params: Dict[str, Any] = {
                "prompt": prompt,
                "model": self.model,
                "n": self.n,
                "quality": self.quality,
                "size": self.size,
            }
            response: ImagesResponse = client.images.generate(**request_params)
            log_debug("Image generated successfully")

            generated_images = []
            response_str = ""
            if response.data:
                for img in response.data:
                    if img.url:
                        image = Image(
                            id=str(uuid4()),
                            url=img.url,
                            original_prompt=prompt,
                            revised_prompt=img.revised_prompt,
                        )
                        generated_images.append(image)
                        response_str += f"Image has been generated at the URL {img.url}\n"
                    elif img.b64_json:
                        # GPT Image models return base64 data only, never a URL.
                        image = Image(
                            id=str(uuid4()),
                            content=base64.b64decode(img.b64_json),
                            mime_type=f"image/{getattr(response, 'output_format', None) or 'png'}",
                            original_prompt=prompt,
                        )
                        generated_images.append(image)
                        response_str += "Image has been generated\n"

            return ToolResult(
                content=response_str or "No images were generated",
                images=generated_images if generated_images else None,
            )
        except Exception as e:
            logger.exception("Failed to generate image")
            return ToolResult(content=f"Error: {e}")
