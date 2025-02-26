from pathlib import Path
from typing import IO, Any, List, Union

from agno.document.base import Document
from agno.document.reader.base import Reader
from agno.utils.log import logger


class TextReader(Reader):
    """Reader for Text files"""

    def read(self, file: Union[Path, IO[Any]]) -> List[Document]:
        try:
            if isinstance(file, Path):
                if not file.exists():
                    raise FileNotFoundError(f"Could not find file: {file}")
                logger.info(f"Reading: {file}")
                file_name = file.stem
                file_contents = file.read_text("utf-8")
            else:
                logger.info(f"Reading uploaded file: {file.name}")
                file_name = file.name.split(".")[0]
                file.seek(0)
                file_contents = file.read().decode("utf-8")

            documents = [
                Document(
                    name=file_name,
                    id=file_name,
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
