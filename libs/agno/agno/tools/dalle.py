import base64
from os import getenv
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from agno.media import Image
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import log_debug, log_error, logger

try:
    from openai import OpenAI
    from openai.types.images_response import ImagesResponse
except ImportError:
    raise ImportError("`openai` not installed. Please install using `pip install openai`")

_GPT_IMAGE_OPTIONS = {
    "sizes": ["auto", "1024x1024", "1536x1024", "1024x1536"],
    "qualities": ["auto", "low", "medium", "high"],
}
# Sizes and qualities each image model accepts.
MODEL_OPTIONS: Dict[str, Dict[str, List[str]]] = {
    "gpt-image-2": _GPT_IMAGE_OPTIONS,
    "gpt-image-1": _GPT_IMAGE_OPTIONS,
    "gpt-image-1-mini": _GPT_IMAGE_OPTIONS,
    "dall-e-3": {"sizes": ["1024x1024", "1792x1024", "1024x1792"], "qualities": ["auto", "standard", "hd"]},
    "dall-e-2": {"sizes": ["256x256", "512x512", "1024x1024"], "qualities": ["auto", "standard"]},
}


class DalleTools(Toolkit):
    def __init__(
        self,
        model: str = "gpt-image-2",
        n: int = 1,
        size: Optional[
            Literal["auto", "1024x1024", "1536x1024", "1024x1536", "256x256", "512x512", "1792x1024", "1024x1792"]
        ] = "1024x1024",
        quality: Literal["auto", "low", "medium", "high", "standard", "hd"] = "auto",
        style: Optional[Literal["vivid", "natural"]] = None,
        api_key: Optional[str] = None,
        enable_create_image: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.model = model
        self.n = n
        self.size = size
        self.quality = quality
        self.style = style
        self.api_key = api_key or getenv("OPENAI_API_KEY")

        # Validations
        if model not in MODEL_OPTIONS:
            raise ValueError(f"Invalid model. Please choose from {', '.join(MODEL_OPTIONS)}.")
        options = MODEL_OPTIONS[model]
        if size not in options["sizes"]:
            raise ValueError(f"Invalid size for {model}. Please choose from {', '.join(options['sizes'])}.")
        if quality not in options["qualities"]:
            raise ValueError(f"Invalid quality for {model}. Please choose from {', '.join(options['qualities'])}.")
        if not isinstance(n, int) or n <= 0:
            raise ValueError("Invalid number of images. Please provide a positive integer.")
        if model == "dall-e-3" and n > 1:
            raise ValueError("Dall-e-3 only supports a single image generation.")

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
            # OpenAI removed the dall-e-3 'style' parameter from the images API
            # (400 "Unknown parameter"); only forward it when explicitly set.
            if self.style is not None:
                request_params["style"] = self.style
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
                            revised_prompt=img.revised_prompt,
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
