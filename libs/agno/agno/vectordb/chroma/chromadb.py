import asyncio
from hashlib import md5
from typing import Any, Dict, List, Optional

try:
    from chromadb import Client as ChromaDbClient
    from chromadb import PersistentClient as PersistentChromaDbClient
    from chromadb.api.client import ClientAPI
    from chromadb.api.models.Collection import Collection
    from chromadb.api.types import GetResult, QueryResult

except ImportError:
    raise ImportError("The `chromadb` package is not installed. Please install it via `pip install chromadb`.")

from agno.document import Document
from agno.embedder import Embedder
from agno.reranker.base import Reranker
from agno.utils.log import log_debug, log_info, logger
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance


class ChromaDb(VectorDb):
    def __init__(
        self,
        collection: str,
        embedder: Optional[Embedder] = None,
        distance: Distance = Distance.cosine,
        path: str = "tmp/chromadb",
        persistent_client: bool = False,
        reranker: Optional[Reranker] = None,
        **kwargs,
    ):
        # Collection attributes
        self.collection_name: str = collection

        # Embedder for embedding the document contents
        if embedder is None:
            from agno.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()
            log_info("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder: Embedder = embedder
        # Distance metric
        self.distance: Distance = distance

        # Chroma client instance
        self._client: Optional[ClientAPI] = None

        # Chroma collection instance
        self._collection: Optional[Collection] = None

        # Persistent Chroma client instance
        self.persistent_client: bool = persistent_client
        self.path: str = path

        # Reranker instance
        self.reranker: Optional[Reranker] = reranker

        # Chroma client kwargs
        self.kwargs = kwargs

    @property
    def client(self) -> ClientAPI:
        if self._client is None:
            if not self.persistent_client:
                log_debug("Creating Chroma Client")
                self._client = ChromaDbClient(
                    **self.kwargs,
                )
            elif self.persistent_client:
                log_debug("Creating Persistent Chroma Client")
                self._client = PersistentChromaDbClient(
                    path=self.path,
                    **self.kwargs,
                )
        return self._client

    def create(self) -> None:
        """Create the collection in ChromaDb."""
        if self.exists():
            log_debug(f"Collection already exists: {self.collection_name}")
            self._collection = self.client.get_collection(name=self.collection_name)
        else:
            log_debug(f"Creating collection: {self.collection_name}")
            self._collection = self.client.create_collection(
                name=self.collection_name, metadata={"hnsw:space": self.distance.value}
            )

    async def async_create(self) -> None:
        """Create the collection asynchronously by running in a thread."""
        await asyncio.to_thread(self.create)

    def doc_exists(self, document: Document) -> bool:
        """Check if a document exists in the collection.
        Args:
            document (Document): Document to check.
        Returns:
            bool: True if document exists, False otherwise.
        """
        if not self.client:
            logger.warning("Client not initialized")
            return False

        try:
            collection: Collection = self.client.get_collection(name=self.collection_name)
            collection_data: GetResult = collection.get(include=["documents"])  # type: ignore
            existing_documents = collection_data.get("documents", [])
            cleaned_content = document.content.replace("\x00", "\ufffd")
            if cleaned_content in existing_documents:  # type: ignore
                return True
        except Exception as e:
            logger.error(f"Document does not exist: {e}")
        return False

    async def async_doc_exists(self, document: Document) -> bool:
        """Check if a document exists asynchronously."""
        return await asyncio.to_thread(self.doc_exists, document)

    def name_exists(self, name: str) -> bool:
        """Check if a document with a given name exists in the collection.
        Args:
            name (str): Name of the document to check.
        Returns:
            bool: True if document exists, False otherwise."""
        if self.client:
            try:
                collections: Collection = self.client.get_collection(name=self.collection_name)
                for collection in collections:  # type: ignore
                    if name in collection:
                        return True
            except Exception as e:
                logger.error(f"Document with given name does not exist: {e}")
        return False

    async def async_name_exists(self, name: str) -> bool:
        """Check if a document with given name exists asynchronously."""
        return await asyncio.to_thread(self.name_exists, name)

    def insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents into the collection.

        Args:
            documents (List[Document]): List of documents to insert
            filters (Optional[Dict[str, Any]]): Filters to apply while inserting documents
        """
        log_debug(f"Inserting {len(documents)} documents")
        ids: List = []
        docs: List = []
        docs_embeddings: List = []
        docs_metadata: List = []

        if not self._collection:
            self._collection = self.client.get_collection(name=self.collection_name)

        for document in documents:
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = md5(cleaned_content.encode()).hexdigest()
            docs_embeddings.append(document.embedding)
            docs.append(cleaned_content)
            ids.append(doc_id)
            docs_metadata.append(document.meta_data)
            log_debug(f"Inserted document: {document.id} | {document.name} | {document.meta_data}")

        if self._collection is None:
            logger.warning("Collection does not exist")
        else:
            if len(docs) > 0:
                self._collection.add(ids=ids, embeddings=docs_embeddings, documents=docs, metadatas=docs_metadata)
                log_debug(f"Committed {len(docs)} documents")

    async def async_insert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents asynchronously by running in a thread."""
        await asyncio.to_thread(self.insert, documents, filters)

    def upsert_available(self) -> bool:
        """Check if upsert is available in ChromaDB."""
        return True

    def upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents into the collection.

        Args:
            documents (List[Document]): List of documents to upsert
            filters (Optional[Dict[str, Any]]): Filters to apply while upserting
        """
        log_debug(f"Upserting {len(documents)} documents")
        ids: List = []
        docs: List = []
        docs_embeddings: List = []
        docs_metadata: List = []

        if not self._collection:
            self._collection = self.client.get_collection(name=self.collection_name)

        for document in documents:
            document.embed(embedder=self.embedder)
            cleaned_content = document.content.replace("\x00", "\ufffd")
            doc_id = md5(cleaned_content.encode()).hexdigest()
            docs_embeddings.append(document.embedding)
            docs.append(cleaned_content)
            ids.append(doc_id)
            docs_metadata.append(document.meta_data)
            log_debug(f"Upserted document: {document.id} | {document.name} | {document.meta_data}")

        if self._collection is None:
            logger.warning("Collection does not exist")
        else:
            if len(docs) > 0:
                self._collection.upsert(ids=ids, embeddings=docs_embeddings, documents=docs, metadatas=docs_metadata)
                log_debug(f"Committed {len(docs)} documents")

    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents asynchronously by running in a thread."""
        await asyncio.to_thread(self.upsert, documents, filters)

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """Search the collection for a query.

        Args:
            query (str): Query to search for.
            limit (int): Number of results to return.
            filters (Optional[Dict[str, Any]]): Filters to apply while searching.
        Returns:
            List[Document]: List of search results.
        """
        query_embedding = self.embedder.get_embedding(query)
        if query_embedding is None:
            logger.error(f"Error getting embedding for Query: {query}")
            return []

        if not self._collection:
            self._collection = self.client.get_collection(name=self.collection_name)

        result: QueryResult = self._collection.query(
            query_embeddings=query_embedding,
            n_results=limit,
            include=["metadatas", "documents", "embeddings", "distances", "uris"],  # type: ignore
        )

        # Build search results
        search_results: List[Document] = []

        ids = result.get("ids", [[]])[0]
        metadata = result.get("metadatas", [{}])[0]  # type: ignore
        documents = result.get("documents", [[]])[0]  # type: ignore
        embeddings = result.get("embeddings")[0]  # type: ignore
        embeddings = [e.tolist() if hasattr(e, "tolist") else e for e in embeddings]  # type: ignore
        distances = result.get("distances", [[]])[0]  # type: ignore

        for idx, distance in enumerate(distances):
            metadata[idx]["distances"] = distance  # type: ignore

        try:
            # Use zip to iterate over multiple lists simultaneously
            for idx, (id_, metadata, document) in enumerate(zip(ids, metadata, documents)):
                search_results.append(
                    Document(
                        id=id_,
                        meta_data=metadata,
                        content=document,
                        embedding=embeddings[idx],  # type: ignore
                    )
                )
        except Exception as e:
            logger.error(f"Error building search results: {e}")

        if self.reranker:
            search_results = self.reranker.rerank(query=query, documents=search_results)

        return search_results

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Search asynchronously by running in a thread."""
        return await asyncio.to_thread(self.search, query, limit, filters)

    def drop(self) -> None:
        """Delete the collection."""
        if self.exists():
            log_debug(f"Deleting collection: {self.collection_name}")
            self.client.delete_collection(name=self.collection_name)

    async def async_drop(self) -> None:
        """Drop the collection asynchronously by running in a thread."""
        await asyncio.to_thread(self.drop)

    def exists(self) -> bool:
        """Check if the collection exists."""
        try:
            self.client.get_collection(name=self.collection_name)
            return True
        except Exception as e:
            log_debug(f"Collection does not exist: {e}")
        return False

    async def async_exists(self) -> bool:
        """Check if collection exists asynchronously by running in a thread."""
        return await asyncio.to_thread(self.exists)

    def get_count(self) -> int:
        """Get the count of documents in the collection."""
        if self.exists():
            try:
                collection: Collection = self.client.get_collection(name=self.collection_name)
                return collection.count()
            except Exception as e:
                logger.error(f"Error getting count: {e}")
        return 0

    def optimize(self) -> None:
        raise NotImplementedError

    def delete(self) -> bool:
        try:
            self.client.delete_collection(name=self.collection_name)
            return True
        except Exception as e:
            logger.error(f"Error clearing collection: {e}")
            return False
