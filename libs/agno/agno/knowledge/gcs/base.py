from typing import AsyncIterator, Iterator, List, Optional

from google.cloud import storage

from agno.document import Document
from agno.knowledge.agent import AgentKnowledge


class GCSKnowledgeBase(AgentKnowledge):
    bucket: Optional[storage.Bucket] = None
    bucket_name: Optional[str] = None
    blob_name: Optional[str] = None
    prefix: Optional[str] = None

    @property
    def gcs_blobs(self) -> List[storage.Blob]:
        if self.bucket is None and self.bucket_name is None:
            raise ValueError("No bucket or bucket_name provided")
        if self.bucket is not None and self.bucket_name is not None:
            raise ValueError("Provide either bucket or bucket_name")
        if self.bucket_name is not None:
            client = storage.Client()
            self.bucket = client.bucket(self.bucket_name)
        blobs_to_read = []
        if self.blob_name is not None:
            blobs_to_read.append(self.bucket.blob(self.blob_name))  # type: ignore
        elif self.prefix is not None:
            blobs_to_read.extend(self.bucket.list_blobs(prefix=self.prefix))  # type: ignore
        else:
            blobs_to_read.extend(self.bucket.list_blobs())  # type: ignore
        return list(blobs_to_read)

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        raise NotImplementedError

    @property
    def async_document_lists(self) -> AsyncIterator[List[Document]]:
        raise NotImplementedError
