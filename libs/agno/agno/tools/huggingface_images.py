from io import BytesIO
from os import getenv
from typing import Any, List, Optional
from uuid import uuid4

from agno.media import Image
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import log_debug, log_error, logger

try:
    from huggingface_hub import InferenceClient
except ImportError:
    raise ImportError("`huggingface_hub` not installed. Please install using `pip install huggingface_hub`")


class HuggingFaceImageTools(Toolkit):
    """Toolkit for generating images using Hugging Face Inference API.

    Args:
        model: The model ID on Hugging Face Hub. Default: "black-forest-labs/FLUX.1-schnell".
        provider: The inference provider. Default: "hf-inference".
        api_key: Hugging Face API token. Defaults to HF_TOKEN environment variable.
        image_format: Output image format. Default: "png".
        enable_create_image: Register the create_image tool. Default: True.
    """

    def __init__(
        self,
        model: str = "black-forest-labs/FLUX.1-schnell",
        provider: str = "hf-inference",
        api_key: Optional[str] = None,
        image_format: str = "png",
        enable_create_image: bool = True,
        **kwargs: Any,
    ):
        self.model = model
        self.provider = provider
        self.api_key = api_key or getenv("HF_TOKEN")
        self.image_format = image_format

        if not self.api_key:
            log_error("HF_TOKEN not set. Please set the HF_TOKEN environment variable or pass api_key.")

        tools: List[Any] = []
        if enable_create_image:
            tools.append(self.create_image)

        super().__init__(name="huggingface_images", tools=tools, **kwargs)

    def create_image(self, prompt: str) -> ToolResult:
        """Generate an image from a text prompt using Hugging Face Inference API.

        Args:
            prompt: A detailed text description of the image to generate.

        Returns:
            ToolResult containing the generated image.
        """
        if not self.api_key:
            return ToolResult(content="Error: HF_TOKEN not set. Please set the HF_TOKEN environment variable.")

        try:
            log_debug(f"Generating image with model: {self.model}")
            client = InferenceClient(provider=self.provider, api_key=self.api_key)
            image = client.text_to_image(prompt, model=self.model)

            buffer = BytesIO()
            image.save(buffer, format=self.image_format.upper())
            image_bytes = buffer.getvalue()

            generated_image = Image(
                id=str(uuid4()),
                content=image_bytes,
                format=self.image_format,
                original_prompt=prompt,
            )

            log_debug(f"Image generated successfully: {generated_image.id}")
            return ToolResult(
                content=f"Image generated successfully from prompt: {prompt}",
                images=[generated_image],
            )
        except Exception as e:
            log_error(f"Failed to generate image: {e}")
            return ToolResult(content=f"Error generating image: {e}")
