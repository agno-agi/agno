from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

from agno.document import Document
from agno.document.reader.gcs.pdf_reader import GCSPDFReader
from agno.knowledge.gcs.base import GCSKnowledgeBase
from agno.utils.log import log_debug, log_info


class GCSPDFKnowledgeBase(GCSKnowledgeBase):
    reader: GCSPDFReader = GCSPDFReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        for blob in self.gcs_blobs:
            if blob.name.endswith(".pdf"):
                yield self.reader.read(blob=blob)

    @property
    async def async_document_lists(self) -> AsyncIterator[List[Document]]:
        for blob in self.gcs_blobs:
            if blob.name.endswith(".pdf"):
                yield await self.reader.async_read(blob=blob)

    def load(
        self,
        recreate: bool = False,
        upsert: bool = False,
        skip_existing: bool = True,
    ) -> None:
        """Load the knowledge base to the vector db
        Args:
            recreate (bool): If True, recreates the collection in the vector db. Defaults to False.
            upsert (bool): If True, upserts documents to the vector db. Defaults to False.
            skip_existing (bool): If True, skips documents which already exist in the vector db when inserting. Defaults to True.
        """
        self._load_init(recreate, upsert)
        if self.vector_db is None:
            return

        log_info("Loading knowledge base")
        num_documents = 0
        for document_list in self.document_lists:
            documents_to_load = document_list

            # Track metadata for filtering capabilities and collect metadata for filters
            filters_metadata: Optional[Dict[str, Any]] = None
            for doc in document_list:
                if doc.meta_data:
                    self._track_metadata_structure(doc.meta_data)
                    # Use the first non-None metadata for filters
                    if filters_metadata is None:
                        filters_metadata = doc.meta_data

            # Skip processing if no documents in this batch
            if not documents_to_load:
                log_debug("Skipping empty document batch")
                continue

            # Upsert documents if upsert is True and vector db supports upsert
            if upsert and self.vector_db.upsert_available():
                self.vector_db.upsert(documents=documents_to_load, filters=filters_metadata)
            # Insert documents
            else:
                # Filter out documents which already exist in the vector db
                if skip_existing:
                    log_debug("Filtering out existing documents before insertion.")
                    documents_to_load = self.filter_existing_documents(document_list)

                if documents_to_load:
                    self.vector_db.insert(documents=documents_to_load, filters=filters_metadata)

            num_documents += len(documents_to_load)
        log_info(f"Added {num_documents} documents to knowledge base")

    async def aload(
        self,
        recreate: bool = False,
        upsert: bool = False,
        skip_existing: bool = True,
    ) -> None:
        """Load the knowledge base to the vector db asynchronously
        Args:
            recreate (bool): If True, recreates the collection in the vector db. Defaults to False.
            upsert (bool): If True, upserts documents to the vector db. Defaults to False.
            skip_existing (bool): If True, skips documents which already exist in the vector db when inserting. Defaults to True.
        """
        await self._aload_init(recreate, upsert)
        if self.vector_db is None:
            return

        log_info("Loading knowledge base")
        num_documents = 0
        document_iterator = self.async_document_lists
        async for document_list in document_iterator:  # type: ignore
            documents_to_load = document_list

            # Track metadata for filtering capabilities and collect metadata for filters
            filters_metadata: Optional[Dict[str, Any]] = None
            for doc in document_list:
                if doc.meta_data:
                    self._track_metadata_structure(doc.meta_data)
                    # Use the first non-None metadata for filters
                    if filters_metadata is None:
                        filters_metadata = doc.meta_data

            # Skip processing if no documents in this batch
            if not documents_to_load:
                log_debug("Skipping empty document batch")
                continue

            # Upsert documents if upsert is True and vector db supports upsert
            if upsert and self.vector_db.upsert_available():
                await self.vector_db.async_upsert(documents=documents_to_load, filters=filters_metadata)
            # Insert documents
            else:
                # Filter out documents which already exist in the vector db
                if skip_existing:
                    log_debug("Filtering out existing documents before insertion.")
                    documents_to_load = await self.async_filter_existing_documents(document_list)

                if documents_to_load:
                    await self.vector_db.async_insert(documents=documents_to_load, filters=filters_metadata)

            num_documents += len(documents_to_load)
        log_info(f"Added {num_documents} documents to knowledge base")
