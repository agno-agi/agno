import json
import os
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from uuid import uuid4

from agno.exceptions import PathSecurityError
from agno.tools import Toolkit
from agno.tools._local_file_utils import DEFAULT_EXCLUDE_PATTERNS, path_matches_exclude
from agno.utils.log import log_debug, log_error
from agno.utils.path_safety import safe_join_relative_path

TEXT_EXTENSIONS = {
    ".md",
    ".txt",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".py",
    ".js",
    ".ts",
    ".html",
    ".css",
    ".sql",
    ".sh",
    ".toml",
    ".cfg",
    ".ini",
    ".log",
    ".rst",
}


def _format_size(size: int) -> str:
    """Format a file size in bytes to a human-readable string."""
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.1f}{unit}" if unit != "B" else f"{size}{unit}"
        size /= 1024  # type: ignore
    return f"{size:.1f}GB"


def _extract_snippet(content: str, query: str, context_chars: int = 200) -> str:
    """Extract a snippet of content around the first occurrence of query."""
    lower_content = content.lower()
    lower_query = query.lower()
    idx = lower_content.find(lower_query)
    if idx == -1:
        return ""
    start = max(0, idx - context_chars)
    end = min(len(content), idx + len(query) + context_chars)
    snippet = content[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet = snippet + "..."
    return snippet


class FileTools(Toolkit):
    """Toolkit for read/write access to a local directory tree.

    By default, results from ``list_files``, ``search_files``, and ``search_content``
    skip common noise directories (``.venv``, ``.venvs``, ``.context``,
    ``.git``, ``__pycache__``, ``node_modules``, etc.). See
    ``DEFAULT_EXCLUDE_PATTERNS`` for the full list.

    To customize:
    - Pass ``exclude_patterns=[...]`` with your own list of fnmatch-style patterns.
    - Pass ``exclude_patterns=[]`` to disable exclusion entirely (prior behavior).

    Each pattern is matched with ``fnmatch`` against *any path component* of the
    file's path relative to ``base_dir``. A file is excluded if any component
    matches any pattern, so ``.git`` will exclude both ``.git/`` at the root
    and ``vendor/thing/.git/`` nested deep.

    Note: ``exclude_patterns`` does not parse ``.gitignore`` files — it only
    applies the literal patterns provided.
    """

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        default_extension: str = "txt",
        restrict_to_base_dir: bool = True,
        save_file: bool = False,
        read_file: bool = True,
        delete_file: bool = False,
        list_files: bool = True,
        search_files: bool = True,
        read_file_chunk: bool = True,
        replace_file_chunk: bool = False,
        search_content: bool = True,
        expose_base_directory: bool = False,
        max_file_length: int = 400000,
        max_file_lines: int = 8000,
        line_separator: str = "\n",
        exclude_patterns: Optional[List[str]] = None,
        all: bool = False,
        **kwargs,
    ):
        """Initialize FileTools for local file system operations.

        Args:
            base_dir: Root directory for all file operations. Defaults to cwd.
            default_extension: Extension appended to auto-generated file names.
            restrict_to_base_dir: If True, all paths must stay within base_dir.
            save_file: Enable the save_file tool.
            read_file: Enable the read_file tool.
            delete_file: Enable the delete_file tool.
            list_files: Enable the list_files tool.
            search_files: Enable the search_files tool.
            read_file_chunk: Enable the read_file_chunk tool.
            replace_file_chunk: Enable the replace_file_chunk tool.
            search_content: Enable the search_content tool.
            expose_base_directory: Include base_dir in search results.
            max_file_length: Max file size for read_file (chars).
            max_file_lines: Max file lines for read_file.
            line_separator: Line separator for chunked operations.
            exclude_patterns: Patterns to exclude from list/search operations.
            all: Enable all tools.
        """
        self.base_dir: Path = Path(base_dir).resolve() if base_dir else Path.cwd().resolve()
        self.restrict_to_base_dir = restrict_to_base_dir
        self.default_extension = default_extension.lstrip(".")

        tools: List[Callable] = []
        self.max_file_length = max_file_length
        self.max_file_lines = max_file_lines
        self.line_separator = line_separator
        self.expose_base_directory = expose_base_directory
        self.exclude_patterns: List[str] = (
            exclude_patterns if exclude_patterns is not None else list(DEFAULT_EXCLUDE_PATTERNS)
        )
        if all or save_file:
            tools.append(self.save_file)
        if all or read_file:
            tools.append(self.read_file)
        if all or list_files:
            tools.append(self.list_files)
        if all or search_files:
            tools.append(self.search_files)
        if all or delete_file:
            tools.append(self.delete_file)
        if all or read_file_chunk:
            tools.append(self.read_file_chunk)
        if all or replace_file_chunk:
            tools.append(self.replace_file_chunk)
        if all or search_content:
            tools.append(self.search_content)

        super().__init__(name="file_tools", tools=tools, **kwargs)

    def _is_excluded(self, path: Path) -> bool:
        """Return True if any component of ``path`` (relative to ``base_dir``) matches an exclude pattern."""
        return path_matches_exclude(path, self.base_dir, self.exclude_patterns)

    def check_escape(self, relative_path: str) -> Tuple[bool, Path]:
        """Check if a file path is within the base directory.

        Args:
            relative_path: The file name or relative path to check.

        Returns:
            Tuple of (is_safe, resolved_path).
        """
        return self._check_path(relative_path, self.base_dir, self.restrict_to_base_dir)

    def save_file(
        self,
        contents: str,
        file_name: Optional[str] = None,
        overwrite: bool = True,
        encoding: str = "utf-8",
        extension: Optional[str] = None,
    ) -> str:
        """Save contents to a file.

        Args:
            contents: The contents to save.
            file_name: The name of the file, saved exactly as given. Auto-generated UUID if not provided.
            overwrite: Overwrite the file if it already exists.
            encoding: File encoding. Defaults to utf-8.
            extension: Force this file extension, replacing any existing one.

        Returns:
            JSON with file path and status or error.
        """
        try:
            generated_name = file_name is None
            file_name = file_name or str(uuid4())
            if extension:
                full_name = str(Path(file_name).with_suffix("." + extension.lstrip(".")))
            elif generated_name and self.default_extension:
                full_name = f"{file_name}.{self.default_extension}"
            else:
                # Explicit names are saved exactly as given (Makefile stays Makefile)
                full_name = file_name

            safe, file_path = self.check_escape(full_name)
            if not safe:
                log_error(f"Attempted to save file: {full_name}")
                return json.dumps({"error": "Path is outside base directory"})
            log_debug(f"Saving contents to {file_path}")
            if not file_path.parent.exists():
                file_path.parent.mkdir(parents=True, exist_ok=True)
            if file_path.exists() and not overwrite:
                return json.dumps({"error": f"File {full_name} already exists"})
            file_path.write_text(contents, encoding=encoding)
            log_debug(f"Saved: {file_path}")
            return json.dumps({"file_path": str(file_path), "status": "saved"})
        except Exception as e:
            log_error(f"Error saving to file: {str(e)}")
            return json.dumps({"error": str(e)})

    def read_file_chunk(self, file_name: str, start_line: int, end_line: int, encoding: str = "utf-8") -> str:
        """Read a range of lines from a file.

        Args:
            file_name: The name of the file to read.
            start_line: First line number to read.
            end_line: Last line number to read.
            encoding: File encoding. Defaults to utf-8.

        Returns:
            The file contents or JSON error.
        """
        try:
            log_debug(f"Reading file: {file_name}")
            safe, file_path = self.check_escape(file_name)
            if not safe:
                log_error(f"Attempted to read file: {file_name}")
                return json.dumps({"error": "Path is outside base directory"})
            contents = file_path.read_text(encoding=encoding)
            lines = contents.split(self.line_separator)
            return self.line_separator.join(lines[start_line : end_line + 1])
        except Exception as e:
            log_error(f"Error reading file: {str(e)}")
            return json.dumps({"error": str(e)})

    def replace_file_chunk(
        self, file_name: str, start_line: int, end_line: int, chunk: str, encoding: str = "utf-8"
    ) -> str:
        """Replace a range of lines in a file with new content.

        Args:
            file_name: The name of the file to process.
            start_line: First line number to replace.
            end_line: Last line number to replace.
            chunk: Content to insert (can have multiple lines).
            encoding: File encoding. Defaults to utf-8.

        Returns:
            JSON with file name or error.
        """
        try:
            log_debug(f"Patching file: {file_name}")
            safe, file_path = self.check_escape(file_name)
            if not safe:
                log_error(f"Attempted to read file: {file_name}")
                return json.dumps({"error": "Path is outside base directory"})
            contents = file_path.read_text(encoding=encoding)
            lines = contents.split(self.line_separator)
            start = lines[0:start_line]
            end = lines[end_line + 1 :]
            return self.save_file(
                file_name=file_name, contents=self.line_separator.join(start + [chunk] + end), encoding=encoding
            )
        except Exception as e:
            log_error(f"Error patching file: {str(e)}")
            return json.dumps({"error": str(e)})

    def read_file(self, file_name: str, encoding: str = "utf-8") -> str:
        """Read the contents of a file.

        Args:
            file_name: The name of the file to read.
            encoding: File encoding. Defaults to utf-8.

        Returns:
            The file contents or JSON error.
        """
        try:
            log_debug(f"Reading file: {file_name}")
            safe, file_path = self.check_escape(file_name)
            if not safe:
                log_error(f"Attempted to read file: {file_name}")
                return json.dumps({"error": "Path is outside base directory"})
            contents = file_path.read_text(encoding=encoding)
            if len(contents) > self.max_file_length:
                return json.dumps({"error": "File too long. Use read_file_chunk instead"})
            if len(contents.split(self.line_separator)) > self.max_file_lines:
                return json.dumps({"error": "File too long. Use read_file_chunk instead"})
            return contents
        except Exception as e:
            log_error(f"Error reading file: {str(e)}")
            return json.dumps({"error": str(e)})

    def delete_file(self, file_name: str) -> str:
        """Delete a file.

        Args:
            file_name: Name of the file to delete.

        Returns:
            JSON with status or error.
        """
        safe, path = self.check_escape(file_name)
        try:
            if safe:
                if path.is_dir():
                    path.rmdir()
                    return json.dumps({"file": file_name, "status": "deleted"})
                path.unlink()
                return json.dumps({"file": file_name, "status": "deleted"})
            else:
                log_error(f"Attempt to delete file outside {self.base_dir}: {file_name}")
                return json.dumps({"error": "Path is outside base directory"})
        except Exception as e:
            log_error(f"Error removing {file_name}: {str(e)}")
            return json.dumps({"error": str(e)})

    def list_files(self, directory: str = ".") -> str:
        """List files in a directory.

        Args:
            directory: Directory to list. Defaults to current directory.

        Returns:
            JSON with files array or error.
        """
        try:
            d = self.base_dir
            if directory:
                safe, d = self.check_escape(directory)
                if not safe:
                    return json.dumps({"error": "Path is outside base directory"})
            log_debug(f"Reading files in : {d}")
            files = []
            for file_path in d.iterdir():
                rel_path = file_path.relative_to(self.base_dir).as_posix()
                try:
                    safe_join_relative_path(self.base_dir, rel_path)
                except PathSecurityError:
                    continue
                if self._is_excluded(file_path):
                    continue
                files.append(rel_path)
            return json.dumps({"directory": directory, "files": files})
        except Exception as e:
            log_error(f"Error reading files: {str(e)}")
            return json.dumps({"error": str(e)})

    def search_files(self, pattern: str) -> str:
        """Search for files matching a glob pattern.

        Args:
            pattern: Glob pattern (e.g. "*.txt", "**/*.py").

        Returns:
            JSON with matching file paths.
        """
        try:
            if not pattern or not pattern.strip():
                return json.dumps({"error": "Pattern cannot be empty"})

            log_debug(f"Searching files in {self.base_dir} with pattern {pattern}")
            matching_files = []
            for p in self.base_dir.glob(pattern):
                try:
                    safe_join_relative_path(self.base_dir, p.relative_to(self.base_dir).as_posix())
                except PathSecurityError:
                    continue
                if not self._is_excluded(p):
                    matching_files.append(p)
            result = None
            if self.expose_base_directory:
                file_paths = [str(file_path) for file_path in matching_files]
                result = {
                    "pattern": pattern,
                    "matches_found": len(file_paths),
                    "base_directory": str(self.base_dir),
                    "files": file_paths,
                }
            else:
                file_paths = [file_path.relative_to(self.base_dir).as_posix() for file_path in matching_files]

                result = {
                    "pattern": pattern,
                    "matches_found": len(file_paths),
                    "files": file_paths,
                }
            log_debug(f"Found {len(file_paths)} files matching pattern {pattern}")
            return json.dumps(result, indent=2)

        except Exception as e:
            log_error(f"Error searching files with pattern '{pattern}': {e}")
            return json.dumps({"error": str(e)})

    def search_content(self, query: str, directory: Optional[str] = None, limit: int = 10) -> str:
        """Search file contents for a query string (case-insensitive).

        Only text files under 500KB are searched.

        Args:
            query: Text to search for.
            directory: Subdirectory to scope the search to.
            limit: Maximum matching files to return. Defaults to 10.

        Returns:
            JSON with file paths, sizes, and content snippets.
        """
        try:
            if not query or not query.strip():
                return json.dumps({"error": "Query cannot be empty"})

            search_dir = self.base_dir
            if directory:
                safe, search_dir = self.check_escape(directory)
                if not safe:
                    log_error(f"Attempted to search outside base directory: {directory}")
                    return json.dumps({"error": "Directory is outside base directory"})

            if not search_dir.is_dir():
                return json.dumps({"error": f"'{directory}' is not a directory"})

            log_debug(f"Searching file contents in {search_dir} for '{query}'")
            lower_query = query.lower()
            matches: List[dict] = []
            max_file_size = 500 * 1024  # 500KB

            walk_done = False
            for dirpath, dirnames, filenames in os.walk(search_dir):
                if walk_done:
                    break
                # Prune excluded directories in place so os.walk doesn't descend into them.
                dirnames[:] = [d for d in dirnames if not self._is_excluded(Path(dirpath) / d)]
                for filename in filenames:
                    if len(matches) >= limit:
                        walk_done = True
                        break
                    file_path = Path(dirpath) / filename
                    try:
                        safe_join_relative_path(self.base_dir, file_path.relative_to(self.base_dir).as_posix())
                    except PathSecurityError:
                        continue
                    if self._is_excluded(file_path):
                        continue
                    if file_path.suffix.lower() not in TEXT_EXTENSIONS:
                        continue
                    try:
                        if file_path.stat().st_size > max_file_size:
                            continue
                    except OSError:
                        continue

                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                    except Exception:
                        continue

                    if lower_query in content.lower():
                        rel_path = file_path.relative_to(self.base_dir).as_posix()
                        snippet = _extract_snippet(content, query)
                        matches.append(
                            {
                                "file": rel_path,
                                "size": _format_size(file_path.stat().st_size),
                                "snippet": snippet,
                            }
                        )

            result = {
                "query": query,
                "matches_found": len(matches),
                "files": matches,
            }
            log_debug(f"Found {len(matches)} files containing '{query}'")
            return json.dumps(result, indent=2)

        except Exception as e:
            log_error(f"Error searching content for '{query}': {e}")
            return json.dumps({"error": str(e)})
