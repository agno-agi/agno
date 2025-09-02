from os import getenv
from pathlib import Path
from typing import Any, Iterable, Iterator, List, Optional, Tuple, Union
from urllib.parse import urlparse
from uuid import uuid4

from agno.agent import Agent
from agno.media import ImageArtifact, VideoArtifact
from agno.team.team import Team
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import logger

try:
    import replicate
    from replicate.helpers import FileOutput
except ImportError:
    raise ImportError("`replicate` not installed. Please install using `pip install replicate`.")


class ReplicateTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "minimax/video-01",
        enable_generate_media: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("REPLICATE_API_KEY")
        if not self.api_key:
            logger.error("REPLICATE_API_KEY not set. Please set the REPLICATE_API_KEY environment variable.")
        self.model = model

        tools: List[Any] = []
        if all or enable_generate_media:
            tools.append(self.generate_media)

        super().__init__(name="replicate_toolkit", tools=tools, **kwargs)

    def generate_media(self, agent: Union[Agent, Team], prompt: str) -> ToolResult:
        """
        Use this function to generate an image or a video using a replicate model.
        Args:
            prompt (str): A text description of the content.
        Returns:
            ToolResult: A ToolResult containing the generated media or error message.
        """
        if not self.api_key:
            logger.error("API key is not set. Please provide a valid API key.")
            return ToolResult(content="API key is not set.")

        try:
            outputs = replicate.run(ref=self.model, input={"prompt": prompt})
            if isinstance(outputs, FileOutput):
                outputs = [outputs]
            elif isinstance(outputs, (Iterable, Iterator)) and not isinstance(outputs, str):
                outputs = list(outputs)
            else:
                logger.error(f"Unexpected output type: {type(outputs)}")
                return ToolResult(content=f"Unexpected output type: {type(outputs)}")

            images = []
            videos = []
            results = []

            for output in outputs:
                if not isinstance(output, FileOutput):
                    logger.error(f"Unexpected output type: {type(output)}")
                    return ToolResult(content=f"Unexpected output type: {type(output)}")

                result_msg, media_artifact = self._parse_output(output)
                results.append(result_msg)

                if isinstance(media_artifact, ImageArtifact):
                    images.append(media_artifact)
                elif isinstance(media_artifact, VideoArtifact):
                    videos.append(media_artifact)

            content = "\n".join(results)
            return ToolResult(
                content=content,
                images=images if images else None,
                videos=videos if videos else None,
            )
        except Exception as e:
            logger.error(f"Failed to generate media: {e}")
            return ToolResult(content=f"Error: {e}")

    def _parse_output(self, output: FileOutput) -> Tuple[str, Union[ImageArtifact, VideoArtifact]]:
        """
        Parse the outputs from the replicate model.
        """
        # Parse the URL to extract the file extension
        parsed_url = urlparse(output.url)
        path = parsed_url.path
        ext = Path(path).suffix.lower()

        # Define supported extensions
        image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"}
        video_extensions = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".webm"}

        media_id = str(uuid4())
        artifact: Union[ImageArtifact, VideoArtifact]
        media_type: str

        if ext in image_extensions:
            artifact = ImageArtifact(id=media_id, url=output.url)
            media_type = "image"
        elif ext in video_extensions:
            artifact = VideoArtifact(id=media_id, url=output.url)
            media_type = "video"
        else:
            logger.error(f"Unsupported media type with extension '{ext}' for URL: {output.url}")
            raise ValueError(f"Unsupported media type with extension '{ext}'.")

        return f"{media_type.capitalize()} generated successfully at {output.url}", artifact
