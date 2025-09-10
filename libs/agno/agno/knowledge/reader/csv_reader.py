import asyncio
import csv
import io
from pathlib import Path
from typing import IO, Any, List, Optional, Union
from uuid import uuid4

try:
    import aiofiles
except ImportError:
    raise ImportError("`aiofiles` not installed. Please install it with `pip install aiofiles`")

try:
    import chardet
except ImportError:
    raise ImportError("`chardet` not installed. Please install it with `pip install chardet`")

from agno.knowledge.chunking.row import RowChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.utils.log import logger


class CSVReader(Reader):
    """Reader for CSV files"""

    def __init__(self, chunking_strategy: Optional[ChunkingStrategy] = RowChunking(), **kwargs):
        super().__init__(chunking_strategy=chunking_strategy, **kwargs)

    @classmethod
    def get_supported_chunking_strategies(self) -> List[ChunkingStrategyType]:
        """Get the list of supported chunking strategies for CSV readers."""
        return [
            ChunkingStrategyType.ROW_CHUNKER,
            ChunkingStrategyType.FIXED_SIZE_CHUNKER,
            ChunkingStrategyType.AGENTIC_CHUNKER,
            ChunkingStrategyType.DOCUMENT_CHUNKER,
            ChunkingStrategyType.RECURSIVE_CHUNKER,
        ]

    @classmethod
    def get_supported_content_types(self) -> List[ContentType]:
        return [ContentType.CSV, ContentType.XLSX, ContentType.XLS]

    def _detect_encoding(self, file_path: Path) -> str:
        """
        Detect the encoding of a file using chardet.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Detected encoding or 'utf-8' as fallback
        """
        try:
            with open(file_path, 'rb') as f:
                raw_data = f.read(10000)  # Read first 10KB for detection
                result = chardet.detect(raw_data)
                encoding = result['encoding']
                confidence = result['confidence']
                
                # If confidence is high enough, use detected encoding
                if encoding and confidence > 0.7:
                    logger.info(f"Detected encoding: {encoding} with confidence: {confidence}")
                    return encoding
                else:
                    logger.info(f"Low confidence in detected encoding ({confidence}), falling back to utf-8")
                    return 'utf-8'
        except Exception as e:
            logger.warning(f"Error detecting encoding, falling back to utf-8: {e}")
            return 'utf-8'

    def _read_file_with_encoding(self, file_path: Path, encoding: str) -> str:
        """
        Read file content with specified encoding, with fallback to other encodings if needed.
        
        Args:
            file_path: Path to the file
            encoding: Encoding to try first
            
        Returns:
            File content as string
        """
        encodings_to_try = [encoding, 'utf-8', 'gbk', 'gb2312', 'latin-1']
        
        for enc in encodings_to_try:
            try:
                with open(file_path, 'r', encoding=enc) as f:
                    content = f.read()
                    if enc != encoding:
                        logger.info(f"Successfully read file with fallback encoding: {enc}")
                    return content
            except UnicodeDecodeError:
                logger.debug(f"Failed to read file with encoding: {enc}")
                continue
            except Exception as e:
                logger.warning(f"Error reading file with encoding {enc}: {e}")
                continue
        
        # If all encodings fail, try with errors='ignore'
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                logger.warning("Reading file with errors ignored, some characters may be lost")
                return f.read()
        except Exception as e:
            logger.error(f"Failed to read file even with error ignoring: {e}")
            raise

    def read(
        self, file: Union[Path, IO[Any]], delimiter: str = ",", quotechar: str = '"', name: Optional[str] = None
    ) -> List[Document]:
        try:
            if isinstance(file, Path):
                if not file.exists():
                    raise FileNotFoundError(f"Could not find file: {file}")
                logger.info(f"Reading: {file}")
                
                # Detect encoding
                detected_encoding = self._detect_encoding(file)
                file_content_str = self._read_file_with_encoding(file, detected_encoding)
                file_content = io.StringIO(file_content_str)
            else:
                logger.info(f"Reading retrieved file: {name or file.name}")
                file.seek(0)
                # Try to detect encoding for bytes content
                if hasattr(file, 'read'):
                    try:
                        # Get current position
                        pos = file.tell()
                        raw_data = file.read(10000)  # Read first 10KB for detection
                        file.seek(pos)  # Reset position
                        
                        result = chardet.detect(raw_data if isinstance(raw_data, bytes) else raw_data.encode() if isinstance(raw_data, str) else b'')
                        encoding = result['encoding'] or 'utf-8'
                        
                        file_content = io.StringIO(file.read().decode(encoding))
                    except Exception as e:
                        logger.warning(f"Error detecting encoding for bytes content, using utf-8: {e}")
                        file.seek(0)
                        file_content = io.StringIO(file.read().decode("utf-8"))  # type: ignore
                else:
                    file_content = io.StringIO(file.read().decode("utf-8"))  # type: ignore

            csv_name = name or (
                Path(file.name).stem
                if isinstance(file, Path)
                else (getattr(file, "name", "csv_file").split(".")[0] if hasattr(file, "name") else "csv_file")
            )
            csv_content = ""
            with file_content as csvfile:
                csv_reader = csv.reader(csvfile, delimiter=delimiter, quotechar=quotechar)
                for row in csv_reader:
                    csv_content += ", ".join(row) + "\n"

            documents = [
                Document(
                    name=csv_name,
                    id=str(uuid4()),
                    content=csv_content,
                )
            ]
            if self.chunk:
                chunked_documents = []
                for document in documents:
                    chunked_documents.extend(self.chunk_document(document))
                return chunked_documents
            return documents
        except Exception as e:
            logger.error(f"Error reading: {getattr(file, 'name', str(file)) if isinstance(file, IO) else file}: {e}")
            return []

    async def async_read(
        self,
        file: Union[Path, IO[Any]],
        delimiter: str = ",",
        quotechar: str = '"',
        page_size: int = 1000,
        name: Optional[str] = None,
    ) -> List[Document]:
        """
        Read a CSV file asynchronously, processing batches of rows concurrently.

        Args:
            file: Path or file-like object
            delimiter: CSV delimiter
            quotechar: CSV quote character
            page_size: Number of rows per page

        Returns:
            List of Document objects
        """
        try:
            if isinstance(file, Path):
                if not file.exists():
                    raise FileNotFoundError(f"Could not find file: {file}")
                logger.info(f"Reading async: {file}")
                
                # Detect encoding
                detected_encoding = self._detect_encoding(file)
                
                # Try to read with detected encoding
                encodings_to_try = [detected_encoding, 'utf-8', 'gbk', 'gb2312', 'latin-1']
                content = None
                used_encoding = None
                
                for enc in encodings_to_try:
                    try:
                        async with aiofiles.open(file, mode="r", encoding=enc, newline="") as file_content:
                            content = await file_content.read()
                            used_encoding = enc
                            if enc != detected_encoding:
                                logger.info(f"Successfully read file with fallback encoding: {enc}")
                            break
                    except UnicodeDecodeError:
                        logger.debug(f"Failed to read file with encoding: {enc}")
                        continue
                    except Exception as e:
                        logger.warning(f"Error reading file with encoding {enc}: {e}")
                        continue
                
                # If all encodings fail, try with errors='ignore'
                if content is None:
                    try:
                        async with aiofiles.open(file, mode="r", encoding='utf-8', errors='ignore', newline="") as file_content:
                            content = await file_content.read()
                            used_encoding = 'utf-8'
                            logger.warning("Reading file with errors ignored, some characters may be lost")
                    except Exception as e:
                        logger.error(f"Failed to read file even with error ignoring: {e}")
                        raise
                
                file_content_io = io.StringIO(content)
            else:
                logger.info(f"Reading retrieved file async: {file.name}")
                file.seek(0)
                # Try to detect encoding for bytes content
                try:
                    # For file-like objects, we'll assume UTF-8 for now in async context
                    file_content_io = io.StringIO(file.read().decode("utf-8"))  # type: ignore
                except Exception as e:
                    logger.warning(f"Error decoding file content, using utf-8 with error handling: {e}")
                    file.seek(0)
                    file_content_io = io.StringIO(file.read().decode("utf-8", errors="ignore"))  # type: ignore

            csv_name = name or (
                Path(file.name).stem
                if isinstance(file, Path)
                else (getattr(file, "name", "csv_file").split(".")[0] if hasattr(file, "name") else "csv_file")
            )

            file_content_io.seek(0)
            csv_reader = csv.reader(file_content_io, delimiter=delimiter, quotechar=quotechar)
            rows = list(csv_reader)
            total_rows = len(rows)

            if total_rows <= 10:
                csv_content = " ".join(", ".join(row) for row in rows)
                documents = [
                    Document(
                        name=csv_name,
                        id=str(uuid4()),
                        content=csv_content,
                    )
                ]
            else:
                pages = []
                for i in range(0, total_rows, page_size):
                    pages.append(rows[i : i + page_size])

                async def _process_page(page_number: int, page_rows: List[List[str]]) -> Document:
                    """Process a page of rows into a document"""
                    start_row = (page_number - 1) * page_size + 1
                    page_content = " ".join(", ".join(row) for row in page_rows)

                    return Document(
                        name=csv_name,
                        id=str(uuid4()),
                        meta_data={"page": page_number, "start_row": start_row, "rows": len(page_rows)},
                        content=page_content,
                    )

                documents = await asyncio.gather(
                    *[_process_page(page_number, page) for page_number, page in enumerate(pages, start=1)]
                )

            if self.chunk:
                documents = await self.chunk_documents_async(documents)

            return documents
        except Exception as e:
            logger.error(
                f"Error reading async: {getattr(file, 'name', str(file)) if isinstance(file, IO) else file}: {e}"
            )
            return []