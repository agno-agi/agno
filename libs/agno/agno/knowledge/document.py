from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Union

from agno.document import Document
from agno.knowledge.agent import AgentKnowledge
from agno.utils.log import log_info, logger


class DocumentKnowledgeBase(AgentKnowledge):
    documents: Optional[Union[List[Document], List[Dict[str, Any]]]] = None

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over documents and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            Iterator[List[Document]]: Iterator yielding list of documents
        """
        if self.documents is None:
            # Return empty iterator when no documents are set
            return

        for item in self.documents:
            if isinstance(item, dict) and "document" in item:
                # Handle document with metadata
                document: Document = item["document"]
                config = item.get("metadata", {})
                if config:
                    log_info(f"Adding metadata {config} to document: {document.name}")
                    # Create a copy of the document with updated metadata
                    updated_document = Document(
                        content=document.content,
                        id=document.id,
                        name=document.name,
                        meta_data={**document.meta_data, **config},
                        embedder=document.embedder,
                        embedding=document.embedding,
                        usage=document.usage,
                        reranking_score=document.reranking_score,
                    )
                    yield [updated_document]
                else:
                    yield [document]
            elif isinstance(item, Document):
                # Handle direct document
                yield [item]
            else:
                raise ValueError(f"Invalid document format: {type(item)}")

    @property
    async def async_document_lists(self) -> AsyncIterator[List[Document]]:
        """Iterate over documents and yield lists of documents asynchronously.
        Each object yielded by the iterator is a list of documents.

        Returns:
            AsyncIterator[List[Document]]: Iterator yielding list of documents
        """
        if self.documents is None:
            # Return empty iterator when no documents are set
            return

        for item in self.documents:
            if isinstance(item, dict) and "document" in item:
                # Handle document with metadata
                document: Document = item["document"]
                config = item.get("metadata", {})
                if config:
                    log_info(f"Adding metadata {config} to document: {document.name}")
                    # Create a copy of the document with updated metadata
                    updated_document = Document(
                        content=document.content,
                        id=document.id,
                        name=document.name,
                        meta_data={**document.meta_data, **config},
                        embedder=document.embedder,
                        embedding=document.embedding,
                        usage=document.usage,
                        reranking_score=document.reranking_score,
                    )
                    yield [updated_document]
                else:
                    yield [document]
            elif isinstance(item, Document):
                # Handle direct document
                yield [item]
            else:
                raise ValueError(f"Invalid document format: {type(item)}")

    def _prepare_document_load(
        self,
        metadata: Optional[Dict[str, Any]] = None,
        recreate: bool = False,
    ) -> bool:
        """Prepare collection for loading documents (no file validation needed).
        Args:
            metadata (Optional[Dict[str, Any]]): Metadata to track
            recreate (bool): Whether to recreate the collection
        Returns:
            bool: True if preparation succeeded, False otherwise
        """
        # 1. Track metadata
        if metadata:
            self._track_metadata_structure(metadata)

        # 2. Prepare vector DB
        if self.vector_db is None:
            logger.warning("Cannot load document: No vector db provided.")
            return False

        # Recreate collection if requested
        if recreate:
            self.vector_db.drop()

        # Create collection if it doesn't exist
        if not self.vector_db.exists():
            self.vector_db.create()

        return True

    async def _aprepare_document_load(
        self,
        metadata: Optional[Dict[str, Any]] = None,
        recreate: bool = False,
    ) -> bool:
        """Prepare collection for loading documents asynchronously (no file validation needed).
        Args:
            metadata (Optional[Dict[str, Any]]): Metadata to track
            recreate (bool): Whether to recreate the collection
        Returns:
            bool: True if preparation succeeded, False otherwise
        """
        # 1. Track metadata
        if metadata:
            self._track_metadata_structure(metadata)

        # 2. Prepare vector DB
        if self.vector_db is None:
            logger.warning("Cannot load document: No vector db provided.")
            return False

        # Recreate collection if requested
        if recreate:
            await self.vector_db.async_drop()

        # Create collection if it doesn't exist
        if not await self.vector_db.async_exists():
            await self.vector_db.async_create()

        return True

    def load_document(
        self,
        document: Document,
        metadata: Optional[Dict[str, Any]] = None,
        recreate: bool = False,
        upsert: bool = False,
        skip_existing: bool = True,
    ) -> None:
        """Load a single document with specific metadata into the vector DB."""

        # Use our document-specific preparation method
        if not self._prepare_document_load(metadata, recreate):
            return

        # Apply metadata if provided
        if metadata:
            # Create a copy of the document with updated metadata
            document = Document(
                content=document.content,
                id=document.id,
                name=document.name,
                meta_data={**document.meta_data, **metadata},
                embedder=document.embedder,
                embedding=document.embedding,
                usage=document.usage,
                reranking_score=document.reranking_score,
            )

        # Process documents
        self.process_documents(
            documents=[document],
            metadata=metadata,
            upsert=upsert,
            skip_existing=skip_existing,
            source_info=f"document: {document.name or document.id}",
        )

    async def aload_document(
        self,
        document: Document,
        metadata: Optional[Dict[str, Any]] = None,
        recreate: bool = False,
        upsert: bool = False,
        skip_existing: bool = True,
    ) -> None:
        """Load a single document with specific metadata into the vector DB asynchronously."""

        # Use our document-specific preparation method
        if not await self._aprepare_document_load(metadata, recreate):
            return

        # Apply metadata if provided
        if metadata:
            # Create a copy of the document with updated metadata
            document = Document(
                content=document.content,
                id=document.id,
                name=document.name,
                meta_data={**document.meta_data, **metadata},
                embedder=document.embedder,
                embedding=document.embedding,
                usage=document.usage,
                reranking_score=document.reranking_score,
            )

        # Process documents
        await self.aprocess_documents(
            documents=[document],
            metadata=metadata,
            upsert=upsert,
            skip_existing=skip_existing,
            source_info=f"document: {document.name or document.id}",
        )
