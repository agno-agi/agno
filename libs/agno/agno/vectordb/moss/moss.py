import asyncio
import os
from typing import Any, Dict, List, Optional

from agno.knowledge.document import Document
from agno.utils.log import log_debug, log_error, log_info
from agno.vectordb.base import VectorDb

try:
    from inferedge_moss import DocumentInfo, GetDocumentsOptions, MossClient

    moss_available = True
except ImportError:
    moss_available = False


class Moss(VectorDb):
    """
    Moss VectorDB implementation for Agno.
    Moss handles embeddings internally and provides sub-10ms semantic search.
    """

    def __init__(
        self,
        index_name: str,
        project_id: Optional[str] = None,
        project_key: Optional[str] = None,
        model: str = "moss-minilm",
        alpha: float = 0.6,
        name: Optional[str] = None,
        description: Optional[str] = None,
        id: Optional[str] = None,
        **kwargs,
    ):
        """
        Initialize the Moss VectorDB.

        Args:
            index_name (str): Name of the Moss index.
            project_id (Optional[str]): Moss project ID.
            project_key (Optional[str]): Moss project key.
            model (str): Embedding model to use. Defaults to "moss-minilm". "moss-mediumlm" for higher accuracy
            alpha (float): Hybrid search weighting. Defaults to 0.6.
            name (Optional[str]): Name of the vector database.
            description (Optional[str]): Description of the vector database.
            id (Optional[str]): Optional custom ID.
        """
        if not moss_available:
            raise ImportError("`inferedge_moss` not installed. Please install using `pip install inferedge-moss`.")

        super().__init__(id=id, name=name, description=description)

        self.index_name: str = index_name
        self.model: str = model
        self.alpha: float = alpha
        self.project_id: Optional[str] = project_id or os.getenv("MOSS_PROJECT_ID")
        self.project_key: Optional[str] = project_key or os.getenv("MOSS_PROJECT_KEY")

        if not self.project_id or not self.project_key:
            raise ValueError(
                "Moss credentials required. Provide project_id and project_key "
                "or set MOSS_PROJECT_ID and MOSS_PROJECT_KEY environment variables."
            )

        self.client: MossClient = MossClient(self.project_id, self.project_key)
        self._index_loaded: bool = False
        log_debug(f"Initialized Moss VectorDB for index: {self.index_name}")

    def create(self) -> None:
        """Moss index is created on demand during insert if it doesn't exist."""
        log_info(f"Moss index '{self.index_name}' will be created on first insert")

    async def async_create(self) -> None:
        """Moss index is created on demand during insert if it doesn't exist."""
        self.create()

    def name_exists(self, name: str) -> bool:
        """Check if an index with the given name exists."""
        try:
            indexes = asyncio.run(self.client.list_indexes())
            return any(idx.name == name for idx in indexes)
        except Exception as e:
            log_error(f"Error checking if index exists: {e}")
            return False

    async def async_name_exists(self, name: str) -> bool:
        """Check if index exists asynchronously."""
        try:
            indexes = await self.client.list_indexes()
            return any(idx.name == name for idx in indexes)
        except Exception as e:
            log_error(f"Error checking if index exists: {e}")
            return False

    def id_exists(self, id: str) -> bool:
        """Check if a document with the given ID exists."""
        try:
            docs = asyncio.run(self.client.get_docs(self.index_name, options=GetDocumentsOptions(doc_ids=[id])))
            return len(docs) > 0
        except Exception as e:
            log_error(f"Error checking if ID exists: {e}")
            return False

    def content_hash_exists(self, content_hash: str) -> bool:
        """Not supported by Moss directly."""
        return False

    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents into the database."""
        if not documents:
            return

        moss_docs = [
            DocumentInfo(
                id=str(doc.id),
                text=doc.content,
                metadata={str(k): str(v) for k, v in {**(doc.meta_data or {}), **(filters or {})}.items()},
            )
            for doc in documents
        ]

        try:
            if not self.name_exists(self.index_name):
                log_info(f"Creating Moss index: {self.index_name}")
                asyncio.run(self.client.create_index(self.index_name, moss_docs, self.model))
            else:
                log_info(f"Adding documents to Moss index: {self.index_name}")
                asyncio.run(self.client.add_docs(self.index_name, moss_docs))
            log_info(f"Inserted {len(documents)} documents into Moss")
        except Exception as e:
            log_error(f"Error inserting documents: {e}")
            raise

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Insert documents asynchronously."""
        if not documents:
            return

        moss_docs = [
            DocumentInfo(
                id=str(doc.id),
                text=doc.content,
                metadata={str(k): str(v) for k, v in {**(doc.meta_data or {}), **(filters or {})}.items()},
            )
            for doc in documents
        ]

        try:
            if not await self.async_name_exists(self.index_name):
                log_info(f"Creating Moss index: {self.index_name}")
                await self.client.create_index(self.index_name, moss_docs, self.model)
            else:
                log_info(f"Adding documents to Moss index: {self.index_name}")
                await self.client.add_docs(self.index_name, moss_docs)
            log_info(f"Inserted {len(documents)} documents into Moss")
        except Exception as e:
            log_error(f"Error inserting documents: {e}")
            raise

    def upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Moss automatically handles updates if document ID matches."""
        self.insert(content_hash, documents, filters)

    async def async_upsert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Moss automatically handles updates if document ID matches."""
        await self.async_insert(content_hash, documents, filters)

    def search(self, query: str, limit: int = 5, filters: Optional[Any] = None) -> List[Document]:
        """Search for similar documents."""
        try:
            if not self._index_loaded:
                asyncio.run(self.client.load_index(self.index_name))
                self._index_loaded = True

            # Use alpha from filters if provided, otherwise use default
            search_alpha = self.alpha
            if isinstance(filters, dict) and "alpha" in filters:
                search_alpha = filters.pop("alpha")

            results = asyncio.run(self.client.query(self.index_name, query, top_k=limit, alpha=search_alpha))
            return [
                Document(
                    id=res.id,
                    content=res.text,
                    meta_data={
                        **(res.metadata or {}),
                        "similarity_score": getattr(res, "score", None),
                    },
                )
                for res in results.docs
            ]
        except Exception as e:
            log_error(f"Error searching Moss: {e}")
            return []

    async def async_search(self, query: str, limit: int = 5, filters: Optional[Any] = None) -> List[Document]:
        """Search for similar documents asynchronously."""
        try:
            if not self._index_loaded:
                await self.client.load_index(self.index_name)
                self._index_loaded = True

            # Use alpha from filters if provided, otherwise use default
            search_alpha = self.alpha
            if isinstance(filters, dict) and "alpha" in filters:
                search_alpha = filters.pop("alpha")

            results = await self.client.query(self.index_name, query, top_k=limit, alpha=search_alpha)
            return [
                Document(
                    id=res.id,
                    content=res.text,
                    meta_data={
                        **(res.metadata or {}),
                        "similarity_score": getattr(res, "score", None),
                    },
                )
                for res in results.docs
            ]
        except Exception as e:
            log_error(f"Error searching Moss: {e}")
            return []

    def drop(self) -> None:
        """Delete the Moss index."""
        try:
            asyncio.run(self.client.delete_index(self.index_name))
            self._index_loaded = False
        except Exception as e:
            log_error(f"Error deleting index: {e}")
            raise

    async def async_drop(self) -> None:
        """Delete the Moss index asynchronously."""
        try:
            await self.client.delete_index(self.index_name)
            self._index_loaded = False
        except Exception as e:
            log_error(f"Error deleting index: {e}")
            raise

    def exists(self) -> bool:
        """Check if index exists."""
        return self.name_exists(self.index_name)

    async def async_exists(self) -> bool:
        """Check if index exists asynchronously."""
        return await self.async_name_exists(self.index_name)

    def delete(self) -> bool:
        """Delete all documents (deletes index)."""
        try:
            self.drop()
            return True
        except Exception:
            return False

    def delete_by_id(self, id: str) -> bool:
        """Delete a document by ID."""
        try:
            asyncio.run(self.client.delete_docs(self.index_name, doc_ids=[id]))
            return True
        except Exception as e:
            log_error(f"Error deleting document by ID: {e}")
            return False

    def delete_by_name(self, name: str) -> bool:
        """Not supported directly."""
        return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Not supported directly."""
        return False

    def delete_by_content_id(self, content_id: str) -> bool:
        """Delete documents by content ID."""
        return self.delete_by_id(content_id)

    def get_supported_search_types(self) -> List[str]:
        """Returns supported search types."""
        return ["vector"]
