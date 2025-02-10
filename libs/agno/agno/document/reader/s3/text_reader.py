from pathlib import Path
from typing import List

from agno.document.base import Document
from agno.document.reader.base import Reader
from agno.utils.log import logger

try:
    from agno.aws.resource.s3.object import S3Object  # type: ignore
except (ModuleNotFoundError, ImportError):
    raise ImportError("`agno-aws` not installed. Please install using `pip install agno-aws`")

try:
    import textract  # noqa: F401
except ImportError:
    raise ImportError("`textract` not installed. Please install it via `pip install textract`.")


class S3TextReader(Reader):
    """Reader for text files on S3"""

    def read(self, s3_object: S3Object) -> List[Document]:
        try:
            logger.info(f"Reading: {s3_object.uri}")

            obj_name = s3_object.name.split("/")[-1]
            temporary_file = Path("storage").joinpath(obj_name)
            s3_object.download(temporary_file)

            logger.info(f"Parsing: {temporary_file}")
            doc_name = s3_object.name.split("/")[-1].split(".")[0].replace("/", "_").replace(" ", "_")
            doc_content = textract.process(temporary_file)
            documents = [
                Document(
                    name=doc_name,
                    id=doc_name,
                    content=doc_content.decode("utf-8"),
                )
            ]
            if self.chunk:
                chunked_documents = []
                for document in documents:
                    chunked_documents.extend(self.chunk_document(document))
                return chunked_documents

            logger.debug(f"Deleting: {temporary_file}")
            temporary_file.unlink()
            return documents
        except Exception as e:
            logger.error(f"Error reading: {s3_object.uri}: {e}")
        return []
