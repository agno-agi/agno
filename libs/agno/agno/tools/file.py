import bisect
import json
import os
import re
import shutil
import subprocess
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Dict, Iterator, List, Literal, Optional, Tuple

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

GrepOutputMode = Literal["files_with_matches", "content", "count"]
_GREP_OUTPUT_MODES = ("files_with_matches", "content", "count")

# Absolute cap on how many results grep will return in a single call, even
# when limit is set higher. Prevents accidental context blow-up.
GREP_MAX_LIMIT = 1000
# Timeout for the ripgrep subprocess. Ripgrep is fast; anything longer
# than 20s on a project usually means a pathological regex.
GREP_RG_TIMEOUT_S = 20

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
        enable_grep: bool = True,
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
        # Cache the ripgrep binary path so grep does not repeat the PATH
        # lookup on every call. ``None`` means ripgrep is not installed.
        self._rg_path: Optional[str] = shutil.which("rg")
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
        if all or enable_grep:
            tools.append(self.grep)

        super().__init__(name="file_tools", tools=tools, **kwargs)

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

    def grep(
        self,
        pattern: str,
        path: Optional[str] = None,
        output_mode: GrepOutputMode = "files_with_matches",
        include: Optional[str] = None,
        ignore_case: bool = False,
        context: int = 0,
        limit: int = 250,
        multiline: bool = False,
    ) -> str:
        """Regex-based content search across the base directory.

        Prefers the ripgrep (``rg``) binary when it is on PATH for speed,
        and falls back to a pure-Python walk when it is not. The output
        shape does not depend on which backend ran.

        Return JSON shape varies by ``output_mode``:

        - ``"files_with_matches"``: ``{"pattern", "mode", "matches_found", "files": [...], "truncated"}``
        - ``"content"``: ``{"pattern", "mode", "matches_found", "lines": [{"file", "line", "text"}, ...], "truncated"}``
        - ``"count"``: ``{"pattern", "mode", "matches_found", "counts": [{"file", "count"}, ...], "truncated"}``

        :param pattern: Regex to search for. Uses ripgrep syntax when ``rg``
            is available, Python's ``re`` syntax otherwise. Simple patterns
            work the same in both.
        :param path: Optional subdirectory (relative to ``base_dir``) to
            scope the search to. Defaults to the whole base directory.
        :param output_mode: ``"files_with_matches"`` (default, paths only),
            ``"content"`` (matching lines with line numbers), or ``"count"``
            (match count per file).
        :param include: Optional filename filter such as ``"*.py"`` or
            ``"**/*.tsx"``. Matched against paths relative to ``base_dir``.
        :param ignore_case: If ``True``, ignore case when matching.
        :param context: Number of context lines to show before and after each
            match. Only applies when ``output_mode='content'`` and the
            ripgrep backend is active; the Python fallback ignores it.
        :param limit: Maximum number of results to return. Capped at
            ``GREP_MAX_LIMIT`` regardless of caller input.
        :param multiline: If ``True``, the pattern can match across line
            boundaries (``.`` matches newlines). Off by default.
        :return: JSON document with the shape shown above.
        """
        try:
            if not pattern or not pattern.strip():
                return "Error: Pattern cannot be empty"
            if output_mode not in _GREP_OUTPUT_MODES:
                return f"Error: output_mode must be one of {_GREP_OUTPUT_MODES}, got {output_mode!r}"

            search_dir = self.base_dir
            if path:
                safe, search_dir = self.check_escape(path)
                if not safe:
                    log_error(f"Attempted to grep outside base directory: {path}")
                    return "Error: path is outside the allowed base directory"
            if not search_dir.is_dir():
                return f"Error: '{path}' is not a directory"

            effective_limit = min(max(limit, 1), GREP_MAX_LIMIT)

            if self._rg_path is not None:
                log_debug(f"grep: using ripgrep at {self._rg_path}")
                return self._grep_ripgrep(
                    rg_path=self._rg_path,
                    pattern=pattern,
                    search_dir=search_dir,
                    output_mode=output_mode,
                    include=include,
                    ignore_case=ignore_case,
                    context=context,
                    limit=effective_limit,
                    multiline=multiline,
                )

            log_debug("grep: ripgrep not found, using Python fallback")
            return self._grep_python(
                pattern=pattern,
                search_dir=search_dir,
                output_mode=output_mode,
                include=include,
                ignore_case=ignore_case,
                context=context,
                limit=effective_limit,
                multiline=multiline,
            )
        except Exception as e:
            error_msg = f"Error running grep for '{pattern}': {e}"
            log_error(error_msg)
            return error_msg

    def _grep_ripgrep(
        self,
        *,
        rg_path: str,
        pattern: str,
        search_dir: Path,
        output_mode: GrepOutputMode,
        include: Optional[str],
        ignore_case: bool,
        context: int,
        limit: int,
        multiline: bool,
    ) -> str:
        """Invoke ripgrep and normalize its output into the shared JSON shape."""
        args: List[str] = [rg_path, "--hidden", "--max-columns", "500"]
        # Our exclude_patterns are fnmatch-style; ripgrep accepts the same
        # globbing syntax for --glob, so pass them through directly.
        for pat in self.exclude_patterns:
            args.extend(["--glob", f"!{pat}"])

        if ignore_case:
            args.append("-i")
        if multiline:
            args.extend(["-U", "--multiline-dotall"])
        if include:
            args.extend(["--glob", include])

        if output_mode == "files_with_matches":
            args.append("-l")
        elif output_mode == "count":
            args.append("-c")
        else:  # content
            args.append("-n")
            if context > 0:
                args.extend(["-C", str(context)])

        # Use -e so patterns starting with '-' are not treated as flags.
        args.extend(["-e", pattern, str(search_dir)])

        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=GREP_RG_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return f"Error: ripgrep exceeded {GREP_RG_TIMEOUT_S}s; refine the pattern or narrow the path"

        # ripgrep exit codes: 0 = matches, 1 = no matches, 2+ = error.
        if completed.returncode >= 2:
            stderr = completed.stderr.strip() or "ripgrep failed"
            return f"Error: {stderr}"

        lines = [line for line in completed.stdout.splitlines() if line]
        truncated = len(lines) > limit
        lines = lines[:limit]

        if output_mode == "files_with_matches":
            files = [self._relativize(line) for line in lines]
            result: Dict[str, Any] = {
                "pattern": pattern,
                "mode": output_mode,
                "matches_found": len(files),
                "files": files,
                "truncated": truncated,
            }
        elif output_mode == "count":
            counts: List[dict] = []
            total = 0
            for line in lines:
                file_part, _, num_part = line.rpartition(":")
                try:
                    n = int(num_part)
                except ValueError:
                    continue
                counts.append({"file": self._relativize(file_part), "count": n})
                total += n
            result = {
                "pattern": pattern,
                "mode": output_mode,
                "matches_found": total,
                "counts": counts,
                "truncated": truncated,
            }
        else:  # content
            content_lines: List[dict] = []
            for line in lines:
                parts = line.split(":", 2)
                if len(parts) < 3:
                    continue
                file_part, line_no, text = parts
                try:
                    n = int(line_no)
                except ValueError:
                    continue
                content_lines.append({"file": self._relativize(file_part), "line": n, "text": text})
            result = {
                "pattern": pattern,
                "mode": output_mode,
                "matches_found": len(content_lines),
                "lines": content_lines,
                "truncated": truncated,
            }

        return json.dumps(result, indent=2)

    def _grep_python(
        self,
        *,
        pattern: str,
        search_dir: Path,
        output_mode: GrepOutputMode,
        include: Optional[str],
        ignore_case: bool,
        context: int,
        limit: int,
        multiline: bool,
    ) -> str:
        """Pure-Python fallback used when ripgrep is unavailable.

        Slower than ripgrep and uses Python regex syntax, but supports the
        same output modes so callers don't need to special-case the absence
        of ``rg``.
        """
        flags = 0
        if ignore_case:
            flags |= re.IGNORECASE
        if multiline:
            flags |= re.DOTALL
        try:
            compiled = re.compile(pattern, flags)
        except re.error as exc:
            return f"Error: invalid regex {pattern!r}: {exc}"

        per_file_counts: List[Tuple[Path, int]] = []
        content_hits: List[Dict[str, Any]] = []
        max_file_size = 1_000_000  # 1MB; mirrors search_content's safety rail

        for file_path in self._iter_candidate_files(search_dir, include):
            try:
                if file_path.stat().st_size > max_file_size:
                    continue
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            if multiline:
                hits = list(compiled.finditer(text))
                if not hits:
                    continue
                per_file_counts.append((file_path, len(hits)))
                if output_mode == "content":
                    # Precompute newline offsets so every match resolves its
                    # line number in O(log n) via bisect, instead of re-counting
                    # the prefix per match (which was O(offset) per hit).
                    newline_offsets = [i for i, c in enumerate(text) if c == "\n"]
                    rel = self._relativize(str(file_path))
                    for match in hits:
                        line_no = bisect.bisect_right(newline_offsets, match.start()) + 1
                        snippet = text[match.start() : match.end()].splitlines()[0]
                        content_hits.append({"file": rel, "line": line_no, "text": snippet})
            elif output_mode == "count":
                # Skip the line-by-line loop when we only need a total count.
                total = len(compiled.findall(text))
                if total:
                    per_file_counts.append((file_path, total))
            else:
                file_hits = 0
                rel = self._relativize(str(file_path))
                for idx, line in enumerate(text.splitlines()):
                    if compiled.search(line):
                        file_hits += 1
                        if output_mode == "content":
                            content_hits.append({"file": rel, "line": idx + 1, "text": line})
                if file_hits:
                    per_file_counts.append((file_path, file_hits))

            if output_mode == "content" and len(content_hits) >= limit:
                break
            if output_mode != "content" and len(per_file_counts) >= limit:
                break

        if output_mode == "files_with_matches":
            truncated = len(per_file_counts) >= limit
            files = [self._relativize(str(p)) for p, _ in per_file_counts[:limit]]
            result: Dict[str, Any] = {
                "pattern": pattern,
                "mode": output_mode,
                "matches_found": len(files),
                "files": files,
                "truncated": truncated,
            }
        elif output_mode == "count":
            truncated = len(per_file_counts) >= limit
            counts = [{"file": self._relativize(str(p)), "count": n} for p, n in per_file_counts[:limit]]
            result = {
                "pattern": pattern,
                "mode": output_mode,
                "matches_found": sum(n for _, n in per_file_counts[:limit]),
                "counts": counts,
                "truncated": truncated,
            }
        else:  # content
            truncated = len(content_hits) >= limit
            trimmed = content_hits[:limit]
            # Context lines require re-reading files with surrounding context,
            # which the ripgrep backend already does natively. Skipping it here
            # keeps the fallback simple without a silent divergence — the
            # docstring calls this out.
            if context > 0:
                log_debug("grep Python fallback ignores context; install ripgrep for context support")
            result = {
                "pattern": pattern,
                "mode": output_mode,
                "matches_found": len(trimmed),
                "lines": trimmed,
                "truncated": truncated,
            }

        return json.dumps(result, indent=2)

    def _iter_candidate_files(self, search_dir: Path, include: Optional[str]) -> Iterator[Path]:
        """Yield files under ``search_dir`` honoring exclude_patterns and include."""
        for dirpath, dirnames, filenames in os.walk(search_dir):
            dirnames[:] = [d for d in dirnames if not self._is_excluded(Path(dirpath) / d)]
            for filename in filenames:
                file_path = Path(dirpath) / filename
                if self._is_excluded(file_path):
                    continue
                if include is not None:
                    try:
                        rel = file_path.relative_to(self.base_dir)
                    except ValueError:
                        continue
                    if not (fnmatch(str(rel), include) or fnmatch(filename, include)):
                        continue
                yield file_path

    def _relativize(self, p: str) -> str:
        """Return ``p`` relative to ``base_dir`` when possible, else as given."""
        try:
            return str(Path(p).relative_to(self.base_dir))
        except ValueError:
            return p
