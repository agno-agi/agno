import asyncio
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Set, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agno.document import Document
from agno.document.chunking.fixed import FixedSizeChunking
from agno.document.chunking.strategy import ChunkingStrategy
from agno.document.reader.base import Reader
from agno.utils.log import log_debug, log_info, logger
from agno.vectordb import VectorDb


class AgentKnowledge(BaseModel):
    """Base class for Agent knowledge"""

    # Reader for reading documents from files, pdfs, urls, etc.
    reader: Optional[Reader] = None
    # Vector db for storing knowledge
    vector_db: Optional[VectorDb] = None
    # Number of relevant documents to return on search
    num_documents: int = 5
    # Number of documents to optimize the vector db on
    optimize_on: Optional[int] = 1000

    chunking_strategy: ChunkingStrategy = Field(default_factory=FixedSizeChunking)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    valid_metadata_filters: Set[str] = None  # type: ignore

    @model_validator(mode="after")
    def update_reader(self) -> "AgentKnowledge":
        if self.reader is not None and self.reader.chunking_strategy is None:
            self.reader.chunking_strategy = self.chunking_strategy
        return self

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterator that yields lists of documents in the knowledge base
        Each object yielded by the iterator is a list of documents.
        """
        raise NotImplementedError

    @property
    def async_document_lists(self) -> AsyncIterator[List[Document]]:
        """Iterator that yields lists of documents in the knowledge base
        Each object yielded by the iterator is a list of documents.
        """
        raise NotImplementedError

    def search(
        self, query: str, num_documents: Optional[int] = None, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Returns relevant documents matching a query"""
        try:
            if self.vector_db is None:
                logger.warning("No vector db provided")
                return []

            _num_documents = num_documents or self.num_documents
            log_debug(f"Getting {_num_documents} relevant documents for query: {query}")
            return self.vector_db.search(query=query, limit=_num_documents, filters=filters)
        except Exception as e:
            logger.error(f"Error searching for documents: {e}")
            return []

    async def async_search(
        self, query: str, num_documents: Optional[int] = None, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Returns relevant documents matching a query"""
        try:
            if self.vector_db is None:
                logger.warning("No vector db provided")
                return []

            _num_documents = num_documents or self.num_documents
            log_debug(f"Getting {_num_documents} relevant documents for query: {query}")
            try:
                return await self.vector_db.async_search(query=query, limit=_num_documents, filters=filters)
            except NotImplementedError:
                logger.info("Vector db does not support async search")
                return self.search(query=query, num_documents=_num_documents, filters=filters)
        except Exception as e:
            logger.error(f"Error searching for documents: {e}")
            return []

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
        if self.vector_db is None:
            logger.warning("No vector db provided")
            return

        if recreate:
            log_info("Dropping collection")
            self.vector_db.drop()

        if not self.vector_db.exists():
            log_info("Creating collection")
            self.vector_db.create()

        log_info("Loading knowledge base")
        num_documents = 0
        for document_list in self.document_lists:
            documents_to_load = document_list

            # Track metadata for filtering capabilities
            for doc in document_list:
                if doc.meta_data:
                    self._track_metadata_structure(doc.meta_data)

            # Upsert documents if upsert is True and vector db supports upsert
            if upsert and self.vector_db.upsert_available():
                self.vector_db.upsert(documents=document_list, filters=doc.meta_data)
            # Insert documents
            else:
                # Filter out documents which already exist in the vector db
                if skip_existing:
                    log_debug("Filtering out existing documents before insertion.")
                    documents_to_load = self.filter_existing_documents(document_list)

                if documents_to_load:
                    self.vector_db.insert(documents=documents_to_load, filters=doc.meta_data)

            num_documents += len(documents_to_load)
            log_info(f"Added {len(documents_to_load)} documents to knowledge base")

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

        if self.vector_db is None:
            logger.warning("No vector db provided")
            return

        if recreate:
            log_info("Dropping collection")
            await self.vector_db.async_drop()

        if not await self.vector_db.async_exists():
            log_info("Creating collection")
            await self.vector_db.async_create()

        log_info("Loading knowledge base")
        num_documents = 0
        async for document_list in self.async_document_lists:
            # Track metadata for filtering capabilities
            for doc in document_list:
                if doc.meta_data:
                    self._track_metadata_structure(doc.meta_data)

            # Upsert documents if upsert is True and vector db supports upsert
            if upsert and self.vector_db.upsert_available():
                await self.vector_db.async_upsert(documents=document_list, filters=doc.meta_data)
            # Insert documents
            else:
                # Filter out documents which already exist in the vector db
                documents_to_load = document_list
                if skip_existing:
                    log_debug("Filtering out existing documents before insertion.")
                    documents_to_load = self.filter_existing_documents(document_list)

                if documents_to_load:
                    await self.vector_db.async_insert(documents=documents_to_load, filters=doc.meta_data)

            num_documents += len(documents_to_load)
            log_info(f"Added {len(documents_to_load)} documents to knowledge base")

    def load_documents(
        self,
        documents: List[Document],
        upsert: bool = False,
        skip_existing: bool = True,
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Load documents to the knowledge base

        Args:
            documents (List[Document]): List of documents to load
            upsert (bool): If True, upserts documents to the vector db. Defaults to False.
            skip_existing (bool): If True, skips documents which already exist in the vector db when inserting. Defaults to True.
            filters (Optional[Dict[str, Any]]): Filters to add to each row that can be used to limit results during querying. Defaults to None.
        """

        log_info("Loading knowledge base")
        if self.vector_db is None:
            logger.warning("No vector db provided")
            return

        log_debug("Creating collection")
        self.vector_db.create()

        # Upsert documents if upsert is True
        if upsert and self.vector_db.upsert_available():
            self.vector_db.upsert(documents=documents, filters=filters)
            log_info(f"Loaded {len(documents)} documents to knowledge base")
        else:
            # Filter out documents which already exist in the vector db
            documents_to_load = (
                [document for document in documents if not self.vector_db.doc_exists(document)]
                if skip_existing
                else documents
            )

            # Insert documents
            if len(documents_to_load) > 0:
                self.vector_db.insert(documents=documents_to_load, filters=filters)
                log_info(f"Loaded {len(documents_to_load)} documents to knowledge base")
            else:
                log_info("No new documents to load")

    async def async_load_documents(
        self,
        documents: List[Document],
        upsert: bool = False,
        skip_existing: bool = True,
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Load documents to the knowledge base

        Args:
            documents (List[Document]): List of documents to load
            upsert (bool): If True, upserts documents to the vector db. Defaults to False.
            skip_existing (bool): If True, skips documents which already exist in the vector db when inserting. Defaults to True.
            filters (Optional[Dict[str, Any]]): Filters to add to each row that can be used to limit results during querying. Defaults to None.
        """
        log_info("Loading knowledge base")
        if self.vector_db is None:
            logger.warning("No vector db provided")
            return

        log_debug("Creating collection")
        try:
            await self.vector_db.async_create()
        except NotImplementedError:
            logger.warning("Vector db does not support async create")
            self.vector_db.create()

        # Upsert documents if upsert is True
        if upsert and self.vector_db.upsert_available():
            try:
                await self.vector_db.async_upsert(documents=documents, filters=filters)
            except NotImplementedError:
                logger.warning("Vector db does not support async upsert")
                self.vector_db.upsert(documents=documents, filters=filters)
            log_info(f"Loaded {len(documents)} documents to knowledge base")
        else:
            # Filter out documents which already exist in the vector db
            if skip_existing:
                try:
                    # Parallelize existence checks using asyncio.gather
                    existence_checks = await asyncio.gather(
                        *[self.vector_db.async_doc_exists(document) for document in documents], return_exceptions=True
                    )

                    documents_to_load = [
                        doc
                        for doc, exists in zip(documents, existence_checks)
                        if not (isinstance(exists, bool) and exists)
                    ]
                except NotImplementedError:
                    logger.warning("Vector db does not support async doc_exists")
                    documents_to_load = [document for document in documents if not self.vector_db.doc_exists(document)]
            else:
                documents_to_load = documents

            # Insert documents
            if len(documents_to_load) > 0:
                try:
                    await self.vector_db.async_insert(documents=documents_to_load, filters=filters)
                except NotImplementedError:
                    logger.warning("Vector db does not support async insert")
                    self.vector_db.insert(documents=documents_to_load, filters=filters)
                log_info(f"Loaded {len(documents_to_load)} documents to knowledge base")
            else:
                log_info("No new documents to load")

    def add_document_to_knowledge_base(
        self,
        document: Document,
        upsert: bool = False,
        skip_existing: bool = True,
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Load a document to the knowledge base

        Args:
            document (Document): Document to load
            upsert (bool): If True, upserts documents to the vector db. Defaults to False.
            skip_existing (bool): If True, skips documents which already exist in the vector db. Defaults to True.
            filters (Optional[Dict[str, Any]]): Filters to add to each row that can be used to limit results during querying. Defaults to None.
        """
        self.load_documents(documents=[document], upsert=upsert, skip_existing=skip_existing, filters=filters)

    async def async_load_document(
        self,
        document: Document,
        upsert: bool = False,
        skip_existing: bool = True,
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Load a document to the knowledge base

        Args:
            document (Document): Document to load
            upsert (bool): If True, upserts documents to the vector db. Defaults to False.
            skip_existing (bool): If True, skips documents which already exist in the vector db. Defaults to True.
            filters (Optional[Dict[str, Any]]): Filters to add to each row that can be used to limit results during querying. Defaults to None.
        """
        await self.async_load_documents(
            documents=[document], upsert=upsert, skip_existing=skip_existing, filters=filters
        )

    def load_dict(
        self,
        document: Dict[str, Any],
        upsert: bool = False,
        skip_existing: bool = True,
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Load a dictionary representation of a document to the knowledge base

        Args:
            document (Dict[str, Any]): Dictionary representation of a document
            upsert (bool): If True, upserts documents to the vector db. Defaults to False.
            skip_existing (bool): If True, skips documents which already exist in the vector db. Defaults to True.
            filters (Optional[Dict[str, Any]]): Filters to add to each row that can be used to limit results during querying. Defaults to None.
        """
        self.load_documents(
            documents=[Document.from_dict(document)], upsert=upsert, skip_existing=skip_existing, filters=filters
        )

    def load_json(
        self, document: str, upsert: bool = False, skip_existing: bool = True, filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Load a json representation of a document to the knowledge base

        Args:
            document (str): Json representation of a document
            upsert (bool): If True, upserts documents to the vector db. Defaults to False.
            skip_existing (bool): If True, skips documents which already exist in the vector db. Defaults to True.
            filters (Optional[Dict[str, Any]]): Filters to add to each row that can be used to limit results during querying. Defaults to None.
        """
        self.load_documents(
            documents=[Document.from_json(document)], upsert=upsert, skip_existing=skip_existing, filters=filters
        )

    def load_text(
        self, text: str, upsert: bool = False, skip_existing: bool = True, filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Load a text to the knowledge base

        Args:
            text (str): Text to load to the knowledge base
            upsert (bool): If True, upserts documents to the vector db. Defaults to False.
            skip_existing (bool): If True, skips documents which already exist in the vector db. Defaults to True.
            filters (Optional[Dict[str, Any]]): Filters to add to each row that can be used to limit results during querying. Defaults to None.
        """
        self.load_documents(
            documents=[Document(content=text)], upsert=upsert, skip_existing=skip_existing, filters=filters
        )

    def exists(self) -> bool:
        """Returns True if the knowledge base exists"""
        if self.vector_db is None:
            logger.warning("No vector db provided")
            return False
        return self.vector_db.exists()

    def delete(self) -> bool:
        """Clear the knowledge base"""
        if self.vector_db is None:
            logger.warning("No vector db available")
            return True

        return self.vector_db.delete()

    def filter_existing_documents(self, documents: List[Document]) -> List[Document]:
        """Filter out documents that already exist in the vector database.

        This helper method is used across various knowledge base implementations
        to avoid inserting duplicate documents.

        Args:
            documents (List[Document]): List of documents to filter

        Returns:
            List[Document]: Filtered list of documents that don't exist in the database
        """
        from agno.utils.log import log_debug, log_info

        if not self.vector_db:
            log_debug("No vector database configured, skipping document filtering")
            return documents

        # Use set for O(1) lookups
        seen_content = set()
        original_count = len(documents)
        filtered_documents = []

        for doc in documents:
            # Check hash and existence in DB
            content_hash = doc.content  # Assuming doc.content is reliable hash key
            if content_hash not in seen_content and not self.vector_db.doc_exists(doc):
                seen_content.add(content_hash)
                filtered_documents.append(doc)
            else:
                log_debug(f"Skipping existing document: {doc.name} (or duplicate content)")

        if len(filtered_documents) < original_count:
            log_info(f"Skipped {original_count - len(filtered_documents)} existing/duplicate documents.")

        return filtered_documents

    def _track_metadata_structure(self, metadata: Optional[Dict[str, Any]]) -> None:
        """Track metadata structure to enable filter extraction from queries

        Args:
            metadata (Optional[Dict[str, Any]]): Metadata to track
        """
        if metadata:
            if self.valid_metadata_filters is None:
                self.valid_metadata_filters = set()

            # Extract top-level keys to track as potential filter fields
            for key in metadata.keys():
                self.valid_metadata_filters.add(key)

    def validate_filters(self, filters: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[str]]:
        if not filters:
            return {}, []

        valid_filters = {}
        invalid_keys = []

        # If no metadata filters tracked yet, all keys are considered invalid
        if self.valid_metadata_filters is None:
            invalid_keys = list(filters.keys())
            log_debug(f"No valid metadata filters tracked yet. All filter keys considered invalid: {invalid_keys}")
            return {}, invalid_keys

        for key, value in filters.items():
            # Handle both normal keys and prefixed keys like meta_data.key
            base_key = key.split(".")[-1] if "." in key else key
            if base_key in self.valid_metadata_filters or key in self.valid_metadata_filters:
                valid_filters[key] = value
            else:
                invalid_keys.append(key)
                log_debug(f"Invalid filter key: {key} - not present in knowledge base")

        return valid_filters, invalid_keys

    def initialize_valid_filters(self) -> None:
        """Refresh the valid metadata filters by scanning the documents in the knowledge base.
        This will be required majorly for the case when load/aload is commented out but we still need a way to call document_lists for updating the valid metadata filters.
        """
        if self.valid_metadata_filters is None:
            for doc_list in self.document_lists:
                for doc in doc_list:
                    if doc.meta_data:
                        self._track_metadata_structure(doc.meta_data)

    def prepare_load(
        self,
        file_path: Path,
        allowed_formats: Optional[List[str]],
        metadata: Optional[Dict[str, Any]] = None,
        recreate: bool = False,
        is_url: bool = False,
    ) -> bool:
        """Validate file path and prepare collection for loading.
        Args:
            file_path (Path): Path to validate
            allowed_formats (List[str]): List of allowed file formats
            metadata (Optional[Dict[str, Any]]): Metadata to track
            recreate (bool): Whether to recreate the collection
        Returns:
            bool: True if preparation succeeded, False otherwise
        """
        # 1. Validate file path
        if not is_url:
            if not file_path.exists():
                logger.error(f"File not found: {file_path}")
                return False

            if file_path.suffix not in allowed_formats:  # type: ignore
                logger.error(f"Unsupported file format: {file_path.suffix}")
                return False

        # 2. Track metadata
        if metadata:
            self._track_metadata_structure(metadata)

        # 3. Prepare vector DB
        if self.vector_db is None:
            logger.warning("Cannot load file: No vector db provided.")
            return False

        # Recreate collection if requested
        if recreate:
            # log_info(f"Recreating collection.")
            self.vector_db.drop()

        # Create collection if it doesn't exist
        if not self.vector_db.exists():
            # log_info(f"Collection does not exist. Creating.")
            self.vector_db.create()

        return True

    async def aprepare_load(
        self,
        file_path: Path,
        allowed_formats: List[str],
        metadata: Optional[Dict[str, Any]] = None,
        recreate: bool = False,
        is_url: bool = False,
    ) -> bool:
        """Validate file path and prepare collection for loading.
        Args:
            file_path (Path): Path to validate
            allowed_formats (List[str]): List of allowed file formats
            metadata (Optional[Dict[str, Any]]): Metadata to track
            recreate (bool): Whether to recreate the collection
        Returns:
            bool: True if preparation succeeded, False otherwise
        """
        # 1. Validate file path
        if not is_url:
            if not file_path.exists():
                logger.error(f"File not found: {file_path}")
                return False

            if file_path.suffix not in allowed_formats:
                logger.error(f"Unsupported file format: {file_path.suffix}")
                return False

        # 2. Track metadata
        if metadata:
            self._track_metadata_structure(metadata)

        # 3. Prepare vector DB
        if self.vector_db is None:
            logger.warning("Cannot load file: No vector db provided.")
            return False

        # Recreate collection if requested
        if recreate:
            log_info("Recreating collection.")
            await self.vector_db.async_drop()

        # Create collection if it doesn't exist
        if not await self.vector_db.async_exists():
            log_info("Collection does not exist. Creating.")
            await self.vector_db.async_create()

        return True

    def process_documents(
        self,
        documents: List[Document],
        metadata: Optional[Dict[str, Any]] = None,
        upsert: bool = False,
        skip_existing: bool = True,
        source_info: str = "documents",
    ) -> None:
        """Process and load documents asynchronously.
        Args:
            documents (List[Document]): Documents to process
            metadata (Optional[Dict[str, Any]]): Metadata to add to documents
            upsert (bool): Whether to upsert documents
            skip_existing (bool): Whether to skip existing documents
            source_info (str): Information about document source for logging
        """
        if not documents:
            logger.warning(f"No documents were read from {source_info}")
            return

        log_info(f"Loading {len(documents)} documents from {source_info} with metadata: {metadata}")

        # Decide loading strategy: upsert or insert (with optional skip)
        if upsert and self.vector_db.upsert_available():  # type: ignore
            log_debug(f"Upserting {len(documents)} documents.")  # type: ignore
            self.vector_db.upsert(documents=documents, filters=metadata)  # type: ignore
        else:
            documents_to_insert = documents
            if skip_existing:
                log_debug("Filtering out existing documents before insertion.")
                documents_to_insert = self.filter_existing_documents(documents)

            if documents_to_insert:  # type: ignore
                # type: ignore
                log_debug(f"Inserting {len(documents_to_insert)} new documents.")
                self.vector_db.insert(documents=documents_to_insert, filters=metadata)  # type: ignore
            else:
                log_info("No new documents to insert after filtering.")

        log_info(f"Finished loading documents from {source_info}.")

    async def aprocess_documents(
        self,
        documents: List[Document],
        metadata: Optional[Dict[str, Any]] = None,
        upsert: bool = False,
        skip_existing: bool = True,
        source_info: str = "documents",
    ) -> None:
        """Process and load documents asynchronously.
        Args:
            documents (List[Document]): Documents to process
            metadata (Optional[Dict[str, Any]]): Metadata to add to documents
            upsert (bool): Whether to upsert documents
            skip_existing (bool): Whether to skip existing documents
            source_info (str): Information about document source for logging
        """
        if not documents:
            logger.warning(f"No documents were read from {source_info}")
            return

        log_info(f"Loading {len(documents)} documents from {source_info} with metadata: {metadata}")

        # Decide loading strategy: upsert or insert (with optional skip)
        if upsert and self.vector_db.upsert_available():  # type: ignore
            log_debug(f"Upserting {len(documents)} documents.")
            # type: ignore
            await self.vector_db.async_upsert(documents=documents, filters=metadata)  # type: ignore
        else:
            documents_to_insert = documents
            if skip_existing:
                log_debug("Filtering out existing documents before insertion.")
                documents_to_insert = self.filter_existing_documents(documents)

            if documents_to_insert:  # type: ignore
                log_debug(f"Inserting {len(documents_to_insert)} new documents.")
                await self.vector_db.async_insert(documents=documents_to_insert, filters=metadata)  # type: ignore
            else:
                log_info("No new documents to insert after filtering.")

        log_info(f"Finished loading documents from {source_info}.")
