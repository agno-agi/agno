"""LightRagProvider — ExternalKnowledgeProvider implementation for LightRAG.

Encapsulates all HTTP communication with a LightRAG server. Pass directly
to ``Knowledge(external_provider=LightRagProvider(...))`` for graph-based RAG.

Ingestion is fire-and-forget: the provider hands content to LightRAG and
returns immediately with a ``ProcessingResult`` containing a ``processing_id``
(the LightRAG track_id).  LightRAG processes documents asynchronously in the
background; queries will include the new content once processing completes.
The Agno contents-db tracks content as PROCESSING until it is resolved via
``get_status``/``aget_status``.
"""

import asyncio
import concurrent.futures
from typing import Any, Dict, List, Optional

import httpx

from agno.knowledge.content import ContentStatus
from agno.knowledge.document import Document
from agno.knowledge.external_provider.schemas import ProcessingResult
from agno.utils.log import log_debug, log_error, log_info, log_warning

DEFAULT_SERVER_URL = "http://localhost:9621"

TRACK_ID_PREFIX = "track:"


class LightRagProvider:
    """External knowledge provider that talks to a LightRAG HTTP server."""

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
    # Async-to-sync helper
    # ------------------------------------------------------------------

    @staticmethod
    def _run_sync(coro):  # type: ignore[no-untyped-def]
        """Run an async coroutine from sync code, even inside a running event loop."""
        try:
            asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        except RuntimeError:
            return asyncio.run(coro)

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
    ) -> ProcessingResult:
        """Sync wrapper around aingest_file."""
        return self._run_sync(
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
    ) -> ProcessingResult:
        """Upload raw file bytes to the LightRAG server.

        Returns a ``ProcessingResult`` with the track_id as ``processing_id``.
        LightRAG processes the document in the background.
        """
        if not file_content:
            log_warning("File content is empty.")
            return ProcessingResult(
                processing_id="",
                status=ContentStatus.FAILED,
                status_message="File content is empty",
            )

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
            track_id = result["track_id"]
            log_info(f"File submitted to LightRAG, track_id: {track_id}")
            return ProcessingResult(
                processing_id=track_id,
                status=ContentStatus.PROCESSING,
            )

    # ------------------------------------------------------------------
    # Ingestion — plain text
    # ------------------------------------------------------------------

    def ingest_text(
        self,
        text: str,
        source_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ProcessingResult:
        """Sync wrapper around aingest_text."""
        return self._run_sync(self.aingest_text(text=text, source_name=source_name, metadata=metadata))

    async def aingest_text(
        self,
        text: str,
        source_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ProcessingResult:
        """Insert text into the LightRAG server.

        Returns a ``ProcessingResult`` with the track_id as ``processing_id``.
        LightRAG processes the document in the background.
        """
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
            track_id = result["track_id"]
            log_info(f"Text submitted to LightRAG, track_id: {track_id}")
            return ProcessingResult(
                processing_id=track_id,
                status=ContentStatus.PROCESSING,
            )

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
        result = self._run_sync(self.aquery(query=query, limit=limit, mode=mode, filters=filters))
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
            return self._run_sync(self.adelete_content(external_id))
        except Exception as e:
            log_error(f"Error in sync delete_content: {e}")
            return False

    async def adelete_content(
        self,
        external_id: str,
    ) -> bool:
        """Delete a document from LightRAG by its external ID.

        Accepts either a raw doc ID or a ``track:<track_id>`` reference.
        Track references are resolved to a doc ID on the fly.
        """
        try:
            doc_id = await self._resolve_doc_id(external_id)
            if doc_id is None:
                log_warning(f"Could not resolve LightRAG doc ID from: {external_id}")
                return False

            payload = {"doc_ids": [doc_id], "delete_file": False}
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
    # Status polling
    # ------------------------------------------------------------------

    def get_status(self, processing_id: str) -> ProcessingResult:
        """Sync wrapper around aget_status."""
        return self._run_sync(self.aget_status(processing_id))

    async def aget_status(self, processing_id: str) -> ProcessingResult:
        """Check LightRAG processing status for a track ID.

        Queries the track status endpoint and returns a ``ProcessingResult``
        with the resolved ``external_id`` (document ID) when completed.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.server_url}/documents/track_status/{processing_id}",
                    headers=self._get_headers(),
                )
                response.raise_for_status()
                result = response.json()
                log_debug(f"Track status for {processing_id}: {result}")

                status_summary = result.get("status_summary", {})
                if status_summary.get("failed", 0) > 0:
                    return ProcessingResult(
                        processing_id=processing_id,
                        status=ContentStatus.FAILED,
                        status_message="External provider processing failed",
                    )

                documents = result.get("documents", [])
                if documents:
                    external_id = documents[0]["id"]
                    return ProcessingResult(
                        processing_id=processing_id,
                        external_id=external_id,
                        status=ContentStatus.COMPLETED,
                    )

                return ProcessingResult(
                    processing_id=processing_id,
                    status=ContentStatus.PROCESSING,
                )
        except Exception as e:
            log_error(f"Error checking track status {processing_id}: {e}")
            return ProcessingResult(
                processing_id=processing_id,
                status=ContentStatus.PROCESSING,
                status_message=f"Error checking status: {e}",
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _resolve_doc_id(self, external_id: str) -> Optional[str]:
        """Resolve an external_id to a LightRAG document ID.

        If the external_id is a ``track:<track_id>`` reference, queries the
        track status endpoint to find the actual document ID.  Otherwise
        returns the external_id as-is (assumed to be a doc ID already).
        """
        if not external_id.startswith(TRACK_ID_PREFIX):
            return external_id

        track_id = external_id[len(TRACK_ID_PREFIX) :]
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.server_url}/documents/track_status/{track_id}",
                    headers=self._get_headers(),
                )
                response.raise_for_status()
                result = response.json()

                if "documents" in result and len(result["documents"]) > 0:
                    return result["documents"][0]["id"]

                log_warning(f"No documents found for track_id {track_id}: {result}")
                return None
        except Exception as e:
            log_error(f"Error resolving doc ID from track_id {track_id}: {e}")
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
