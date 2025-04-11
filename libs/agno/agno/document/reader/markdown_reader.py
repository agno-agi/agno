import io
from pathlib import Path
from typing import List, Union

from agno.document.base import Document
from agno.document.reader.base import Reader
from agno.utils.log import logger


class MarkdownReader(Reader):
    """Reader for Markdown files"""

    def read(self, file: Union[Path, io.BytesIO]) -> List[Document]:
        try:
            if isinstance(file, Path):
                logger.info(f"Reading: {file}")
                with open(file, "r", encoding="utf-8") as f:
                    content = f.read()
                doc_name = file.stem
            else:
                logger.info(f"Reading uploaded file: {file.name}")
                content = file.read().decode("utf-8")
                doc_name = file.name.split(".")[0]

            documents = [
                Document(
                    name=doc_name,
                    id=doc_name,
                    content=content,
                )
            ]
            if self.chunk:
                chunked_documents = []
                for document in documents:
                    chunked_documents.extend(self.chunk_document(document))
                return chunked_documents
            return documents
        except Exception as e:
            logger.error(f"Error reading file: {e}")
            return []
