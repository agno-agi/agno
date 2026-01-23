"""
FileSystem Knowledge
====================
A Knowledge implementation that allows retrieval from files in a local directory.

Implements the KnowledgeProtocol and provides three tools:
- grep_file: Search for patterns in file contents
- list_files: List files matching a glob pattern
- get_file: Read the full contents of a specific file
"""

from dataclasses import dataclass, field
from os import walk as os_walk
from os.path import isabs as path_isabs
from pathlib import Path
from re import IGNORECASE
from re import compile as re_compile
from re import error as re_error
from re import escape as re_escape
from typing import Any, List, Optional

from agno.knowledge.document import Document
from agno.utils.log import log_debug, log_warning


@dataclass
class FileSystemKnowledge:
    """Knowledge implementation that searches files in a local directory.

    Implements the KnowledgeProtocol and provides three tools to agents:
    - grep_file(query): Search for patterns in file contents
    - list_files(pattern): List files matching a glob pattern
    - get_file(path): Read the full contents of a specific file

    Example:
        ```python
        from agno.agent import Agent
        from agno.knowledge.filesystem import FileSystemKnowledge
        from agno.models.openai import OpenAIChat

        # Create knowledge for a directory
        fs_knowledge = FileSystemKnowledge(base_dir="/path/to/code")

        # Agent automatically gets grep_file, list_files, get_file tools
        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),
            knowledge=fs_knowledge,
            search_knowledge=True,
        )

        # Agent can now search, list, and read files
        agent.print_response("Find where main() is defined")
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

        for root, dirs, files in os_walk(self.base_path):
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
        if path_isabs(query):
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
            pattern = re_compile(query, IGNORECASE)
        except re_error:
            # If not a valid regex, treat as literal string
            pattern = re_compile(re_escape(query), IGNORECASE)

        for root, dirs, files in os_walk(self.base_path):
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

    # ========================================================================
    # Protocol Implementation (build_context, get_tools, retrieve)
    # ========================================================================

    def build_context(self, **kwargs) -> str:
        """Build context string for the agent's system prompt.

        Returns instructions about the three available filesystem tools.

        Args:
            **kwargs: Additional context (unused).

        Returns:
            Context string describing available tools.
        """
        from textwrap import dedent

        return dedent(
            f"""
            You have access to a filesystem knowledge base containing documents at: {self.base_dir}
            
            IMPORTANT: You MUST use these tools to search and read files before answering questions.
            Do NOT answer from your own knowledge - always search the files first.

            Available tools:
            - grep_file(query): Search for keywords or patterns in file contents. Use this to find relevant information.
            - list_files(pattern): List available files. Use "*" to see all files, or "*.md" for specific types.
            - get_file(path): Read the full contents of a specific file.

            When answering questions:
            1. First use grep_file to search for relevant terms in the documents
            2. Or use list_files to see what documents are available, then get_file to read them
            3. Base your answer on what you find in the files
            """
        ).strip()

    def get_tools(self, **kwargs) -> List[Any]:
        """Get tools to expose to the agent.

        Returns three filesystem tools: grep_file, list_files, get_file.

        Args:
            **kwargs: Additional context (unused).

        Returns:
            List of filesystem tools.
        """
        return [
            self._create_grep_tool(),
            self._create_list_files_tool(),
            self._create_get_file_tool(),
        ]

    async def aget_tools(self, **kwargs) -> List[Any]:
        """Async version of get_tools."""
        return self.get_tools(**kwargs)

    def _create_grep_tool(self) -> Any:
        """Create the grep_file tool."""
        from agno.tools.function import Function

        def grep_file(query: str, max_results: int = 20) -> str:
            """Search the knowledge base files for a keyword or pattern.

            Use this tool to find information in the documents. Search for relevant
            terms from the user's question to find answers.

            Args:
                query: The keyword or pattern to search for (e.g., "coffee", "cappuccino", "brewing").
                max_results: Maximum number of files to return (default: 20).

            Returns:
                Matching content from files with context around each match.
            """
            docs = self._grep(query, max_results=max_results)

            if not docs:
                return f"No matches found for: {query}"

            results = []
            for doc in docs:
                results.append(f"### {doc.name}\n{doc.content}")

            return "\n\n".join(results)

        return Function.from_callable(grep_file, name="grep_file")

    def _create_list_files_tool(self) -> Any:
        """Create the list_files tool."""
        from agno.tools.function import Function

        def list_files(pattern: str = "*", max_results: int = 50) -> str:
            """List available files in the knowledge base.

            Use this to see what documents are available to search.

            Args:
                pattern: Glob pattern to match (e.g., "*.md", "*.txt"). Default: "*" for all files.
                max_results: Maximum number of files to return (default: 50).

            Returns:
                List of available file paths.
            """
            docs = self._list_files(pattern, max_results=max_results)

            if not docs:
                return f"No files found matching: {pattern}"

            file_list = [doc.name for doc in docs]
            return f"Found {len(file_list)} files:\n" + "\n".join(f"- {f}" for f in file_list)

        return Function.from_callable(list_files, name="list_files")

    def _create_get_file_tool(self) -> Any:
        """Create the get_file tool."""
        from agno.tools.function import Function

        def get_file(path: str) -> str:
            """Read the full contents of a document from the knowledge base.

            Use this after list_files to read a specific document.

            Args:
                path: Path to the file (e.g., "coffee.md", "guide.txt").

            Returns:
                The full file contents.
            """
            docs = self._get_file(path)

            if not docs:
                return f"File not found: {path}"

            doc = docs[0]
            return f"### {doc.name}\n```\n{doc.content}\n```"

        return Function.from_callable(get_file, name="get_file")

    def retrieve(
        self,
        query: str,
        max_results: Optional[int] = None,
        **kwargs,
    ) -> List[Document]:
        """Retrieve documents for context injection.

        Uses grep as the default retrieval method since it's most likely
        to return relevant results for a natural language query.

        Args:
            query: The query string.
            max_results: Maximum number of results.
            **kwargs: Additional parameters.

        Returns:
            List of Document objects.
        """
        return self._grep(query, max_results=max_results or 10)

    async def aretrieve(
        self,
        query: str,
        max_results: Optional[int] = None,
        **kwargs,
    ) -> List[Document]:
        """Async version of retrieve."""
        return self.retrieve(query, max_results=max_results, **kwargs)
