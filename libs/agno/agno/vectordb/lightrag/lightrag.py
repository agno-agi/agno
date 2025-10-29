import asyncio
from typing import Any, Dict, List, Optional

import httpx

from agno.knowledge.document import Document
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.vectordb.base import VectorDb

DEFAULT_SERVER_URL = "http://localhost:9621"


class LightRag(VectorDb):
    """
    LightRAG VectorDB implementation
    """

    def __init__(
        self,
        server_url: str = DEFAULT_SERVER_URL,
        api_key: Optional[str] = None,
        auth_header_name: str = "X-API-KEY",
        auth_header_format: str = "{api_key}",
        name: Optional[str] = None,
        description: Optional[str] = None,
    ):
        self.server_url = server_url
        self.api_key = api_key
        # Initialize base class with name and description
        super().__init__(name=name, description=description)

        self.auth_header_name = auth_header_name
        self.auth_header_format = auth_header_format

    def _get_headers(self) -> Dict[str, str]:
        """Get headers with optional API key authentication."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers[self.auth_header_name] = self.auth_header_format.format(api_key=self.api_key)
        return headers

    def _get_auth_headers(self) -> Dict[str, str]:
        """Get minimal headers with just authentication (for file uploads)."""
        headers = {}
        if self.api_key:
            headers[self.auth_header_name] = self.auth_header_format.format(api_key=self.api_key)
        return headers

    def create(self) -> None:
        """Create the vector database"""
        pass

    async def async_create(self) -> None:
        """Async create the vector database"""
        pass

    def name_exists(self, name: str) -> bool:
        """Check if a document with the given name exists"""
        return False

    async def async_name_exists(self, name: str) -> bool:
        """Async check if a document with the given name exists"""
        return False

    def id_exists(self, id: str) -> bool:
        """Check if a document with the given ID exists"""
        return False

    def content_hash_exists(self, content_hash: str) -> bool:
        """Check if content with the given hash exists"""
        return False

    def insert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Insert documents into the vector database"""
        pass

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None
    ) -> None:
        """Async insert documents into the vector database"""
        pass

    def upsert(self, content_hash: str, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Upsert documents into the vector database"""
        pass

    def delete_by_content_id(self, content_id: str) -> None:
        """Delete documents by content ID"""
        pass

    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Async upsert documents into the vector database"""
        pass

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        result = asyncio.run(self.async_search(query, limit=limit, filters=filters))
        return result if result is not None else []

    async def async_search(
        self, query: str, limit: Optional[int] = None, filters: Optional[Dict[str, Any]] = None
    ) -> Optional[List[Document]]:
        mode: str = "hybrid"  # Default mode, can be "local", "global", or "hybrid"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.server_url}/query",
                    json={"query": query, "mode": "hybrid"},
                    headers=self._get_headers(),
                )

                response.raise_for_status()
                result = response.json()

                return self._format_lightrag_response(result, query, mode)

        except httpx.RequestError as e:
            log_error(f"HTTP Request Error: {type(e).__name__}: {str(e)}")
            return []
        except httpx.HTTPStatusError as e:
            log_error(f"HTTP Status Error: {e.response.status_code} - {e.response.text}")
            return []
        except Exception as e:
            log_error(f"Unexpected error during LightRAG server search: {type(e).__name__}: {str(e)}")
            import traceback

            log_error(f"Full traceback: {traceback.format_exc()}")
            return None

    def drop(self) -> None:
        """Drop the vector database"""
        asyncio.run(self.async_drop())

    async def async_drop(self) -> None:
        """Async drop the vector database"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.delete(f"{self.server_url}/documents", headers=self._get_headers())

        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(
                f"{self.server_url}/documents/clear_cache",
                json={"modes": ["default", "naive"]},
                headers=self._get_headers(),
            )

    def exists(self) -> bool:
        """Check if the vector database exists"""
        return False

    async def async_exists(self) -> bool:
        """Async check if the vector database exists"""
        return False

    def delete(self) -> bool:
        """Delete all documents from the vector database"""
        return False

    def delete_by_id(self, id: str) -> bool:
        """Delete documents by ID"""
        return False

    def delete_by_name(self, name: str) -> bool:
        """Delete documents by name"""
        return False

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Delete documents by metadata"""
        return False

    def delete_by_external_id(self, external_id: str) -> bool:
        """Delete documents by external ID (sync wrapper)"""
        import asyncio

        try:
            return asyncio.run(self.async_delete_by_external_id(external_id))
        except Exception as e:
            log_error(f"Error in sync delete_by_external_id: {e}")
            return False

    async def async_delete_by_external_id(self, external_id: str) -> bool:
        """Delete documents by external ID"""
        try:
            payload = {"doc_ids": [external_id], "delete_file": False}

            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method="DELETE",
                    url=f"{self.server_url}/documents/delete_document",
                    headers=self._get_headers(),
                    json=payload,
                )
                response.raise_for_status()
                return True
        except Exception as e:
            log_error(f"Error deleting document {external_id}: {e}")
            return False

    # We use this method when content is coming from unsupported file types that LightRAG can't process
    # For these we process the content in Agno and then insert it into LightRAG using text
    async def _insert_text(self, text: str) -> Dict[str, Any]:
        """Insert text into the LightRAG server."""

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.server_url}/documents/text",
                json={"text": text},
                headers=self._get_headers(),
            )
            response.raise_for_status()
            result = response.json()
            log_debug(f"Text insertion result: {result}")
            return result

    async def insert_file_bytes(
        self,
        file_content: bytes,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        send_metadata: bool = False,
        skip_if_exists: bool = False,
    ) -> Optional[str]:
        """Insert file from raw bytes into the LightRAG server."""

        if not file_content:
            log_warning("File content is empty.")
            return None

        if send_metadata and filename and content_type:
            # Send with filename and content type (full UploadFile format)
            files = {"file": (filename, file_content, content_type)}
        else:
            files = {"file": file_content}  # type: ignore

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.server_url}/documents/upload",
                files=files,
                headers=self._get_auth_headers(),
            )
            response.raise_for_status()
            result = response.json()
            log_info(f"File insertion result: {result}")
            track_id = result["track_id"]
            log_info(f"Track ID: {track_id}")
            result = await self._get_document_id(track_id)  # type: ignore
            log_info(f"Document ID: {result}")

            return result

    async def insert_text(self, file_source: str, text: str) -> Optional[str]:
        """Insert text into the LightRAG server."""
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.server_url}/documents/text",
                json={"file_source": file_source, "text": text},
                headers=self._get_headers(),
            )
            response.raise_for_status()
            result = response.json()

            log_info(f"Text insertion result: {result}")
            track_id = result["track_id"]
            log_info(f"Track ID: {track_id}")
            result = await self._get_document_id(track_id)  # type: ignore
            log_info(f"Document ID: {result}")

            return result

    async def _get_document_id(self, track_id: str) -> Optional[str]:
        """Get the document ID from the upload ID."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.server_url}/documents/track_status/{track_id}",
                headers=self._get_headers(),
            )
            response.raise_for_status()
            result = response.json()

            log_debug(f"Document ID result: {result}")

            # Extract document ID from the documents array
            if "documents" in result and len(result["documents"]) > 0:
                document_id = result["documents"][0]["id"]
                return document_id
            else:
                log_error(f"No documents found in track response: {result}")
                return None

    def _is_valid_url(self, url: str) -> bool:
        """Helper to check if URL is valid."""
        # TODO: Define supported extensions or implement proper URL validation
        return True

    async def lightrag_knowledge_retriever(
        self,
        query: str,
    ) -> Optional[List[Document]]:
        """
        Custom knowledge retriever function to search the LightRAG server for relevant documents.

        Args:
            query: The search query string
            num_documents: Number of documents to retrieve (currently unused by LightRAG)
            mode: Query mode - "local", "global", or "hybrid"
            lightrag_server_url: URL of the LightRAG server

        Returns:
            List of retrieved documents or None if search fails
        """

        mode: str = "hybrid"  # Default mode, can be "local", "global", or "hybrid"

        try:
            import httpx

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.server_url}/query",
                    json={"query": query, "mode": "hybrid"},
                    headers=self._get_headers(),
                )

                response.raise_for_status()
                result = response.json()

                return self._format_lightrag_response(result, query, mode)

        except httpx.RequestError as e:
            log_error(f"HTTP Request Error: {type(e).__name__}: {str(e)}")
            return None
        except httpx.HTTPStatusError as e:
            log_error(f"HTTP Status Error: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            log_error(f"Unexpected error during LightRAG server search: {type(e).__name__}: {str(e)}")
            import traceback

            log_error(f"Full traceback: {traceback.format_exc()}")
            return None

    def _format_lightrag_response(self, result: Any, query: str, mode: str) -> List[Document]:
        """Format LightRAG server response to expected document format."""
        # LightRAG server returns a dict with 'response' key, but we expect a list of documents
        # Convert the response to the expected format
        if isinstance(result, dict) and "response" in result:
            # Wrap the response in a Document object
            return [
                Document(content=result["response"], meta_data={"source": "lightrag", "query": query, "mode": mode})
            ]
        elif isinstance(result, list):
            # Convert list items to Document objects
            documents = []
            for item in result:
                if isinstance(item, dict) and "content" in item:
                    documents.append(
                        Document(
                            content=item["content"],
                            meta_data=item.get("metadata", {"source": "lightrag", "query": query, "mode": mode}),
                        )
                    )
                else:
                    documents.append(
                        Document(content=str(item), meta_data={"source": "lightrag", "query": query, "mode": mode})
                    )
            return documents
        else:
            # If it's a string or other format, wrap it in a Document
            return [Document(content=str(result), meta_data={"source": "lightrag", "query": query, "mode": mode})]

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        """
        Update metadata is not supported for LightRag as it manages its own graph structure.

        Args:
            content_id (str): The content ID to update
            metadata (Dict[str, Any]): The metadata to update
        """
        raise NotImplementedError("update_metadata not supported for LightRag - use LightRag's native methods")

    def get_supported_search_types(self) -> List[str]:
        """Get the supported search types for this vector database."""
        return []  # LightRag doesn't use SearchType enum
