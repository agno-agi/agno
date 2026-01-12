"""
FileSystem Knowledge Base
=========================
A knowledge base implementation for searching filesystem contents.

Implements the KnowledgeBase protocol, enabling agents to search files
without needing a vector database.

Example:
    ```python
    from pathlib import Path
    from agno.knowledge.filesystem import FileSystemKnowledge
    from agno.agent import Agent

    knowledge = FileSystemKnowledge(
        base_dir=Path("./my_project"),
        include_patterns=["*.py", "*.txt"],
        exclude_patterns=["__pycache__", "*.pyc"],
    )

    agent = Agent(knowledge=knowledge)

    # Grep search (default) - search file contents
    agent.print_response("Find files containing 'def main'")

    # Filename search - search by filename pattern
    agent.print_response("Find all config files", search_type="filename")
    ```
"""

import fnmatch
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from agno.knowledge.document import Document
from agno.utils.log import log_debug, log_warning


@dataclass
class FileSystemKnowledge:
    """Knowledge base for filesystem search.

    Implements the KnowledgeBase protocol for searching files in a directory.
    Supports two search types:
    - grep: Search file contents for a pattern (default)
    - filename: Search for files matching a glob pattern

    Attributes:
        base_dir: Root directory for searches. All paths are validated to stay within this directory.
        max_results: Maximum number of documents to return (default: 10).
        recursive: Whether to search subdirectories (default: True).
        include_patterns: List of glob patterns for files to include (e.g., ["*.py", "*.txt"]).
        exclude_patterns: List of glob patterns for files/dirs to exclude (e.g., ["__pycache__", "*.pyc"]).
    """

    base_dir: Path
    max_results: int = 10
    recursive: bool = True
    include_patterns: Optional[List[str]] = None
    exclude_patterns: Optional[List[str]] = field(
        default_factory=lambda: ["__pycache__", "*.pyc", ".git", "node_modules", ".venv", "venv"]
    )

    def __post_init__(self):
        """Validate and resolve base_dir to absolute path."""
        if isinstance(self.base_dir, str):
            self.base_dir = Path(self.base_dir)
        self.base_dir = self.base_dir.resolve()

        if not self.base_dir.exists():
            raise ValueError(f"base_dir does not exist: {self.base_dir}")
        if not self.base_dir.is_dir():
            raise ValueError(f"base_dir is not a directory: {self.base_dir}")

    # ==========================================
    # PUBLIC API - SEARCH METHODS
    # ==========================================

    def search(
        self,
        query: str,
        search_type: str = "grep",
        max_results: Optional[int] = None,
        case_sensitive: bool = False,
        **kwargs,
    ) -> List[Document]:
        """Search for documents in the filesystem.

        Args:
            query: The search query. For grep: regex pattern to search in file contents.
                   For filename: glob pattern to match filenames.
            search_type: Type of search - "grep" (default) or "filename".
            max_results: Maximum number of results to return. Defaults to self.max_results.
            case_sensitive: Whether grep search is case-sensitive (default: False).
            **kwargs: Additional arguments (ignored, for protocol compatibility).

        Returns:
            List of Document objects matching the query.
        """
        if not query or not query.strip():
            log_warning("Empty search query provided")
            return []

        _max_results = max_results if max_results is not None else self.max_results
        log_debug(f"FileSystemKnowledge search: query='{query}', type={search_type}, max={_max_results}")

        if search_type == "filename":
            return self._search_filename(query, _max_results)
        elif search_type == "grep":
            return self._search_grep(query, _max_results, case_sensitive)
        else:
            log_warning(f"Unknown search_type '{search_type}', defaulting to grep")
            return self._search_grep(query, _max_results, case_sensitive)

    async def asearch(
        self,
        query: str,
        search_type: str = "grep",
        max_results: Optional[int] = None,
        case_sensitive: bool = False,
        **kwargs,
    ) -> List[Document]:
        """Async search for documents in the filesystem.

        This is a synchronous implementation wrapped for async compatibility.
        For truly async file operations, consider using aiofiles.

        Args:
            query: The search query.
            search_type: Type of search - "grep" (default) or "filename".
            max_results: Maximum number of results to return.
            case_sensitive: Whether grep search is case-sensitive.
            **kwargs: Additional arguments (ignored, for protocol compatibility).

        Returns:
            List of Document objects matching the query.
        """
        # For now, delegate to sync implementation
        # Could be made truly async with aiofiles if needed
        return self.search(
            query=query,
            search_type=search_type,
            max_results=max_results,
            case_sensitive=case_sensitive,
            **kwargs,
        )

    # ==========================================
    # PRIVATE - SEARCH IMPLEMENTATIONS
    # ==========================================

    def _search_grep(self, query: str, max_results: int, case_sensitive: bool = False) -> List[Document]:
        """Search file contents for a pattern (grep-style)."""
        documents = []
        flags = 0 if case_sensitive else re.IGNORECASE

        try:
            pattern = re.compile(query, flags)
        except re.error as e:
            log_warning(f"Invalid regex pattern '{query}': {e}. Using literal search.")
            pattern = re.compile(re.escape(query), flags)

        for file_path in self._get_all_files():
            if len(documents) >= max_results:
                break

            content = self._read_file_content(file_path)
            if content is None:
                continue

            # Find all matches with line numbers
            matches = []
            line_numbers = []
            for i, line in enumerate(content.splitlines(), start=1):
                if pattern.search(line):
                    matches.append(line.strip())
                    line_numbers.append(i)

            if matches:
                # Create document with matching content
                rel_path = file_path.relative_to(self.base_dir)
                match_content = "\n".join(f"Line {ln}: {match}" for ln, match in zip(line_numbers, matches))

                documents.append(
                    Document(
                        content=match_content,
                        name=file_path.name,
                        meta_data={
                            "file_path": str(rel_path),
                            "absolute_path": str(file_path),
                            "search_type": "grep",
                            "query": query,
                            "line_numbers": line_numbers,
                            "match_count": len(matches),
                        },
                    )
                )

        return documents

    def _search_filename(self, query: str, max_results: int) -> List[Document]:
        """Search for files matching a glob pattern."""
        documents = []

        # If query doesn't contain glob characters, make it a contains search
        if not any(c in query for c in "*?[]"):
            query = f"*{query}*"

        for file_path in self._get_all_files():
            if len(documents) >= max_results:
                break

            if fnmatch.fnmatch(file_path.name, query):
                content = self._read_file_content(file_path)
                if content is None:
                    content = f"[Binary or unreadable file: {file_path.name}]"

                rel_path = file_path.relative_to(self.base_dir)
                stat = file_path.stat()

                documents.append(
                    Document(
                        content=content,
                        name=file_path.name,
                        meta_data={
                            "file_path": str(rel_path),
                            "absolute_path": str(file_path),
                            "search_type": "filename",
                            "query": query,
                            "file_size": stat.st_size,
                            "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        },
                    )
                )

        return documents

    # ==========================================
    # PRIVATE - HELPER METHODS
    # ==========================================

    def _is_path_safe(self, path: Path) -> bool:
        """Check if a path is within the base directory (security check)."""
        try:
            resolved = path.resolve()
            return resolved.is_relative_to(self.base_dir)
        except (ValueError, RuntimeError):
            return False

    def _should_include_file(self, file_path: Path) -> bool:
        """Check if a file should be included based on include/exclude patterns."""
        rel_path = str(file_path.relative_to(self.base_dir))
        file_name = file_path.name

        # Check exclude patterns against both filename and relative path
        if self.exclude_patterns:
            for pattern in self.exclude_patterns:
                if fnmatch.fnmatch(file_name, pattern) or fnmatch.fnmatch(rel_path, pattern):
                    return False
                # Also check if any parent directory matches
                for part in file_path.relative_to(self.base_dir).parts:
                    if fnmatch.fnmatch(part, pattern):
                        return False

        # Check include patterns (if specified, file must match at least one)
        if self.include_patterns:
            return any(fnmatch.fnmatch(file_name, pattern) for pattern in self.include_patterns)

        return True

    def _is_binary_file(self, file_path: Path, sample_size: int = 8192) -> bool:
        """Check if a file is binary by looking for null bytes."""
        try:
            with open(file_path, "rb") as f:
                chunk = f.read(sample_size)
                return b"\x00" in chunk
        except (IOError, OSError):
            return True

    def _get_all_files(self) -> List[Path]:
        """Get all searchable files in base_dir."""
        files = []
        if self.recursive:
            for root, dirs, filenames in os.walk(self.base_dir):
                # Filter out excluded directories in-place to prevent descending into them
                if self.exclude_patterns:
                    dirs[:] = [
                        d
                        for d in dirs
                        if not any(fnmatch.fnmatch(d, pattern) for pattern in self.exclude_patterns)
                    ]

                for filename in filenames:
                    file_path = Path(root) / filename
                    if self._should_include_file(file_path):
                        files.append(file_path)
        else:
            for item in self.base_dir.iterdir():
                if item.is_file() and self._should_include_file(item):
                    files.append(item)

        return files

    def _read_file_content(self, file_path: Path) -> Optional[str]:
        """Read file content, returning None if file cannot be read."""
        try:
            if self._is_binary_file(file_path):
                log_debug(f"Skipping binary file: {file_path}")
                return None
            return file_path.read_text(encoding="utf-8", errors="replace")
        except (IOError, OSError) as e:
            log_warning(f"Could not read file {file_path}: {e}")
            return None
