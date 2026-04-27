import json
import os
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error


@dataclass
class _ReadState:
    """Tracks the last-observed mtime of a file and whether the agent saw it
    in full. ``edit_file`` uses both: staleness is detected via mtime, and
    partial reads are rejected because the agent may pick an ``old_text``
    that exists only in unseen lines.

    mtime is stored in nanoseconds because filesystems with coarse mtime
    granularity (HFS+ with 1s precision, some network mounts, older ext4)
    can produce identical mtime values for two writes within the same tick,
    letting a real change slip past the staleness check. Nanosecond precision
    widens the detection window on Linux/modern macOS (APFS) — do not
    downgrade this to seconds without replacing it with a content hash."""

    mtime_ns: int
    is_partial: bool


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

DEFAULT_EXCLUDE_PATTERNS = [
    # Environments and secrets
    ".venv",
    "venv",
    ".env*",
    "*.env",
    # Version control
    ".git",
    ".hg",
    ".svn",
    # Python caches and build artifacts
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".tox",
    ".nox",
    ".ipynb_checkpoints",
    "dist",
    "build",
    "*.egg-info",
    # JavaScript and TypeScript
    "node_modules",
    ".next",
    ".turbo",
    ".nuxt",
    ".svelte-kit",
    ".docusaurus",
    ".parcel-cache",
    ".nyc_output",
    "*.tsbuildinfo",
    ".serverless",
    # JVM (Java, Kotlin, Android, Gradle)
    ".gradle",
    ".kotlin",
    "*.class",
    # Dart and Flutter
    ".dart_tool",
    ".flutter-plugins",
    ".flutter-plugins-dependencies",
    # Swift and Xcode
    ".build",
    "xcuserdata",
    "*.xcuserstate",
    # Ruby
    ".bundle",
    "*.gem",
    ".yardoc",
    # Elixir
    "_build",
    ".elixir_ls",
    # .NET / Visual Studio
    ".vs",
    # Infrastructure as Code (state files hidden by default for security)
    ".terraform",
    "*.tfstate",
    "*.tfstate.*",
    ".terragrunt-cache",
    # OS artifacts
    ".DS_Store",
]


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
    skip common noise directories (``.venv``, ``.git``, ``__pycache__``,
    ``node_modules``, etc.). See ``DEFAULT_EXCLUDE_PATTERNS`` for the full list.

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
        enable_save_file: bool = True,
        enable_read_file: bool = True,
        enable_delete_file: bool = False,
        enable_list_files: bool = True,
        enable_search_files: bool = True,
        enable_read_file_chunk: bool = True,
        enable_replace_file_chunk: bool = True,
        enable_search_content: bool = True,
        enable_edit_file: bool = True,
        expose_base_directory: bool = False,
        max_file_length: int = 10000000,
        max_file_lines: int = 100000,
        line_separator: str = "\n",
        exclude_patterns: Optional[List[str]] = None,
        all: bool = False,
        **kwargs,
    ):
        self.base_dir: Path = (base_dir or Path.cwd()).resolve()

        tools: List[Any] = []
        self.max_file_length = max_file_length
        self.max_file_lines = max_file_lines
        self.line_separator = line_separator
        self.expose_base_directory = expose_base_directory
        self.exclude_patterns: List[str] = (
            exclude_patterns if exclude_patterns is not None else list(DEFAULT_EXCLUDE_PATTERNS)
        )
        self._read_state: Dict[Path, _ReadState] = {}
        if all or enable_save_file:
            tools.append(self.save_file)
        if all or enable_read_file:
            tools.append(self.read_file)
        if all or enable_list_files:
            tools.append(self.list_files)
        if all or enable_search_files:
            tools.append(self.search_files)
        if all or enable_delete_file:
            tools.append(self.delete_file)
        if all or enable_read_file_chunk:
            tools.append(self.read_file_chunk)
        if all or enable_replace_file_chunk:
            tools.append(self.replace_file_chunk)
        if all or enable_search_content:
            tools.append(self.search_content)
        if all or enable_edit_file:
            tools.append(self.edit_file)

        super().__init__(name="file_tools", tools=tools, **kwargs)

    def _record_read(self, path: Path, is_partial: bool) -> None:
        """Cache the current mtime of ``path`` so ``edit_file`` can detect
        external modifications between reads and edits."""
        self._read_state[path] = _ReadState(mtime_ns=path.stat().st_mtime_ns, is_partial=is_partial)

    def _is_excluded(self, path: Path) -> bool:
        """Return True if any component of ``path`` (relative to ``base_dir``) matches an exclude pattern."""
        if not self.exclude_patterns:
            return False
        try:
            rel = path.relative_to(self.base_dir)
        except ValueError:
            return False
        return any(fnmatch(part, pattern) for part in rel.parts for pattern in self.exclude_patterns)

    def check_escape(self, relative_path: str) -> Tuple[bool, Path]:
        """Check if the file path is within the base directory.

        Alias for _check_path maintained for backward compatibility.

        Args:
            relative_path: The file name or relative path to check.

        Returns:
            Tuple of (is_safe, resolved_path). If not safe, returns base_dir as the path.
        """
        return self._check_path(relative_path, self.base_dir)

    def save_file(self, contents: str, file_name: str, overwrite: bool = True, encoding: str = "utf-8") -> str:
        """Saves the contents to a file called `file_name` and returns the file name if successful.

        :param contents: The contents to save.
        :param file_name: The name of the file to save to.
        :param overwrite: Overwrite the file if it already exists.
        :return: The file name if successful, otherwise returns an error message.
        """
        try:
            safe, file_path = self.check_escape(file_name)
            if not (safe):
                log_error(f"Attempted to save file: {file_name}")
                return "Error saving file"
            log_debug(f"Saving contents to {file_path}")
            if not file_path.parent.exists():
                file_path.parent.mkdir(parents=True, exist_ok=True)
            if file_path.exists() and not overwrite:
                return f"File {file_name} already exists"
            file_path.write_text(contents, encoding=encoding)
            self._record_read(file_path, is_partial=False)
            log_debug(f"Saved: {file_path}")
            return str(file_name)
        except Exception as e:
            log_error(f"Error saving to file: {str(e)}")
            return f"Error saving to file: {e}"

    def read_file_chunk(self, file_name: str, start_line: int, end_line: int, encoding: str = "utf-8") -> str:
        """Reads the contents of the file `file_name` and returns lines from start_line to end_line.

        :param file_name: The name of the file to read.
        :param start_line: Number of first line in the returned chunk
        :param end_line: Number of the last line in the returned chunk
        :param encoding: Encoding to use, default - utf-8

        :return: The contents of the selected chunk
        """
        try:
            log_debug(f"Reading file: {file_name}")
            safe, file_path = self.check_escape(file_name)
            if not (safe):
                log_error(f"Attempted to read file: {file_name}")
                return "Error reading file"
            contents = file_path.read_text(encoding=encoding)
            lines = contents.split(self.line_separator)
            self._record_read(file_path, is_partial=True)
            return self.line_separator.join(lines[start_line : end_line + 1])
        except Exception as e:
            log_error(f"Error reading file: {str(e)}")
            return f"Error reading file: {e}"

    def replace_file_chunk(
        self, file_name: str, start_line: int, end_line: int, chunk: str, encoding: str = "utf-8"
    ) -> str:
        """Reads the contents of the file, replaces lines
        between start_line and end_line with chunk and writes the file

        :param file_name: The name of the file to process.
        :param start_line: Number of first line in the replaced chunk
        :param end_line: Number of the last line in the replaced chunk
        :param chunk: String to be inserted instead of lines from start_line to end_line. Can have multiple lines.
        :param encoding: Encoding to use, default - utf-8

        :return: file name if successfull, error message otherwise
        """
        try:
            log_debug(f"Patching file: {file_name}")
            safe, file_path = self.check_escape(file_name)
            if not (safe):
                log_error(f"Attempted to read file: {file_name}")
                return "Error reading file"
            contents = file_path.read_text(encoding=encoding)
            lines = contents.split(self.line_separator)
            start = lines[0:start_line]
            end = lines[end_line + 1 :]
            return self.save_file(
                file_name=file_name, contents=self.line_separator.join(start + [chunk] + end), encoding=encoding
            )
        except Exception as e:
            log_error(f"Error patching file: {str(e)}")
            return f"Error patching file: {e}"

    def read_file(self, file_name: str, encoding: str = "utf-8") -> str:
        """Reads the contents of the file `file_name` and returns the contents if successful.

        :param file_name: The name of the file to read.
        :param encoding: Encoding to use, default - utf-8
        :return: The contents of the file if successful, otherwise returns an error message.
        """
        try:
            log_debug(f"Reading file: {file_name}")
            safe, file_path = self.check_escape(file_name)
            if not (safe):
                log_error(f"Attempted to read file: {file_name}")
                return "Error reading file"
            contents = file_path.read_text(encoding=encoding)
            if len(contents) > self.max_file_length:
                return "Error reading file: file too long. Use read_file_chunk instead"
            if len(contents.split(self.line_separator)) > self.max_file_lines:
                return "Error reading file: file too long. Use read_file_chunk instead"

            self._record_read(file_path, is_partial=False)
            return str(contents)
        except Exception as e:
            log_error(f"Error reading file: {str(e)}")
            return f"Error reading file: {e}"

    def delete_file(self, file_name: str) -> str:
        """Deletes a file
        :param file_name: Name of the file to delete

        :return: Empty string, if operation succeeded, otherwise returns an error message
        """
        safe, path = self.check_escape(file_name)
        try:
            if safe:
                if path.is_dir():
                    path.rmdir()
                    return ""
                path.unlink()
                return ""
            else:
                log_error(f"Attempt to delete file outside {self.base_dir}: {file_name}")
                return "Incorrect file_name"
        except Exception as e:
            log_error(f"Error removing {file_name}: {str(e)}")
            return f"Error removing file: {e}"

    def list_files(self, **kwargs) -> str:
        """Returns a list of files in directory
        :param directory: (Optional) name of directory to list.

        :return: The contents of the file if successful, otherwise returns an error message.
        """
        directory = kwargs.get("directory", ".")
        try:
            log_debug(f"Reading files in : {self.base_dir}/{directory}")
            safe, d = self.check_escape(directory)
            if safe:
                return json.dumps(
                    [
                        str(file_path.relative_to(self.base_dir))
                        for file_path in d.iterdir()
                        if not self._is_excluded(file_path)
                    ],
                    indent=4,
                )
            else:
                return "{}"
        except Exception as e:
            log_error(f"Error reading files: {str(e)}")
            return f"Error reading files: {e}"

    def search_files(self, pattern: str) -> str:
        """Searches for files in the base directory that match the pattern

        :param pattern: The pattern to search for, e.g. "*.txt", "file*.csv", "**/*.py".
        :return: JSON formatted list of matching file paths, or error message.
        """
        try:
            if not pattern or not pattern.strip():
                return "Error: Pattern cannot be empty"

            log_debug(f"Searching files in {self.base_dir} with pattern {pattern}")
            matching_files = [p for p in self.base_dir.glob(pattern) if not self._is_excluded(p)]
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
                file_paths = [str(file_path.relative_to(self.base_dir)) for file_path in matching_files]

                result = {
                    "pattern": pattern,
                    "matches_found": len(file_paths),
                    "files": file_paths,
                }
            log_debug(f"Found {len(file_paths)} files matching pattern {pattern}")
            return json.dumps(result, indent=2)

        except Exception as e:
            error_msg = f"Error searching files with pattern '{pattern}': {e}"
            log_error(error_msg)
            return error_msg

    def search_content(self, query: str, directory: Optional[str] = None, limit: int = 10) -> str:
        """Search file contents within the base directory for a query string (case-insensitive).

        Only text files (by extension) under 500KB are searched.

        :param query: The text to search for in file contents.
        :param directory: Optional subdirectory to scope the search to.
        :param limit: Maximum number of matching files to return (default 10).
        :return: JSON formatted results with file paths, sizes, and content snippets.
        """
        try:
            if not query or not query.strip():
                return "Error: Query cannot be empty"

            search_dir = self.base_dir
            if directory:
                safe, search_dir = self.check_escape(directory)
                if not safe:
                    log_error(f"Attempted to search outside base directory: {directory}")
                    return "Error: Directory is outside the allowed base directory"

            if not search_dir.is_dir():
                return f"Error: '{directory}' is not a directory"

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
                        rel_path = str(file_path.relative_to(self.base_dir))
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
            error_msg = f"Error searching content for '{query}': {e}"
            log_error(error_msg)
            return error_msg

    def edit_file(
        self,
        file_name: str,
        old_text: str,
        new_text: str,
        replace_all: bool = False,
        encoding: str = "utf-8",
    ) -> str:
        """Edit a file by replacing ``old_text`` with ``new_text``.

        The file must have been fully read via ``read_file`` (or just written
        via ``save_file``) before it can be edited. If its mtime has changed
        since then, the edit is rejected so the agent re-reads the current
        contents before retrying.

        ``old_text`` must match exactly one location unless ``replace_all``
        is ``True``. Passing an empty ``old_text`` on a non-existent file
        creates it with ``new_text`` as its contents.

        :param file_name: Path (relative to ``base_dir``) of the file to edit.
        :param old_text: Exact text to replace. Empty string + missing file => create.
        :param new_text: Replacement text. Must differ from ``old_text``.
        :param replace_all: Replace every occurrence instead of requiring a unique match.
        :param encoding: File encoding, defaults to utf-8.
        :return: A short success message, or an ``Error: ...`` string.
        """
        try:
            if old_text == new_text:
                return "Error editing file: old_text and new_text are identical"

            safe, file_path = self.check_escape(file_name)
            if not safe:
                log_error(f"Attempted to edit file: {file_name}")
                return "Error editing file"

            if not file_path.exists():
                if old_text == "":
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_text(new_text, encoding=encoding)
                    self._record_read(file_path, is_partial=False)
                    log_debug(f"Created file via edit_file: {file_path}")
                    return f"Created {file_name}"
                return (
                    f"Error editing file: {file_name} does not exist. "
                    "To create it, pass old_text='' with the new contents in new_text."
                )

            cached = self._read_state.get(file_path)
            if cached is None:
                return (
                    f"Error editing file: {file_name} has not been read yet. "
                    "Call read_file first so the agent sees the current contents."
                )
            if cached.is_partial:
                return (
                    f"Error editing file: {file_name} was only partially read via read_file_chunk. "
                    "Call read_file for the full contents before editing."
                )
            if file_path.stat().st_mtime_ns != cached.mtime_ns:
                return (
                    f"Error editing file: {file_name} has been modified since last read. "
                    "Call read_file again before editing."
                )

            contents = file_path.read_text(encoding=encoding)
            count = contents.count(old_text)
            if count == 0:
                return f"Error editing file: old_text not found in {file_name}"
            if count > 1 and not replace_all:
                return (
                    f"Error editing file: old_text matches {count} locations in {file_name}. "
                    "Add surrounding context to make the match unique, or pass replace_all=True."
                )

            replacements = count if replace_all else 1
            new_contents = contents.replace(old_text, new_text, replacements)
            file_path.write_text(new_contents, encoding=encoding)
            self._record_read(file_path, is_partial=False)
            log_debug(f"Edited {file_path} ({replacements} replacement{'s' if replacements != 1 else ''})")
            return f"Edited {file_name} ({replacements} replacement{'s' if replacements != 1 else ''})"
        except Exception as e:
            log_error(f"Error editing file: {str(e)}")
            return f"Error editing file: {e}"
