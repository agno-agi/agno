import base64
import uuid
from pathlib import Path
from typing import IO, Any, List, Optional, Union

from agno.knowledge.chunking.strategy import ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.utils.log import log_debug, log_error


class ImageReader(Reader):
    """Reader for image files"""

    def __init__(
        self,
        name: str = "Image Reader",
        description: str = "Reader for image files",
        chunk: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(name=name, description=description, chunk=chunk, **kwargs)

    @classmethod
    def get_supported_content_types(cls) -> List[ContentType]:
        return [
            ContentType.IMAGE_PNG,
            ContentType.IMAGE_JPEG,
            ContentType.IMAGE_JPG,
            ContentType.IMAGE_TIFF,
            ContentType.IMAGE_TIF,
            ContentType.IMAGE_BMP,
        ]

    @classmethod
    def get_supported_chunking_strategies(cls) -> List[ChunkingStrategyType]:
        return []

    def read(self, file: Union[Path, IO[Any]], name: Optional[str] = None) -> List[Document]:
        try:
            if isinstance(file, Path):
                if not file.exists():
                    raise FileNotFoundError(f"Could not find file: {file}")
                log_debug(f"Reading image: {file}")
                file_name = name or file.stem
                file_bytes = file.read_bytes()
                file_suffix = file.suffix.lower()
            else:
                log_debug(f"Reading uploaded image: {getattr(file, 'name', 'BytesIO')}")
                file_name = name or getattr(file, "name", "image_file").split(".")[0]
                file.seek(0)
                file_bytes = file.read()
                file_suffix = ""

            content = base64.b64encode(file_bytes).decode("utf-8")

            return [
                Document(
                    name=file_name,
                    id=str(uuid.uuid4()),
                    content=content,
                    meta_data={
                        "image_format": file_suffix,
                        "image_size_bytes": len(file_bytes),
                        "content_type": "image",
                    },
                )
            ]
        except Exception as e:
            log_error(f"Error reading image: {file}: {str(e)}")
            return []

    async def async_read(self, file: Union[Path, IO[Any]], name: Optional[str] = None) -> List[Document]:
        return self.read(file=file, name=name)
