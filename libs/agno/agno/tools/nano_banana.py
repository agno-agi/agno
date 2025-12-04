from __future__ import annotations

import os
from io import BytesIO
from typing import Any, List, Optional
from uuid import uuid4

from agno.media import Image
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import log_debug, logger

try:
    from google import genai
    from google.genai import types
    from PIL import Image as PILImage

except ImportError as exc:
    missing = []
    try:
        from google.genai import types
    except ImportError:
        missing.append("google-genai")

    try:
        from PIL import Image as PILImage
    except ImportError:
        missing.append("Pillow")

    raise ImportError(
        f"Missing required package(s): {', '.join(missing)}. Install using: pip install {' '.join(missing)}"
    ) from exc


# Note: Expand this list as new models become supported by the Google Content Generation API.
ALLOWED_MODELS = ["gemini-2.5-flash-image"]
ALLOWED_RATIOS = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]


class NanoBananaTools(Toolkit):
    def __init__(
        self,
        model: str = "gemini-2.5-flash-image",
        aspect_ratio: str = "1:1",
        api_key: Optional[str] = None,
        enable_create_image: bool = True,
        **kwargs,
    ):
        self.model = model
        self.aspect_ratio = aspect_ratio
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")

        # Validate model
        if model not in ALLOWED_MODELS:
            raise ValueError(f"Invalid model '{model}'. Supported: {', '.join(ALLOWED_MODELS)}")

        if self.aspect_ratio not in ALLOWED_RATIOS:
            raise ValueError(f"Invalid aspect_ratio '{self.aspect_ratio}'. Supported: {', '.join(ALLOWED_RATIOS)}")

        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY not set. Export it: `export GOOGLE_API_KEY=<your-key>`")

        tools: List[Any] = []
        if enable_create_image:
            tools.append(self.create_image)

        super().__init__(name="nano_banana", tools=tools, **kwargs)

    def create_image(self, prompt: str) -> ToolResult:
        """Generate an image from a text prompt."""
        try:
            client = genai.Client(api_key=self.api_key)
            log_debug(f"NanoBanana generating image with prompt: {prompt}")

            cfg = types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio=self.aspect_ratio),
            )

            response = client.models.generate_content(
                model=self.model,
                contents=[prompt],  # type: ignore
                config=cfg,
            )

            generated_images: List[Image] = []
            response_str = ""

            if not hasattr(response, "candidates") or not response.candidates:
                logger.warning("No candidates in response")
                return ToolResult(content="No images were generated in the response")

            # Process each candidate
            for candidate in response.candidates:
                if not hasattr(candidate, "content") or not candidate.content or not candidate.content.parts:
                    continue

                for part in candidate.content.parts:
                    if hasattr(part, "text") and part.text:
                        response_str += part.text + "\n"

                    if hasattr(part, "inline_data") and part.inline_data:
                        try:
                            # Extract image data from the blob
                            image_data = part.inline_data.data
                            mime_type = getattr(part.inline_data, "mime_type", "image/png")

                            if image_data:
                                pil_img = PILImage.open(BytesIO(image_data))

                                # Save to buffer with proper format
                                buffer = BytesIO()
                                image_format = "PNG" if "png" in mime_type.lower() else "JPEG"
                                pil_img.save(buffer, format=image_format)
                                buffer.seek(0)

                                agno_img = Image(
                                    id=str(uuid4()),
                                    content=buffer.getvalue(),
                                    original_prompt=prompt,
                                )
                                generated_images.append(agno_img)

                                log_debug(f"Successfully processed image with ID: {agno_img.id}")
                                response_str += f"Image generated successfully (ID: {agno_img.id}).\n"

                        except Exception as img_exc:
                            logger.error(f"Failed to process image data: {img_exc}")
                            response_str += f"Failed to process image: {img_exc}\n"

            if hasattr(response, "usage_metadata") and response.usage_metadata:
                log_debug(
                    f"Token usage - Prompt: {response.usage_metadata.prompt_token_count}, "
                    f"Response: {response.usage_metadata.candidates_token_count}, "
                    f"Total: {response.usage_metadata.total_token_count}"
                )

            if generated_images:
                return ToolResult(
                    content=response_str.strip() or "Image(s) generated successfully",
                    images=generated_images,
                )
            else:
                return ToolResult(
                    content=response_str.strip() or "No images were generated",
                    images=None,
                )

        except Exception as exc:
            logger.error(f"NanoBanana image generation failed: {exc}")
            return ToolResult(content=f"Error generating image: {str(exc)}")
