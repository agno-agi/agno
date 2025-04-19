from typing import AsyncIterator, Iterator, List, Union

from agno.document import Document
from agno.document.reader.pdf_reader import PDFUrlImageReader, PDFUrlReader
from agno.knowledge.agent import AgentKnowledge
from agno.utils.log import logger
from agno.utils.log import log_info, log_debug
from typing import Optional, Any, Dict



class PDFUrlKnowledgeBase(AgentKnowledge):
    urls: List[str] = []
    reader: Union[PDFUrlReader, PDFUrlImageReader] = PDFUrlReader()

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over PDF urls and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            Iterator[List[Document]]: Iterator yielding list of documents
        """

        for url in self.urls:
            if url.endswith(".pdf"):
                yield self.reader.read(url=url)
            else:
                logger.error(f"Unsupported URL: {url}")

    @property
    async def async_document_lists(self) -> AsyncIterator[List[Document]]:
        """Iterate over PDF urls and yield lists of documents.
        Each object yielded by the iterator is a list of documents.
        Returns:
            Iterator[List[Document]]: Iterator yielding list of documents
        """

        for url in self.urls:
            if url.endswith(".pdf"):
                yield await self.reader.async_read(url=url)
            else:
                logger.error(f"Unsupported URL: {url}")
                
    def load_url(
        self,
        url: str,
        metadata: Optional[Dict[str, Any]] = None,
        recreate: bool = False,
        upsert: bool = False,
        skip_existing: bool = True,
    ) -> None:
        """Load documents from a single URL with specific metadata into the vector DB.

        Args:
            url (str): URL of the PDF to load.
            metadata (Optional[Dict[str, Any]]): Metadata to associate with documents from this URL.
                                                This will be merged into the 'meta_data' field of each document.
            recreate (bool): If True, drops and recreates the collection before loading. Defaults to False.
            upsert (bool): If True, upserts documents (insert or update). Requires vector_db support. Defaults to False.
            skip_existing (bool): If True and not upserting, skips documents that already exist based on content hash. Defaults to True.
        """
        if not url.endswith(".pdf"):
            logger.error(f"Unsupported URL provided to load_url: {url}")
            return

        if self.vector_db is None:
            logger.warning("Cannot load URL: No vector db provided.")
            return

        # Initialize reader if it hasn't been (e.g., if urls list was initially empty)
        if self.reader is None:
            logger.debug("Initializing default PDFUrlReader in load_url.")
            self.reader = PDFUrlReader()
            # Apply chunking strategy from the knowledge base config
            self.update_reader()
        elif not hasattr(self.reader, "read"):
            logger.error(
                "Knowledge base reader is not configured correctly or lacks a 'read' method."
            )
            return

        # Ensure collection exists or recreate if requested
        if recreate:
            log_info(
                f"Recreating collection '{self.vector_db.collection}' before loading {url}."
            )
            self.vector_db.drop()

        if not self.vector_db.exists():
            log_info(
                f"Collection '{self.vector_db.collection}' does not exist. Creating.")
            self.vector_db.create()

        # Read documents from the URL
        log_info(f"Reading documents from URL: {url}")
        try:
            documents = self.reader.read(url=url)
            if not documents:
                logger.warning(f"No documents were read from URL: {url}")
                return
        except Exception as e:
            logger.exception(f"Failed to read documents from URL {url}: {e}")
            return

        log_info(
            f"Loading {len(documents)} documents from {url} with metadata: {metadata}")

        # Decide loading strategy: upsert or insert (with optional skip)
        if upsert and self.vector_db.upsert_available():
            log_debug(f"Upserting {len(documents)} documents.")
            # Pass metadata directly; the vector_db's insert/upsert handles merging it
            self.vector_db.upsert(documents=documents, filters=metadata)
        else:
            documents_to_insert = documents
            if skip_existing:
                log_debug("Filtering out existing documents before insertion.")
                # Use set for O(1) lookups
                seen_content = set()
                original_count = len(documents_to_insert)
                documents_to_insert_filtered = []
                for doc in documents_to_insert:
                    # Check hash and existence in DB
                    content_hash = (
                        doc.content
                    )  # Assuming doc.content is reliable hash key or use md5
                    if content_hash not in seen_content and not self.vector_db.doc_exists(
                        doc
                    ):
                        seen_content.add(content_hash)
                        documents_to_insert_filtered.append(doc)
                    else:
                        log_debug(
                            f"Skipping existing document: {doc.name} (or duplicate content)"
                        )
                documents_to_insert = documents_to_insert_filtered
                if len(documents_to_insert) < original_count:
                    log_info(
                        f"Skipped {original_count - len(documents_to_insert)} existing/duplicate documents."
                    )

            if documents_to_insert:
                log_debug(f"Inserting {len(documents_to_insert)} new documents.")
                # Pass metadata directly
                self.vector_db.insert(
                    documents=documents_to_insert, filters=metadata)
            else:
                log_info("No new documents to insert after filtering.")

        log_info(f"Finished loading documents from {url}.")
