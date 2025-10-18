from os import getenv
from pathlib import Path
from typing import Any, List, Literal, Optional, Union
from uuid import uuid4

from agno.agent import Agent
from agno.media import Image
from agno.team.team import Team
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import log_debug, logger

try:
    from openai import OpenAI
    from openai.types.images_response import ImagesResponse
except ImportError:
    raise ImportError("`openai` not installed. Please install using `pip install openai`")


class DalleTools(Toolkit):
    def __init__(
        self,
        model: str = "dall-e-3",
        n: int = 1,
        size: Optional[Literal["256x256", "512x512", "1024x1024", "1792x1024", "1024x1792"]] = "1024x1024",
        quality: Literal["standard", "hd"] = "standard",
        style: Literal["vivid", "natural"] = "vivid",
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
        
        # Optional kwargs to keep signature backward-compatible
        self.response_format: Literal["url", "b64_json"] = kwargs.pop("response_format", "url")  # type: ignore
        enable_save_image_flag: bool = bool(kwargs.pop("enable_save_image", False))
        enable_edit_image_flag: bool = bool(kwargs.pop("enable_edit_image", False))
        self.api_key = api_key or getenv("OPENAI_API_KEY")

        # Validations
        if model not in ["dall-e-3", "dall-e-2"]:
            raise ValueError("Invalid model. Please choose from 'dall-e-3' or 'dall-e-2'.")
        if size not in ["256x256", "512x512", "1024x1024", "1792x1024", "1024x1792"]:
            raise ValueError(
                "Invalid size. Please choose from '256x256', '512x512', '1024x1024', '1792x1024', '1024x1792'."
            )
        if quality not in ["standard", "hd"]:
            raise ValueError("Invalid quality. Please choose from 'standard' or 'hd'.")
        if not isinstance(n, int) or n <= 0:
            raise ValueError("Invalid number of images. Please provide a positive integer.")
        if model == "dall-e-3" and n > 1:
            raise ValueError("Dall-e-3 only supports a single image generation.")
        if self.response_format not in ["url", "b64_json"]:
            raise ValueError("Invalid response_format. Please choose from 'url' or 'b64_json'.")

        if not self.api_key:
            logger.error("OPENAI_API_KEY not set. Please set the OPENAI_API_KEY environment variable.")

        tools: List[Any] = []
        if all or enable_create_image:
            tools.append(self.create_image)
        if all or enable_save_image_flag:
            tools.append(self.save_image)
        if all or enable_edit_image_flag:
            tools.append(self.edit_image)

        super().__init__(name="dalle", tools=tools, **kwargs)
        

    def create_image(
        self,
        agent: Union[Agent, Team],
        prompt: str,
        response_format: Optional[Literal["url", "b64_json"]] = None,
    ) -> ToolResult:
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
            response: ImagesResponse = client.images.generate(
                prompt=prompt,
                model=self.model,
                n=self.n,
                quality=self.quality,
                size=self.size,
                style=self.style,
                response_format=(response_format or self.response_format),
            )
            log_debug("Image generated successfully")

            generated_images = []
            response_str = ""
            if response.data:
                for img in response.data:
                    # Prefer URL when provided
                    if getattr(img, "url", None):
                        image = Image(
                            id=str(uuid4()),
                            url=img.url,
                            original_prompt=prompt,
                            revised_prompt=getattr(img, "revised_prompt", None),
                        )
                        generated_images.append(image)
                        response_str += f"Image has been generated at the URL {img.url}\n"
                    # Handle base64 responses
                    elif getattr(img, "b64_json", None):
                        b64_val = getattr(img, "b64_json")
                        image = Image.from_base64(
                            b64_val,
                            mime_type="image/png",
                            format="png",
                            original_prompt=prompt,
                            revised_prompt=getattr(img, "revised_prompt", None),
                        )
                        generated_images.append(image)
                        response_str += "Image has been generated (base64 content).\n"

            return ToolResult(
                content=response_str or "No images were generated",
                images=generated_images if generated_images else None,
            )
        except Exception as e:
            logger.error(f"Failed to generate image: {e}")
            return ToolResult(content=f"Error: {e}")

    def save_image(
        self,
        agent: Union[Agent, Team],
        image: Image,
        filepath: Optional[Union[str, Path]] = None,
    ) -> ToolResult:
        """Save an Image locally.

        Args:
            image (Image): The image object to save. Can be URL- or content-based.
            filepath (Optional[str|Path]): Where to save the file. Defaults to tmp/images/<id>.png

        Returns:
            ToolResult: Message with saved path and the saved image reference.
        """
        try:
            content_bytes = image.get_content_bytes()
            if not content_bytes:
                return ToolResult(content="No image content available to save")

            # Determine output path
            default_name = f"dalle-{image.id or str(uuid4())}.png"
            out_path = Path(filepath) if filepath else Path("tmp/images") / default_name
            out_path.parent.mkdir(parents=True, exist_ok=True)

            with open(out_path, "wb") as f:
                f.write(content_bytes)

            log_debug(f"Image saved to {out_path}")

            saved_image = Image(
                id=image.id or str(uuid4()),
                filepath=str(out_path),
                original_prompt=image.original_prompt,
                revised_prompt=image.revised_prompt,
                format=image.format or "png",
                mime_type=image.mime_type or "image/png",
            )

            return ToolResult(
                content=f"Saved image to {out_path}",
                images=[saved_image],
            )
        except Exception as e:
            logger.error(f"Failed to save image: {e}")
            return ToolResult(content=f"Error saving image: {e}")

    def edit_image(
        self,
        agent: Union[Agent, Team],
        image: Image,
        prompt: Optional[str] = None,
        mask: Optional[Image] = None,
        response_format: Optional[Literal["url", "b64_json"]] = None,
    ) -> ToolResult:
        """Edit an image using DALL-E edit endpoint (if supported by the model).

        Notes:
            - `dall-e-2` supports image edits/variations; `dall-e-3` edit support may be limited.
            - If the current model does not support edits, returns a graceful message.
        """
        if not self.api_key:
            return ToolResult(content="Please set the OPENAI_API_KEY")

        # Basic model capability check
        if self.model == "dall-e-3":
            return ToolResult(content="Image edit is not currently supported for 'dall-e-3' in this SDK.")

        try:
            client = OpenAI(api_key=self.api_key)

            # Prepare image and optional mask bytes
            image_bytes = image.get_content_bytes()
            if image_bytes is None and image.url is None and image.filepath is None:
                return ToolResult(content="No image content provided for editing")

            # OpenAI images edits expects files; use in-memory bytes or URL fetch via Image helper
            # For simplicity, write to a temporary file if bytes
            import tempfile

            temp_files = []
            try:
                def to_temp(image_obj: Image, suffix: str = ".png") -> Optional[str]:
                    content = image_obj.get_content_bytes()
                    if not content:
                        return None
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                    tmp.write(content)
                    tmp.flush()
                    tmp.close()
                    temp_files.append(tmp.name)
                    return tmp.name

                image_path = image.filepath if image.filepath else to_temp(image)
                mask_path = mask.filepath if mask and mask.filepath else (to_temp(mask) if mask else None)

                # Perform edit call (DALL-E 2 style)
                # New OpenAI SDKs often expose edits under client.images.edits
                # If not available, return a helpful message
                if not hasattr(client.images, "edits"):
                    return ToolResult(content="OpenAI client does not support image edits via SDK version in use.")

                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "n": self.n,
                    "size": self.size,
                    "response_format": (response_format or self.response_format),
                }
                if prompt:
                    kwargs["prompt"] = prompt

                # file arguments are passed as file handles
                files = {}
                if image_path:
                    files["image"] = open(image_path, "rb")
                if mask_path:
                    files["mask"] = open(mask_path, "rb")

                try:
                    resp = client.images.edits(**kwargs, **files)  # type: ignore[arg-type]
                finally:
                    for f in files.values():
                        try:
                            f.close()
                        except Exception:
                            pass

                generated_images = []
                response_str = ""
                if getattr(resp, "data", None):
                    for img in resp.data:
                        if getattr(img, "url", None):
                            generated_images.append(
                                Image(
                                    id=str(uuid4()),
                                    url=img.url,
                                    original_prompt=prompt,
                                    revised_prompt=getattr(img, "revised_prompt", None),
                                )
                            )
                            response_str += f"Edited image available at {img.url}\n"
                        elif getattr(img, "b64_json", None):
                            generated_images.append(
                                Image.from_base64(
                                    img.b64_json,
                                    mime_type="image/png",
                                    format="png",
                                    original_prompt=prompt,
                                    revised_prompt=getattr(img, "revised_prompt", None),
                                )
                            )
                            response_str += "Edited image (base64 content).\n"

                return ToolResult(
                    content=response_str or "No edited images were generated",
                    images=generated_images if generated_images else None,
                )
            finally:
                # Cleanup temp files
                for fp in temp_files:
                    try:
                        Path(fp).unlink(missing_ok=True)  # type: ignore[arg-type]
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Failed to edit image: {e}")
            return ToolResult(content=f"Error editing image: {e}")
