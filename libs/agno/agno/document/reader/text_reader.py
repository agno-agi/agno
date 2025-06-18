import asyncio
import uuid
from pathlib import Path
from typing import IO, Any, List, Union

from agno.document.base import Document
from agno.document.reader.base import Reader
from agno.utils.log import log_info, logger


class TextReader(Reader):
    """Reader for Text files"""

    def read(self, file: Union[Path, IO[Any]]) -> List[Document]:
        try:
            if isinstance(file, Path):
                if not file.exists():
                    raise FileNotFoundError(f"Could not find file: {file}")
                log_info(f"Reading: {file}")
                file_name = file.stem
                file_contents = file.read_text("utf-8")
            else:
                log_info(f"Reading uploaded file: {file.name}")
                file_name = file.name.split(".")[0]
                file.seek(0)
                file_contents = file.read().decode("utf-8")

            documents = [
                Document(
                    name=file_name,
                    id=str({uuid.uuid4()}),
                    content=file_contents,
                )
            ]
            if self.chunk:
                chunked_documents = []
                for document in documents:
                    chunked_documents.extend(self.chunk_document(document))
                return chunked_documents
            return documents
        except Exception as e:
            logger.error(f"Error reading: {file}: {e}")
            return []

    async def async_read(self, file: Union[Path, IO[Any]]) -> List[Document]:
        try:
            if isinstance(file, Path):
                if not file.exists():
                    raise FileNotFoundError(f"Could not find file: {file}")

                log_info(f"Reading asynchronously: {file}")
                file_name = file.stem

                try:
                    import aiofiles

                    async with aiofiles.open(file, "r", encoding="utf-8") as f:
                        file_contents = await f.read()
                except ImportError:
                    logger.warning("aiofiles not installed, using synchronous file I/O")
                    file_contents = file.read_text("utf-8")
            else:
                log_info(f"Reading uploaded file asynchronously: {file.name}")
                file_name = file.name.split(".")[0]
                file.seek(0)
                file_contents = file.read().decode("utf-8")

            document = Document(
                name=file_name,
                id=str({uuid.uuid4()}),
                content=file_contents,
            )

            if self.chunk:
                return await self._async_chunk_document(document)
            return [document]
        except Exception as e:
            logger.error(f"Error reading asynchronously: {file}: {e}")
            return []

    async def _async_chunk_document(self, document: Document) -> List[Document]:
        if not self.chunk or not document:
            return [document]

        async def process_chunk(chunk_doc: Document) -> Document:
            return chunk_doc

        chunked_documents = self.chunk_document(document)

        if not chunked_documents:
            return [document]

        tasks = [process_chunk(chunk_doc) for chunk_doc in chunked_documents]
        return await asyncio.gather(*tasks)
