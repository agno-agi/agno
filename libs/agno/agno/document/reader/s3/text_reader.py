import asyncio
from pathlib import Path
from typing import List

from agno.document.base import Document
from agno.document.reader.base import Reader
from agno.utils.log import log_debug, log_info, logger

try:
    from agno.aws.resource.s3.object import S3Object  # type: ignore
except (ModuleNotFoundError, ImportError):
    raise ImportError("`agno-aws` not installed. Please install using `pip install agno-aws`")

try:
    from agno.document.reader.universal_reader import UniversalDocumentReader
except ImportError:
    raise ImportError("`universal_reader` not available. Check agno installation.")


class S3TextReader(Reader):
    """Reader for text files on S3"""

    def read(self, s3_object: S3Object) -> List[Document]:
        try:
            log_info(f"Reading: {s3_object.uri}")

            obj_name = s3_object.name.split("/")[-1]
            temporary_file = Path("storage").joinpath(obj_name)
            s3_object.download(temporary_file)

            log_info(f"Parsing: {temporary_file}")
            doc_name = s3_object.name.split("/")[-1].split(".")[0].replace("/", "_").replace(" ", "_")

            reader = UniversalDocumentReader()
            extracted_docs = reader.read(temporary_file)

            if extracted_docs:
                content = "\n".join([doc.content for doc in extracted_docs])
                documents = [
                    Document(
                        name=doc_name,
                        id=doc_name,
                        content=content,
                    )
                ]
            else:
                documents = [
                    Document(
                        name=doc_name,
                        id=doc_name,
                        content="",
                    )
                ]
            if self.chunk:
                chunked_documents = []
                for document in documents:
                    chunked_documents.extend(self.chunk_document(document))
                return chunked_documents

            log_debug(f"Deleting: {temporary_file}")
            temporary_file.unlink()
            return documents
        except Exception as e:
            logger.error(f"Error reading: {s3_object.uri}: {e}")
        return []

    async def async_read(self, s3_object: S3Object) -> List[Document]:
        """Asynchronously read text files from S3 by running the synchronous read operation in a thread.

        Args:
            s3_object (S3Object): The S3 object to read

        Returns:
            List[Document]: List of documents from the text file
        """
        return await asyncio.to_thread(self.read, s3_object)
