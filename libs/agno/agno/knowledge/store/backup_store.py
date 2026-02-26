"""BackupStore — local filesystem store for original documents.

Stores parsed text alongside optional raw bytes so agents can
directly read and grep documents without going through vector search.
Each document gets its own directory under ``base_dir``.

Directory layout::

    base_dir/
        <content_id>/
            parsed.txt      # Parsed text content
            raw.<ext>        # Original file (optional)
            metadata.json    # Content metadata
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from agno.utils.log import log_debug, log_error, log_info, log_warning


@dataclass
class GrepResult:
    """A single match from a grep operation."""

    content_id: str
    line_number: int
    line: str
    context_before: List[str] = field(default_factory=list)
    context_after: List[str] = field(default_factory=list)

    def to_str(self) -> str:
        parts = []
        for ctx in self.context_before:
            parts.append(f"  {ctx}")
        parts.append(f"  {self.line_number}: {self.line}")
        for ctx in self.context_after:
            parts.append(f"  {ctx}")
        return "\n".join(parts)


@dataclass
class BackupStore:
    """Local filesystem store for original document content."""

    base_dir: str = "tmp/knowledge_backup"

    def _content_dir(self, content_id: str) -> Path:
        return Path(self.base_dir) / content_id

    def store(
        self,
        content_id: str,
        parsed_text: str,
        raw_bytes: Optional[bytes] = None,
        file_extension: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Store parsed text and optional raw content for a document."""
        content_dir = self._content_dir(content_id)
        content_dir.mkdir(parents=True, exist_ok=True)

        # Write parsed text
        parsed_path = content_dir / "parsed.txt"
        parsed_path.write_text(parsed_text, encoding="utf-8")
        log_info(f"Stored parsed text for {content_id} ({len(parsed_text)} chars)")

        # Write raw bytes if provided
        if raw_bytes is not None:
            ext = file_extension or ".bin"
            if not ext.startswith("."):
                ext = f".{ext}"
            raw_path = content_dir / f"raw{ext}"
            raw_path.write_bytes(raw_bytes)
            log_debug(f"Stored raw file for {content_id} ({len(raw_bytes)} bytes)")

        # Write metadata
        if metadata:
            meta_path = content_dir / "metadata.json"
            meta_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")

    async def astore(
        self,
        content_id: str,
        parsed_text: str,
        raw_bytes: Optional[bytes] = None,
        file_extension: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Async variant of store. Uses sync I/O internally (local filesystem)."""
        self.store(
            content_id=content_id,
            parsed_text=parsed_text,
            raw_bytes=raw_bytes,
            file_extension=file_extension,
            metadata=metadata,
        )

    def read(
        self,
        content_id: str,
        offset: int = 0,
        limit: int = 200,
    ) -> Optional[str]:
        """Read parsed text for a document with line-based pagination.

        Args:
            content_id: The content ID to read.
            offset: Line number to start from (0-based).
            limit: Maximum number of lines to return.

        Returns:
            The requested lines as a string, or None if not found.
        """
        parsed_path = self._content_dir(content_id) / "parsed.txt"
        if not parsed_path.exists():
            return None

        lines = parsed_path.read_text(encoding="utf-8").splitlines()
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
        return self.read(content_id=content_id, offset=offset, limit=limit)

    def grep(
        self,
        content_id: str,
        pattern: str,
        context: int = 2,
        max_matches: int = 20,
    ) -> List[GrepResult]:
        """Search within a single document's parsed text.

        Args:
            content_id: The content ID to search.
            pattern: Regex pattern to search for.
            context: Number of context lines before and after each match.
            max_matches: Maximum number of matches to return.

        Returns:
            List of GrepResult objects.
        """
        parsed_path = self._content_dir(content_id) / "parsed.txt"
        if not parsed_path.exists():
            return []

        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            log_warning(f"Invalid regex pattern '{pattern}': {e}")
            return []

        lines = parsed_path.read_text(encoding="utf-8").splitlines()
        results: List[GrepResult] = []

        for i, line in enumerate(lines):
            if compiled.search(line):
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

    async def agrep(
        self,
        content_id: str,
        pattern: str,
        context: int = 2,
        max_matches: int = 20,
    ) -> List[GrepResult]:
        """Async variant of grep."""
        return self.grep(content_id=content_id, pattern=pattern, context=context, max_matches=max_matches)

    def grep_all(
        self,
        pattern: str,
        context: int = 2,
        max_matches: int = 50,
    ) -> List[GrepResult]:
        """Search across all stored documents.

        Args:
            pattern: Regex pattern to search for.
            context: Number of context lines before and after each match.
            max_matches: Maximum total matches across all documents.

        Returns:
            List of GrepResult objects from all documents.
        """
        base = Path(self.base_dir)
        if not base.exists():
            return []

        results: List[GrepResult] = []
        for content_dir in sorted(base.iterdir()):
            if not content_dir.is_dir():
                continue
            content_id = content_dir.name
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
        return self.grep_all(pattern=pattern, context=context, max_matches=max_matches)

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
            """Read a document from the backup store (async).

            Args:
                content_id: The ID of the document to read.
                offset: Line number to start from (0-based). Default: 0
                limit: Maximum number of lines to return. Default: 200

            Returns:
                str: The document content with line numbers, or an error message.
            """
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
            """Search for a pattern in backup documents (async).

            Args:
                pattern: Regex pattern to search for.
                content_id: If provided, search only this document. Otherwise search all documents.

            Returns:
                str: Matching lines with context, or a message if no matches found.
            """
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

        log_debug("Created read_backup and grep_backup tools from BackupStore")
        return [read_tool, grep_tool]
