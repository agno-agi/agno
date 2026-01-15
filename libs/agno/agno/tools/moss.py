import asyncio
import os
from typing import Any, Dict, List, Optional

from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, log_error, log_info

try:
    from inferedge_moss import DocumentInfo, MossClient  # type: ignore

    moss_available = True
except ImportError:
    moss_available = False


class MossTools(Toolkit):
    """
    Toolkit for interacting with Moss VectorDB.
    Moss handles embeddings internally and provides sub-10ms semantic search.
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        project_key: Optional[str] = None,
        default_index_name: Optional[str] = None,
        **kwargs,
    ):
        """
        Initialize the Moss Tools.

        Args:
            project_id (Optional[str]): Moss project ID.
            project_key (Optional[str]): Moss project key.
            default_index_name (Optional[str]): Default index name to use for tools.
        """
        if not moss_available:
            raise ImportError("`inferedge-moss` not installed. Please install using `pip install inferedge-moss`.")

        super().__init__(name="moss_tools", **kwargs)

        self.project_id: Optional[str] = project_id or os.getenv("MOSS_PROJECT_ID")
        self.project_key: Optional[str] = project_key or os.getenv("MOSS_PROJECT_KEY")
        self.default_index_name: Optional[str] = default_index_name

        if not self.project_id or not self.project_key:
            raise ValueError(
                "Moss credentials required. Provide project_id and project_key "
                "or set MOSS_PROJECT_ID and MOSS_PROJECT_KEY environment variables."
            )

        self.client: MossClient = MossClient(self.project_id, self.project_key)
        self._loaded_indexes: List[str] = []

        # Register tools
        self.register(self.search_moss)
        self.register(self.add_documents_to_moss)
        self.register(self.create_moss_index)
        self.register(self.list_moss_indexes)
        self.register(self.delete_moss_index)

    def _get_index_name(self, index_name: Optional[str]) -> str:
        name = index_name or self.default_index_name
        if not name:
            raise ValueError("index_name must be provided or default_index_name must be set.")
        return name

    async def _ensure_index_loaded(self, index_name: str):
        if index_name not in self._loaded_indexes:
            log_debug(f"Loading Moss index: {index_name}")
            await self.client.load_index(index_name)
            self._loaded_indexes.append(index_name)

    def search_moss(
        self,
        query: str,
        index_name: Optional[str] = None,
        limit: int = 5,
        alpha: float = 0.6,
    ) -> str:
        """Use this tool to search a Moss vector database for relevant information.

        Args:
            query (str): The search query.
            index_name (Optional[str]): The name of the index to search.
            limit (int): The number of results to return.
            alpha (float): Hybrid search weighting (1.0 = pure semantic, 0.0 = pure keyword). Defaults to 0.6.

        Returns:
            str: A JSON string containing the search results.
        """
        try:
            name = self._get_index_name(index_name)
            log_debug(f"Searching Moss index '{name}' for: {query}")

            async def run_search():
                await self._ensure_index_loaded(name)
                return await self.client.query(name, query, top_k=limit, alpha=alpha)

            results = asyncio.run(run_search())
            if not results or not results.docs:
                return f"No results found in Moss index '{name}'."

            search_results = [
                {
                    "id": res.id,
                    "content": res.text,
                    "metadata": res.metadata,
                    "score": getattr(res, "score", None),
                }
                for res in results.docs
            ]
            return str(search_results)
        except Exception as e:
            log_error(f"Error searching Moss: {e}")
            return f"Error searching Moss: {str(e)}"

    def add_documents_to_moss(
        self,
        documents: List[Dict[str, Any]],
        index_name: Optional[str] = None,
    ) -> str:
        """Use this tool to add documents to a Moss index.

        Args:
            documents (List[Dict[str, Any]]): A list of document dictionaries.
                Each dictionary should have 'text' and optionally 'id' and 'metadata'.
            index_name (Optional[str]): The name of the index to add documents to.

        Returns:
            str: A message indicating success or failure.
        """
        try:
            name = self._get_index_name(index_name)
            moss_docs = []
            for i, doc in enumerate(documents):
                doc_id = str(doc.get("id") or doc.get("doc_id") or f"doc_{i}")
                text = doc.get("text") or doc.get("content")
                if not text:
                    continue
                metadata = doc.get("metadata") or doc.get("meta_data") or {}
                # Ensure metadata keys/values are strings
                stringified_metadata = {str(k): str(v) for k, v in metadata.items()}

                moss_docs.append(DocumentInfo(id=doc_id, text=text, metadata=stringified_metadata))

            if not moss_docs:
                return "No valid documents provided."

            asyncio.run(self.client.add_docs(name, moss_docs))
            log_info(f"Added {len(moss_docs)} documents to Moss index '{name}'")
            return f"Successfully added {len(moss_docs)} documents to Moss index '{name}'."
        except Exception as e:
            log_error(f"Error adding documents to Moss: {e}")
            return f"Error adding documents to Moss: {str(e)}"

    def create_moss_index(
        self,
        index_name: str,
        embedding_model: str = "moss-minilm",
    ) -> str:
        """Use this tool to create a new Moss index.

        Args:
            index_name (str): The name of the index to create.
            embedding_model (str): The embedding model to use ('moss-minilm' or 'moss-mediumlm').

        Returns:
            str: A message indicating success or failure.
        """
        try:
            # Moss create_index requires at least one document
            # We'll create it with a seed document if it doesn't exist
            seed_doc = DocumentInfo(id="seed", text="Index created", metadata={"type": "seed"})

            async def run_create():
                indexes = await self.client.list_indexes()
                if any(idx.name == index_name for idx in indexes):
                    return f"Index '{index_name}' already exists."
                await self.client.create_index(index_name, [seed_doc], embedding_model)
                return f"Successfully created Moss index '{index_name}' with model '{embedding_model}'."

            return asyncio.run(run_create())
        except Exception as e:
            log_error(f"Error creating Moss index: {e}")
            return f"Error creating Moss index: {str(e)}"

    def list_moss_indexes(self) -> str:
        """Use this tool to list all available Moss indexes.

        Returns:
            str: A list of index names.
        """
        try:
            indexes = asyncio.run(self.client.list_indexes())
            index_list = [{"name": idx.name, "model": getattr(idx, "model", "unknown")} for idx in indexes]
            return str(index_list)
        except Exception as e:
            log_error(f"Error listing Moss indexes: {e}")
            return f"Error listing Moss indexes: {str(e)}"

    def delete_moss_index(self, index_name: str) -> str:
        """Use this tool to delete a Moss index.

        Args:
            index_name (str): The name of the index to delete.

        Returns:
            str: A message indicating success or failure.
        """
        try:
            asyncio.run(self.client.delete_index(index_name))
            if index_name in self._loaded_indexes:
                self._loaded_indexes.remove(index_name)
            return f"Successfully deleted Moss index '{index_name}'."
        except Exception as e:
            log_error(f"Error deleting Moss index: {e}")
            return f"Error deleting Moss index: {str(e)}"
