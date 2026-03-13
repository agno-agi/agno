from io import BytesIO
from pathlib import Path
from typing import IO, Any, List, Optional, Union

from agno.agent import Agent
from agno.knowledge.chunking.strategy import ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.media import Image
from agno.models.openai import OpenAIChat


class ImageReader(Reader):
    """Reader for extracting text from images using a vision-capable Agent."""

    def __init__(
        self,
        model: Optional[Any] = None,
        instructions: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.model = model or OpenAIChat(id="gpt-4o")
        self.instructions = instructions or (
            "You are an expert at extracting text from images. "
            "Extract all text content from the provided image exactly as it appears. "
            "Return only the raw extracted text without any formatting, commentary, or explanation."
        )
        # Create agent once, reuse for all reads
        self._agent = Agent(
            model=self.model,
            instructions=self.instructions,
        )

    @classmethod
    def get_supported_chunking_strategies(cls) -> List[ChunkingStrategyType]:
        """Get the list of supported chunking strategies for image readers."""
        return [
            ChunkingStrategyType.FIXED_SIZE_CHUNKER,
            ChunkingStrategyType.DOCUMENT_CHUNKER,
            ChunkingStrategyType.RECURSIVE_CHUNKER,
            ChunkingStrategyType.SEMANTIC_CHUNKER,
            ChunkingStrategyType.AGENTIC_CHUNKER,
        ]

    @classmethod
    def get_supported_content_types(cls) -> List[str]:
        """Get the list of supported content types for image readers."""
        return [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"]

    def read(
        self,
        image_source: Union[str, Path, IO[bytes], BytesIO],
        name: Optional[str] = None,
        password: Optional[str] = None,
    ) -> List[Document]:
        """Read text from an image file or byte stream using an Agent.

        Args:
            image_source: Path to the image file, or a BytesIO/file-like object
            name: Optional name for the document
            password: Not used for images, included for API compatibility

        Returns:
            List of Document objects containing extracted text
        """
        if not image_source:
            return []

        # Handle BytesIO or file-like objects
        if isinstance(image_source, (BytesIO, IO)):
            image_bytes = (
                image_source.read()
                if hasattr(image_source, "read")
                else image_source.getvalue()
            )
            doc_name = name or "image"
            image = Image(content=image_bytes)
            source_info = "bytes"
        else:
            # Handle file path
            image_path = Path(image_source)
            doc_name = name or image_path.stem.replace(" ", "_")
            image = Image(filepath=image_path)
            source_info = str(image_path)

        # Run the agent with the image
        response = self._agent.run(
            "Extract all text from this image.",
            images=[image],
        )

        content = response.content if response.content else ""

        document = Document(
            name=doc_name,
            content=content,
            meta_data={"source": source_info},
        )

        if self.chunk:
            return self.chunk_document(document)
        return [document]

    async def async_read(
        self,
        image_source: Union[str, Path, IO[bytes], BytesIO],
        name: Optional[str] = None,
        password: Optional[str] = None,
    ) -> List[Document]:
        """Async version of read."""
        if not image_source:
            return []

        # Handle BytesIO or file-like objects
        if isinstance(image_source, (BytesIO, IO)):
            image_bytes = (
                image_source.read()
                if hasattr(image_source, "read")
                else image_source.getvalue()
            )
            doc_name = name or "image"
            image = Image(content=image_bytes)
            source_info = "bytes"
        else:
            # Handle file path
            image_path = Path(image_source)
            doc_name = name or image_path.stem.replace(" ", "_")
            image = Image(filepath=image_path)
            source_info = str(image_path)

        response = await self._agent.arun(
            "Extract all text from this image.",
            images=[image],
        )

        content = response.content if response.content else ""

        document = Document(
            name=doc_name,
            content=content,
            meta_data={"source": source_info},
        )

        if self.chunk:
            return await self.achunk_document(document)
        return [document]
