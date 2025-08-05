from hashlib import md5
from typing import Any, Dict, List, Optional


from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.reranker.base import Reranker
from agno.utils.log import log_debug, log_info, log_warning, log_error
from agno.vectordb.base import VectorDb
from agno.vectordb.distance import Distance
from agno.vectordb.search import SearchType
import httpx
from fastapi import UploadFile

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
    ):
        self.server_url = server_url
        self.api_key = api_key
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

    async def async_upsert(self, documents: List[Document], filters: Optional[Dict[str, Any]] = None) -> None:
        """Async upsert documents into the vector database"""
        pass

    def search(self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Document]:
        """Search for documents matching the query"""
        return []

    async def async_search(
        self, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Async search for documents matching the query"""
        return []

    def drop(self) -> None:
        """Drop the vector database"""
        pass

    async def async_drop(self) -> None:
        """Async drop the vector database"""
        pass

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
            payload = {
                "doc_ids": [external_id],
                "delete_file": False
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method="DELETE",
                    url=f"{self.server_url}/documents/delete_document",
                    headers=self._get_headers(),
                    json=payload
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
            skip_if_exists: bool = False
        ) -> Dict[str, Any]:
        """Insert file from raw bytes into the LightRAG server."""
        
        if not file_content:
            log_warning("File content is empty.")
            return {"error": "File content is empty"}
        
        if send_metadata and filename and content_type:
            # Send with filename and content type (full UploadFile format)
            files = {
                "file": (filename, file_content, content_type)
            }
        else:
            # Send just binary data
            files = {
                "file": file_content
            }

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
            result = await self._get_document_id(track_id)
            log_info(f"Document ID: {result}")
            return result

    async def insert_text(self, file_source: str, text: str) -> Dict[str, Any]:
        """Insert text into the LightRAG server."""
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.server_url}/documents/text",
                json={
                    "file_source": file_source,
                    "text": text
                },
                headers=self._get_headers(),
            )
            response.raise_for_status()
            result = response.json()
            
            log_info(f"Text insertion result: {result}")
            track_id = result["track_id"]
            log_info(f"Track ID: {track_id}")
            result = await self._get_document_id(track_id)
            log_info(f"Document ID: {result}")
            return result

    async def _get_document_id(self, track_id: str) -> str:
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
                raise ValueError(f"No documents found in track response: {result}")
        

    def _is_valid_url(self, url: str) -> bool:
        """Helper to check if URL is valid."""
        # TODO: Define supported extensions or implement proper URL validation
        return True
    


    