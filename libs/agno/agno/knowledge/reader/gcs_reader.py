import asyncio
from io import BytesIO
from typing import List, Optional
from uuid import uuid4

from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.utils.log import log_info

try:
    from google.cloud import storage
except ImportError:
    raise ImportError("`google-cloud-storage` not installed. Please install it via `pip install google-cloud-storage`.")

try:
    from pypdf import PdfReader as DocumentReader
except ImportError:
    raise ImportError("`pypdf` not installed. Please install it via `pip install pypdf`.")


class GCSReader(Reader):
    def read(self, name: Optional[str], blob: storage.Blob) -> List[Document]:
        log_info(f"Reading: gs://{blob.bucket.name}/{blob.name}")
        data = blob.download_as_bytes()
        doc_name = blob.name.split("/")[-1].split(".")[0].replace("/", "_").replace(" ", "_")
        if name is not None:
            doc_name = name
        doc_reader = DocumentReader(BytesIO(data))
        documents = [
            Document(
                name=doc_name,
                id=str(uuid4()),
                meta_data={"page": page_number},
                content=page.extract_text(),
            )
            for page_number, page in enumerate(doc_reader.pages, start=1)
        ]
        if self.chunk:
            chunked_documents = []
            for document in documents:
                chunked_documents.extend(self.chunk_document(document))
            return chunked_documents
        return documents

    async def async_read(self, name: Optional[str], blob: storage.Blob) -> List[Document]:
        return await asyncio.to_thread(self.read, name, blob)
