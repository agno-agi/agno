"""GCSBackupStore — Google Cloud Storage store for original documents.

Same interface as ``BackupStore`` but stores files in GCS instead of
the local filesystem. Parsed text, raw bytes, and metadata are stored
as blobs under ``{prefix}/{content_id}/``.

Blob layout::

    gs://{bucket_name}/{prefix}/
        <content_id>/
            parsed.txt      # Parsed text content
            raw.<ext>        # Original file (optional)
            metadata.json    # Content metadata
"""

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agno.knowledge.store.backup_store import GrepResult
from agno.utils.log import log_debug, log_info, log_warning


@dataclass
class GCSBackupStore:
    """Google Cloud Storage store for original document content."""

    bucket_name: str
    prefix: str = "knowledge_backup"
    project: Optional[str] = None
    credentials_path: Optional[str] = None

    def _blob_name(self, content_id: str, filename: str) -> str:
        return f"{self.prefix.rstrip('/')}/{content_id}/{filename}"

    def _get_bucket(self):
        try:
            from google.cloud import storage
        except ImportError:
            raise ImportError(
                "google-cloud-storage is required for GCSBackupStore. Install it with: pip install google-cloud-storage"
            )

        kwargs: Dict[str, Any] = {}
        if self.project:
            kwargs["project"] = self.project
        if self.credentials_path:
            from google.oauth2 import service_account

            credentials = service_account.Credentials.from_service_account_file(self.credentials_path)
            kwargs["credentials"] = credentials

        client = storage.Client(**kwargs)
        return client.bucket(self.bucket_name)

    def store(
        self,
        content_id: str,
        parsed_text: str,
        raw_bytes: Optional[bytes] = None,
        file_extension: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Store parsed text and optional raw content in GCS."""
        bucket = self._get_bucket()

        blob = bucket.blob(self._blob_name(content_id, "parsed.txt"))
        blob.upload_from_string(parsed_text, content_type="text/plain")
        log_info(f"Stored parsed text for {content_id} in GCS ({len(parsed_text)} chars)")

        if raw_bytes is not None:
            ext = file_extension or ".bin"
            if not ext.startswith("."):
                ext = f".{ext}"
            raw_blob = bucket.blob(self._blob_name(content_id, f"raw{ext}"))
            raw_blob.upload_from_string(raw_bytes)
            log_debug(f"Stored raw file for {content_id} in GCS ({len(raw_bytes)} bytes)")

        if metadata:
            meta_blob = bucket.blob(self._blob_name(content_id, "metadata.json"))
            meta_blob.upload_from_string(
                json.dumps(metadata, indent=2, default=str),
                content_type="application/json",
            )

    async def astore(
        self,
        content_id: str,
        parsed_text: str,
        raw_bytes: Optional[bytes] = None,
        file_extension: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Async variant of store. Uses asyncio.to_thread for GCS (no native async)."""
        await asyncio.to_thread(
            self.store,
            content_id=content_id,
            parsed_text=parsed_text,
            raw_bytes=raw_bytes,
            file_extension=file_extension,
            metadata=metadata,
        )

    def _get_text(self, blob_name: str) -> Optional[str]:
        """Get text content from GCS, returns None if not found."""
        bucket = self._get_bucket()
        blob = bucket.blob(blob_name)
        if not blob.exists():
            return None
        return blob.download_as_text(encoding="utf-8")

    async def _aget_text(self, blob_name: str) -> Optional[str]:
        """Async variant of _get_text."""
        return await asyncio.to_thread(self._get_text, blob_name)

    def read(
        self,
        content_id: str,
        offset: int = 0,
        limit: int = 200,
    ) -> Optional[str]:
        """Read parsed text for a document with line-based pagination."""
        text = self._get_text(self._blob_name(content_id, "parsed.txt"))
        if text is None:
            return None

        lines = text.splitlines()
        total = len(lines)
        selected = lines[offset : offset + limit]

        header = f"[Lines {offset + 1}-{min(offset + limit, total)} of {total}]"
        numbered = [f"{offset + i + 1}: {line}" for i, line in enumerate(selected)]
        return header + "\n" + "\n".join(numbered)

    async def aread(
        self,
        content_id: str,
        offset: int = 0,
        limit: int = 200,
    ) -> Optional[str]:
        """Async variant of read."""
        text = await self._aget_text(self._blob_name(content_id, "parsed.txt"))
        if text is None:
            return None

        lines = text.splitlines()
        total = len(lines)
        selected = lines[offset : offset + limit]

        header = f"[Lines {offset + 1}-{min(offset + limit, total)} of {total}]"
        numbered = [f"{offset + i + 1}: {line}" for i, line in enumerate(selected)]
        return header + "\n" + "\n".join(numbered)

    def _grep_text(
        self, content_id: str, text: str, pattern: re.Pattern, context: int, max_matches: int
    ) -> List[GrepResult]:
        """Grep through text content, returning matches with context."""
        lines = text.splitlines()
        results: List[GrepResult] = []

        for i, line in enumerate(lines):
            if pattern.search(line):
                before = lines[max(0, i - context) : i]
                after = lines[i + 1 : min(len(lines), i + 1 + context)]
                results.append(
                    GrepResult(
                        content_id=content_id,
                        line_number=i + 1,
                        line=line,
                        context_before=before,
                        context_after=after,
                    )
                )
                if len(results) >= max_matches:
                    break

        return results

    def grep(
        self,
        content_id: str,
        pattern: str,
        context: int = 2,
        max_matches: int = 20,
    ) -> List[GrepResult]:
        """Search within a single document's parsed text in GCS."""
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            log_warning(f"Invalid regex pattern '{pattern}': {e}")
            return []

        text = self._get_text(self._blob_name(content_id, "parsed.txt"))
        if text is None:
            return []

        return self._grep_text(content_id, text, compiled, context, max_matches)

    async def agrep(
        self,
        content_id: str,
        pattern: str,
        context: int = 2,
        max_matches: int = 20,
    ) -> List[GrepResult]:
        """Async variant of grep."""
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            log_warning(f"Invalid regex pattern '{pattern}': {e}")
            return []

        text = await self._aget_text(self._blob_name(content_id, "parsed.txt"))
        if text is None:
            return []

        return self._grep_text(content_id, text, compiled, context, max_matches)

    def _list_content_ids(self) -> List[str]:
        """List all content IDs stored in GCS under the prefix."""
        bucket = self._get_bucket()
        prefix = self.prefix.rstrip("/") + "/"
        content_ids: set = set()

        for blob in bucket.list_blobs(prefix=prefix):
            # blob.name looks like "prefix/content_id/parsed.txt"
            relative = blob.name[len(prefix) :]
            parts = relative.split("/", 1)
            if parts[0]:
                content_ids.add(parts[0])

        return sorted(content_ids)

    async def _alist_content_ids(self) -> List[str]:
        """Async variant of _list_content_ids."""
        return await asyncio.to_thread(self._list_content_ids)

    def grep_all(
        self,
        pattern: str,
        context: int = 2,
        max_matches: int = 50,
    ) -> List[GrepResult]:
        """Search across all stored documents in GCS."""
        try:
            re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            log_warning(f"Invalid regex pattern '{pattern}': {e}")
            return []

        results: List[GrepResult] = []
        for content_id in self._list_content_ids():
            remaining = max_matches - len(results)
            if remaining <= 0:
                break
            results.extend(self.grep(content_id, pattern, context=context, max_matches=remaining))

        return results

    async def agrep_all(
        self,
        pattern: str,
        context: int = 2,
        max_matches: int = 50,
    ) -> List[GrepResult]:
        """Async variant of grep_all."""
        try:
            re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            log_warning(f"Invalid regex pattern '{pattern}': {e}")
            return []

        results: List[GrepResult] = []
        for content_id in await self._alist_content_ids():
            remaining = max_matches - len(results)
            if remaining <= 0:
                break
            results.extend(await self.agrep(content_id, pattern, context=context, max_matches=remaining))

        return results

    def get_tools(self) -> List[Any]:
        """Return read_backup and grep_backup Function tools for the agent."""
        from agno.tools.function import Function

        store = self

        def read_backup(content_id: str, offset: int = 0, limit: int = 200) -> str:
            """Read a document from the backup store with line-based pagination.

            Args:
                content_id: The ID of the document to read.
                offset: Line number to start from (0-based). Default: 0
                limit: Maximum number of lines to return. Default: 200

            Returns:
                str: The document content with line numbers, or an error message.
            """
            result = store.read(content_id=content_id, offset=offset, limit=limit)
            if result is None:
                return f"Document '{content_id}' not found in backup store."
            return result

        async def aread_backup(content_id: str, offset: int = 0, limit: int = 200) -> str:
            """Read a document from the backup store (async)."""
            result = await store.aread(content_id=content_id, offset=offset, limit=limit)
            if result is None:
                return f"Document '{content_id}' not found in backup store."
            return result

        def grep_backup(pattern: str, content_id: Optional[str] = None) -> str:
            """Search for a pattern in backup documents using regex.

            Args:
                pattern: Regex pattern to search for.
                content_id: If provided, search only this document. Otherwise search all documents.

            Returns:
                str: Matching lines with context, or a message if no matches found.
            """
            if content_id:
                results = store.grep(content_id=content_id, pattern=pattern)
            else:
                results = store.grep_all(pattern=pattern)

            if not results:
                return f"No matches found for pattern '{pattern}'."

            parts = []
            for result in results:
                parts.append(f"[{result.content_id}:{result.line_number}]")
                parts.append(result.to_str())
            return "\n".join(parts)

        async def agrep_backup(pattern: str, content_id: Optional[str] = None) -> str:
            """Search for a pattern in backup documents (async)."""
            if content_id:
                results = await store.agrep(content_id=content_id, pattern=pattern)
            else:
                results = await store.agrep_all(pattern=pattern)

            if not results:
                return f"No matches found for pattern '{pattern}'."

            parts = []
            for result in results:
                parts.append(f"[{result.content_id}:{result.line_number}]")
                parts.append(result.to_str())
            return "\n".join(parts)

        read_tool = Function(
            name="read_backup",
            description="Read a document from the knowledge backup store with line-based pagination.",
            entrypoint=read_backup,
            async_entrypoint=aread_backup,
        )

        grep_tool = Function(
            name="grep_backup",
            description="Search for a regex pattern in one or all backup documents.",
            entrypoint=grep_backup,
            async_entrypoint=agrep_backup,
        )

        log_debug("Created read_backup and grep_backup tools from GCSBackupStore")
        return [read_tool, grep_tool]
