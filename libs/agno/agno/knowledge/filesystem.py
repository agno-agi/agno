"""
FileSystem Knowledge
====================
A knowledge implementation that searches files in a local directory.

Supports three search modes via the `mode` kwarg:
- "list_files": List all files in the directory
- "get_file": Get the contents of a specific file
- "grep": Search for a query pattern within files (default)
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Literal, Optional

from agno.knowledge.document import Document
from agno.utils.log import log_debug, log_warning


@dataclass
class FileSystemKnowledge:
    """Knowledge implementation that searches files in a local directory.

    This class implements the KnowledgeBase protocol and provides three search modes.
    Mode can be specified via kwarg or query prefix:
    - "list_files" / "list:": List all files matching the query pattern (glob)
    - "get_file" / "file:": Get the contents of a specific file
    - "grep" / "grep:" or no prefix: Search for pattern within file contents (default)

    Example:
        ```python
        from agno.knowledge.filesystem import FileSystemKnowledge

        # Create knowledge base for a directory
        fs_knowledge = FileSystemKnowledge(base_dir="/path/to/docs")

        # Using mode parameter
        files = fs_knowledge.search("*.py", mode="list_files")
        content = fs_knowledge.search("README.md", mode="get_file")

        # Using query prefixes (works with agent's search_knowledge_base tool)
        files = fs_knowledge.search("list:*.py")
        content = fs_knowledge.search("file:README.md")
        results = fs_knowledge.search("grep:def main")
        results = fs_knowledge.search("def main")  # grep is default
        ```
    """

    base_dir: str
    max_results: int = 50
    include_patterns: List[str] = field(default_factory=list)
    exclude_patterns: List[str] = field(
        default_factory=lambda: [".git", "__pycache__", "node_modules", ".venv", "venv"]
    )

    def __post_init__(self):
        self.base_path = Path(self.base_dir).resolve()
        if not self.base_path.exists():
            raise ValueError(f"Directory does not exist: {self.base_dir}")
        if not self.base_path.is_dir():
            raise ValueError(f"Path is not a directory: {self.base_dir}")

    def _should_include_file(self, file_path: Path) -> bool:
        """Check if a file should be included based on patterns."""
        path_str = str(file_path)

        # Check exclude patterns
        for pattern in self.exclude_patterns:
            if pattern in path_str:
                return False

        # Check include patterns (if specified)
        if self.include_patterns:
            import fnmatch

            for pattern in self.include_patterns:
                if fnmatch.fnmatch(file_path.name, pattern):
                    return True
            return False

        return True

    def _list_files(self, query: str, max_results: Optional[int] = None) -> List[Document]:
        """List files matching the query pattern (glob-style)."""
        import fnmatch

        results: List[Document] = []
        limit = max_results or self.max_results

        for root, dirs, files in os.walk(self.base_path):
            # Filter out excluded directories
            dirs[:] = [d for d in dirs if not any(excl in d for excl in self.exclude_patterns)]

            for filename in files:
                if len(results) >= limit:
                    break

                file_path = Path(root) / filename
                if not self._should_include_file(file_path):
                    continue

                rel_path = file_path.relative_to(self.base_path)

                # Match against query pattern (check both filename and relative path)
                if query and query != "*":
                    if not (fnmatch.fnmatch(filename, query) or fnmatch.fnmatch(str(rel_path), query)):
                        continue
                results.append(
                    Document(
                        name=str(rel_path),
                        content=str(rel_path),
                        meta_data={
                            "type": "file_listing",
                            "absolute_path": str(file_path),
                            "extension": file_path.suffix,
                            "size": file_path.stat().st_size,
                        },
                    )
                )

            if len(results) >= limit:
                break

        log_debug(f"Found {len(results)} files matching pattern: {query}")
        return results

    def _get_file(self, query: str) -> List[Document]:
        """Get the contents of a specific file."""
        # Handle both relative and absolute paths
        if os.path.isabs(query):
            file_path = Path(query)
        else:
            file_path = self.base_path / query

        if not file_path.exists():
            log_warning(f"File not found: {query}")
            return []

        if not file_path.is_file():
            log_warning(f"Path is not a file: {query}")
            return []

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            rel_path = file_path.relative_to(self.base_path) if file_path.is_relative_to(self.base_path) else file_path

            return [
                Document(
                    name=str(rel_path),
                    content=content,
                    meta_data={
                        "type": "file_content",
                        "absolute_path": str(file_path),
                        "extension": file_path.suffix,
                        "size": len(content),
                        "lines": content.count("\n") + 1,
                    },
                )
            ]
        except Exception as e:
            log_warning(f"Error reading file {query}: {e}")
            return []

    def _grep(self, query: str, max_results: Optional[int] = None) -> List[Document]:
        """Search for a pattern within file contents."""
        results: List[Document] = []
        limit = max_results or self.max_results

        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error:
            # If not a valid regex, treat as literal string
            pattern = re.compile(re.escape(query), re.IGNORECASE)

        for root, dirs, files in os.walk(self.base_path):
            # Filter out excluded directories
            dirs[:] = [d for d in dirs if not any(excl in d for excl in self.exclude_patterns)]

            for filename in files:
                if len(results) >= limit:
                    break

                file_path = Path(root) / filename
                if not self._should_include_file(file_path):
                    continue

                try:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                    matches = list(pattern.finditer(content))

                    if matches:
                        # Extract matching lines with context
                        lines = content.split("\n")
                        matching_lines: List[dict[str, Any]] = []

                        for match in matches[:10]:  # Limit matches per file
                            # Find the line number
                            line_start = content.count("\n", 0, match.start())
                            line_num = line_start + 1

                            # Get context (1 line before and after)
                            start_idx = max(0, line_start - 1)
                            end_idx = min(len(lines), line_start + 2)
                            context_lines = lines[start_idx:end_idx]

                            matching_lines.append(
                                {
                                    "line": line_num,
                                    "match": match.group(),
                                    "context": "\n".join(context_lines),
                                }
                            )

                        rel_path = file_path.relative_to(self.base_path)
                        results.append(
                            Document(
                                name=str(rel_path),
                                content="\n---\n".join(str(m["context"]) for m in matching_lines),
                                meta_data={
                                    "type": "grep_result",
                                    "absolute_path": str(file_path),
                                    "match_count": len(matches),
                                    "matches": matching_lines[:5],  # Include first 5 match details
                                },
                            )
                        )

                except Exception as e:
                    # Skip files that can't be read (binary, permissions, etc.)
                    log_debug(f"Skipping file {file_path}: {e}")
                    continue

            if len(results) >= limit:
                break

        log_debug(f"Found {len(results)} files with matches for: {query}")
        return results

    def search(
        self,
        query: str,
        mode: Optional[Literal["list_files", "get_file", "grep"]] = None,
        max_results: Optional[int] = None,
        **kwargs,
    ) -> List[Document]:
        """Search for documents in the filesystem.

        Args:
            query: The search query. Can include a mode prefix:
                - "list:*.py" - list files matching glob pattern
                - "file:path/to/file.py" - get contents of a specific file
                - "grep:pattern" or just "pattern" - search file contents
            mode: Search mode. One of "list_files", "get_file", or "grep".
                  If not provided, will be inferred from query prefix.
            max_results: Maximum number of results to return.
            **kwargs: Additional parameters (unused, for protocol compatibility).

        Returns:
            List of Document objects with search results.
        """
        # Parse mode from query prefix if not explicitly provided
        if mode is None:
            if query.startswith("list:"):
                mode = "list_files"
                query = query[5:].strip()
            elif query.startswith("file:"):
                mode = "get_file"
                query = query[5:].strip()
            elif query.startswith("grep:"):
                mode = "grep"
                query = query[5:].strip()
            else:
                mode = "grep"  # Default to grep

        if mode == "list_files":
            return self._list_files(query, max_results)
        elif mode == "get_file":
            return self._get_file(query)
        elif mode == "grep":
            return self._grep(query, max_results)
        else:
            log_warning(f"Unknown search mode: {mode}")
            return []

    async def asearch(
        self,
        query: str,
        mode: Optional[Literal["list_files", "get_file", "grep"]] = None,
        max_results: Optional[int] = None,
        **kwargs,
    ) -> List[Document]:
        """Async search for documents in the filesystem.

        This is a simple wrapper around search() since filesystem operations
        are synchronous. For true async file I/O, consider using aiofiles.

        Args:
            query: The search query. Can include a mode prefix (list:, file:, grep:).
            mode: Search mode. One of "list_files", "get_file", or "grep".
            max_results: Maximum number of results to return.
            **kwargs: Additional parameters.

        Returns:
            List of Document objects with search results.
        """
        # For now, just delegate to sync version
        # Could be enhanced with aiofiles for true async I/O
        return self.search(query, mode=mode, max_results=max_results, **kwargs)
