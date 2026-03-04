"""LightRagBackend — ManagedKnowledgeBackend implementation for LightRAG.

Encapsulates all HTTP communication with a LightRAG server. The existing
``agno.vectordb.lightrag.LightRag`` class delegates to an instance of this
backend so that ``isinstance(lightrag_vdb, ManagedKnowledgeBackend)`` is True.
"""

import asyncio
from typing import Any, Dict, List, Optional

import httpx

from agno.knowledge.document import Document
from agno.utils.log import log_debug, log_error, log_info, log_warning

DEFAULT_SERVER_URL = "http://localhost:9621"


class LightRagBackend:
    """Managed backend that talks to a LightRAG HTTP server."""

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

    # ------------------------------------------------------------------
    # Header helpers
    # ------------------------------------------------------------------

    def _get_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers[self.auth_header_name] = self.auth_header_format.format(api_key=self.api_key)
        return headers

    def _get_auth_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if self.api_key:
            headers[self.auth_header_name] = self.auth_header_format.format(api_key=self.api_key)
        return headers

    # ------------------------------------------------------------------
    # Ingestion — file bytes
    # ------------------------------------------------------------------

    def ingest_file(
        self,
        file_content: bytes,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Sync wrapper around aingest_file."""
        return asyncio.run(
            self.aingest_file(
                file_content=file_content,
                filename=filename,
                content_type=content_type,
                metadata=metadata,
            )
        )

    async def aingest_file(
        self,
        file_content: bytes,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Upload raw file bytes to the LightRAG server. Returns an external document ID."""
        if not file_content:
            log_warning("File content is empty.")
            return None

        if filename and content_type:
            files = {"file": (filename, file_content, content_type)}
        else:
            files = {"file": file_content}  # type: ignore[dict-item]

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
            doc_id = await self._get_document_id(track_id)
            log_info(f"Document ID: {doc_id}")
            return doc_id

    # ------------------------------------------------------------------
    # Ingestion — plain text
    # ------------------------------------------------------------------

    def ingest_text(
        self,
        text: str,
        source_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Sync wrapper around aingest_text."""
        return asyncio.run(self.aingest_text(text=text, source_name=source_name, metadata=metadata))

    async def aingest_text(
        self,
        text: str,
        source_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Insert text into the LightRAG server. Returns an external document ID."""
        payload: Dict[str, str] = {"text": text}
        if source_name:
            payload["file_source"] = source_name

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.server_url}/documents/text",
                json=payload,
                headers=self._get_headers(),
            )
            response.raise_for_status()
            result = response.json()
            log_info(f"Text insertion result: {result}")
            track_id = result["track_id"]
            log_info(f"Track ID: {track_id}")
            doc_id = await self._get_document_id(track_id)
            log_info(f"Document ID: {doc_id}")
            return doc_id

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(
        self,
        query: str,
        limit: int = 10,
        mode: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Sync wrapper around aquery."""
        result = asyncio.run(self.aquery(query=query, limit=limit, mode=mode, filters=filters))
        return result if result is not None else []

    async def aquery(
        self,
        query: str,
        limit: int = 10,
        mode: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Query the LightRAG server. Returns matching documents."""
        query_mode = mode or "hybrid"
        if filters is not None:
            log_warning("Filters are not supported in LightRAG. No filters will be applied.")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.server_url}/query",
                    json={"query": query, "mode": query_mode, "include_references": True},
                    headers=self._get_headers(),
                )
                response.raise_for_status()
                result = response.json()
                return self._format_response(result, query, query_mode)

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
            return []

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------

    def delete_content(
        self,
        external_id: str,
    ) -> bool:
        """Sync wrapper around adelete_content."""
        try:
            return asyncio.run(self.adelete_content(external_id))
        except Exception as e:
            log_error(f"Error in sync delete_content: {e}")
            return False

    async def adelete_content(
        self,
        external_id: str,
    ) -> bool:
        """Delete a document from LightRAG by its external ID."""
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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_document_id(self, track_id: str) -> Optional[str]:
        """Poll the LightRAG server for a document ID given a track ID."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.server_url}/documents/track_status/{track_id}",
                headers=self._get_headers(),
            )
            response.raise_for_status()
            result = response.json()
            log_debug(f"Document ID result: {result}")

            if "documents" in result and len(result["documents"]) > 0:
                return result["documents"][0]["id"]
            else:
                log_error(f"No documents found in track response: {result}")
                return None

    def _format_response(self, result: Any, query: str, mode: str) -> List[Document]:
        """Format LightRAG server response into Document objects."""
        if isinstance(result, dict) and "response" in result:
            meta_data: Dict[str, Any] = {"source": "lightrag", "query": query, "mode": mode}
            if "references" in result:
                meta_data["references"] = result["references"]
            return [Document(content=result["response"], meta_data=meta_data)]
        elif isinstance(result, list):
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
            return [Document(content=str(result), meta_data={"source": "lightrag", "query": query, "mode": mode})]
