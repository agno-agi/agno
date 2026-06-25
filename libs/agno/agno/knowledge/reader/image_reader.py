import asyncio
import imghdr
from enum import Enum
from pathlib import Path
from typing import IO, Any, List, Optional, Union
from uuid import uuid4

from agno.knowledge.chunking.strategy import ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.media import Image
from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import log_error, log_info, logger

try:
    import rapidocr_onnxruntime as rapidocr
except ImportError:
    raise ImportError(
        "The `rapidocr_onnxruntime` package is not installed. Please install it via `pip install rapidocr_onnxruntime`."
    )


class ImageProcessingMode(Enum):
    OCR = "ocr"
    VISION = "vision"


# Assuming this Enum is defined in agno.knowledge.types
class ContentType(Enum):
    PNG = "image/png"
    JPG = "image/jpeg"  # Note: Mapped to jpeg for consistency
    JPEG = "image/jpeg"
    WEBP = "image/webp"
    BMP = "image/bmp"

    # Helper to get the simple format string (e.g., 'png', 'jpeg')
    @property
    def simple_format(self) -> str:
        return self.value.split("/")[-1]


class ImageReader(Reader):
    def __init__(
        self,
        mode: ImageProcessingMode = ImageProcessingMode.OCR,
        vision_model: Optional[Model] = None,
        vision_prompt: str = "Describe this image in detail.",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.mode = mode
        self.vision_prompt = vision_prompt
        self.ocr_engine = None
        self.vision_model = vision_model

        if self.mode == ImageProcessingMode.OCR:
            try:
                self.ocr_engine = rapidocr.RapidOCR()
            except Exception as e:
                log_error(f"Failed to initialize RapidOCR engine. Error: {e}")
                raise
        elif self.mode == ImageProcessingMode.VISION:
            if not self.vision_model:
                raise ValueError("A 'vision_model' instance is required for VISION mode.")
            if not (hasattr(self.vision_model, "response") and hasattr(self.vision_model, "aresponse")):
                logger.warning(
                    "The provided vision_model may not support both sync and async methods ('response' and 'aresponse')."
                )
        else:
            raise ValueError(f"Unsupported mode: {mode}")

    @classmethod
    def get_supported_content_types(cls) -> List[ContentType]:
        return [ContentType.PNG, ContentType.JPG, ContentType.JPEG, ContentType.WEBP, ContentType.BMP]

    @classmethod
    def get_supported_chunking_strategies(cls) -> List[ChunkingStrategyType]:
        return [
            ChunkingStrategyType.DOCUMENT_CHUNKER,
            ChunkingStrategyType.FIXED_SIZE_CHUNKER,
            ChunkingStrategyType.RECURSIVE_CHUNKER,
            ChunkingStrategyType.SEMANTIC_CHUNKER,
            ChunkingStrategyType.AGENTIC_CHUNKER,
        ]

    def _create_documents_from_text(self, full_text: str, doc_name: str, source_info: str) -> List[Document]:
        if not full_text:
            logger.warning(f"No text/description generated for image: {doc_name}")
            return []

        documents = [
            Document(
                name=doc_name,
                id=str(uuid4()),
                content=full_text,
                meta_data={"source_file": source_info},
            )
        ]

        if self.chunk:
            return self._build_chunked_documents(documents)

        return documents

    def _build_chunked_documents(self, documents: List[Document]) -> List[Document]:
        chunked_documents: List[Document] = []
        for document in documents:
            chunked_documents.extend(self.chunk_document(document))
        return chunked_documents

    def _process_with_ocr(self, image_data: bytes) -> str:
        if not self.ocr_engine:
            raise RuntimeError("OCR engine is not initialized.")
        ocr_result, _ = self.ocr_engine(image_data)
        if not ocr_result:
            return ""
        return "\n".join([item[1] for item in ocr_result])

    def _process_with_vision(self, image_data: bytes, image_format: str) -> str:
        if not self.vision_model:
            raise RuntimeError("Vision model is not initialized.")

        image_obj = Image(content=image_data, format=image_format)
        messages = [Message(role="user", content=self.vision_prompt, images=[image_obj])]
        model_response = self.vision_model.response(messages=messages)
        return model_response.content or ""

    def _process_image(
        self, image_data: bytes, doc_name: str, source_info: str, image_format: Optional[str] = None
    ) -> List[Document]:
        full_text = ""
        if self.mode == ImageProcessingMode.OCR:
            full_text = self._process_with_ocr(image_data)
        elif self.mode == ImageProcessingMode.VISION:
            if not image_format:
                raise ValueError("Image format is required for VISION mode processing.")
            full_text = self._process_with_vision(image_data, image_format)

        return self._create_documents_from_text(full_text, doc_name, source_info)

    async def _aprocess_with_vision(self, image_data: bytes, image_format: str) -> str:
        if not self.vision_model:
            raise RuntimeError("Vision model is not initialized.")

        image_obj = Image(content=image_data, format=image_format)
        messages = [Message(role="user", content=self.vision_prompt, images=[image_obj])]
        model_response = await self.vision_model.aresponse(messages=messages)
        return model_response.content or ""

    async def _aprocess_image(
        self, image_data: bytes, doc_name: str, source_info: str, image_format: Optional[str] = None
    ) -> List[Document]:
        full_text = ""
        if self.mode == ImageProcessingMode.OCR:
            # OCR processing can be I/O bound, so running in a thread is good practice
            full_text = await asyncio.to_thread(self._process_with_ocr, image_data)
        elif self.mode == ImageProcessingMode.VISION:
            if not image_format:
                raise ValueError("Image format is required for async VISION mode processing.")
            full_text = await self._aprocess_with_vision(image_data, image_format)

        return self._create_documents_from_text(full_text, doc_name, source_info)

    def _validate_and_get_image_data(
        self, file: Union[str, Path, IO[Any]], name: Optional[str]
    ) -> tuple[bytes, str, str, str]:
        """
        Validates the file format and returns its data, name, source info, and simple format.
        Raises ValueError for unsupported formats or FileNotFoundError for missing files.
        Returns: (image_data, doc_name, source_info, image_format)
        """
        # Get a set of simple format strings like {'jpeg', 'png', ...}
        supported_formats = {ct.simple_format for ct in self.get_supported_content_types()}
        image_format = ""

        if isinstance(file, (str, Path)):
            path = Path(file)
            if not path.exists():
                raise FileNotFoundError(f"Could not find file: {path}")

            # Determine format from extension
            ext = path.suffix.lstrip(".").lower()
            image_format = "jpeg" if ext == "jpg" else ext

            if image_format not in supported_formats:
                raise ValueError(f"Unsupported file format: '.{ext}'. Supported formats are: {list(supported_formats)}")

            doc_name = name or path.name
            source_info = str(path)
            image_data = path.read_bytes()
        else:  # Handle file-like objects
            filename = getattr(file, "name", "image_stream")
            doc_name = name or filename
            source_info = doc_name
            file.seek(0)
            image_data = file.read()

            # Determine format from content
            fmt = imghdr.what(None, h=image_data)
            if not fmt:
                raise ValueError("Could not determine image format from stream content.")
            image_format = "jpeg" if fmt == "jpg" else fmt

            if image_format not in supported_formats:
                raise ValueError(
                    f"Unsupported image content type: '{image_format}'. Supported types are: {list(supported_formats)}"
                )

        return image_data, doc_name, source_info, image_format

    def read(self, file: Union[str, Path, IO[Any]], name: Optional[str] = None) -> List[Document]:
        if file is None:
            log_error("No image file provided")
            return []

        try:
            image_data, doc_name, source_info, image_format = self._validate_and_get_image_data(file, name)
            log_info(f"Reading image with {self.mode.value}: {source_info}")
            return self._process_image(image_data, doc_name, source_info, image_format)

        except (ValueError, FileNotFoundError) as e:
            log_error(str(e))
            return []
        except Exception as e:
            log_error(f"An unexpected error occurred while processing image {name or str(file)}: {e}")
            return []

    async def async_read(self, file: Union[str, Path, IO[Any]], name: Optional[str] = None) -> List[Document]:
        if file is None:
            log_error("No image file provided")
            return []

        try:
            # I/O validation is fast, so running it synchronously is acceptable.
            image_data, doc_name, source_info, image_format = self._validate_and_get_image_data(file, name)
            log_info(f"Asynchronously reading image with {self.mode.value}: {source_info}")
            return await self._aprocess_image(image_data, doc_name, source_info, image_format)

        except (ValueError, FileNotFoundError) as e:
            log_error(str(e))
            return []
        except Exception as e:
            log_error(f"An unexpected error occurred while processing image {name or str(file)}: {e}")
            return []
