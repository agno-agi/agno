"""WorkspaceTools — read, write, edit, search, and run shell commands in a sandboxed local directory.

Destructive operations (write/edit/delete/run) require human confirmation by default,
which AgentOS renders as approval prompts in the run timeline.

Quick start:

    from agno.agent import Agent
    from agno.tools.workspace import WorkspaceTools

    agent = Agent(
        model="openai:gpt-5.4",
        tools=[
            WorkspaceTools(
                base_dir=".",
                allowed_tools=["read_file", "list_files", "search_content"],
                confirm_tools=["write_file", "edit_file", "delete_file", "run_command"],
            )
        ],
    )
"""

import asyncio
import json
import os
import subprocess
from fnmatch import fnmatch
from pathlib import Path
from typing import List, Optional, Tuple, Union

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_info, log_warning

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
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".scss",
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
    # Infrastructure as Code
    ".terraform",
    "*.tfstate",
    "*.tfstate.*",
    ".terragrunt-cache",
    # OS artifacts
    ".DS_Store",
]


def _format_size(size: float) -> str:
    """Format a file size in bytes to a human-readable string."""
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{int(size)}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


def _extract_snippet(content: str, query: str, context_chars: int = 200) -> str:
    """Extract a snippet of content around the first case-insensitive match of query."""
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


class WorkspaceTools(Toolkit):
    """Local-machine toolkit for read/write/edit/search/shell access to a sandboxed directory.

    All file operations are scoped to ``base_dir``; paths that escape it are rejected.
    Shell commands run with ``cwd=base_dir``.

    Permission model — ``allowed_tools`` and ``confirm_tools`` are mutually exclusive partitions:

    - A method in ``allowed_tools`` runs silently.
    - A method in ``confirm_tools`` requires user approval (Agno's HITL pause/resume).
    - A method in **neither** list is not registered with the toolkit — the LLM doesn't see it.
    - A method in **both** lists raises ``ValueError``.

    Defaults:

    - When both are ``None``: reads (``read_file``, ``list_files``, ``search_content``) are
      auto-pass, writes (``write_file``, ``edit_file``, ``delete_file``, ``run_command``) require
      confirmation. This is the safe-by-default surface meant for the homepage demo.
    - When only one is set: the other defaults to ``[]`` — you've taken control, and the
      surface is exactly what you specified.

    Listing results from ``list_files`` and ``search_content`` skip common noise directories
    (``.venv``, ``.git``, ``__pycache__``, ``node_modules``, etc.) by default. Pass
    ``exclude_patterns=[]`` to disable, or ``exclude_patterns=[...]`` to override.
    """

    READ_TOOLS: List[str] = ["read_file", "list_files", "search_content"]
    WRITE_TOOLS: List[str] = ["write_file", "edit_file", "delete_file", "run_command"]
    ALL_TOOLS: List[str] = READ_TOOLS + WRITE_TOOLS

    def __init__(
        self,
        base_dir: Optional[Union[str, Path]] = None,
        allowed_tools: Optional[List[str]] = None,
        confirm_tools: Optional[List[str]] = None,
        max_file_lines: int = 100_000,
        max_file_length: int = 10_000_000,
        exclude_patterns: Optional[List[str]] = None,
        **kwargs,
    ):
        # Resolve base_dir to an absolute path once — never re-read cwd later (reload-safe).
        if base_dir is None:
            self.base_dir: Path = Path.cwd().resolve()
        else:
            self.base_dir = Path(base_dir).resolve()

        self.max_file_lines = max_file_lines
        self.max_file_length = max_file_length
        self.exclude_patterns: List[str] = (
            exclude_patterns if exclude_patterns is not None else list(DEFAULT_EXCLUDE_PATTERNS)
        )

        resolved_allowed, resolved_confirm = self._resolve_partitions(allowed_tools, confirm_tools)

        registered = resolved_allowed + resolved_confirm
        sync_tools = [getattr(self, name) for name in registered]
        async_tools = [(getattr(self, "a" + name), name) for name in registered]

        super().__init__(
            name="workspace_tools",
            tools=sync_tools,
            async_tools=async_tools,
            requires_confirmation_tools=resolved_confirm,
            **kwargs,
        )

        # Surface-drift guard: every name in ALL_TOOLS must resolve to both a sync method
        # and an async sibling. Catches contributor bugs (added a method but forgot to
        # partition it, or vice versa).
        for name in self.ALL_TOOLS:
            assert callable(getattr(self, name, None)), f"WorkspaceTools missing sync method: {name}"
            assert callable(getattr(self, "a" + name, None)), f"WorkspaceTools missing async method: a{name}"

    @classmethod
    def _resolve_partitions(
        cls,
        allowed_tools: Optional[List[str]],
        confirm_tools: Optional[List[str]],
    ) -> Tuple[List[str], List[str]]:
        """Resolve allowed_tools / confirm_tools into mutually-exclusive lists.

        See the class docstring for the resolution rules.
        """
        # Both None → safe defaults.
        if allowed_tools is None and confirm_tools is None:
            return list(cls.READ_TOOLS), list(cls.WRITE_TOOLS)

        # If one is set, the other defaults to [] — explicit user control means no surprise mixing.
        if allowed_tools is None:
            allowed_tools = []
        if confirm_tools is None:
            confirm_tools = []

        valid = set(cls.ALL_TOOLS)
        unknown_allowed = set(allowed_tools) - valid
        if unknown_allowed:
            raise ValueError(
                f"Unknown tool name(s) in allowed_tools: {sorted(unknown_allowed)}. Valid names: {cls.ALL_TOOLS}"
            )
        unknown_confirm = set(confirm_tools) - valid
        if unknown_confirm:
            raise ValueError(
                f"Unknown tool name(s) in confirm_tools: {sorted(unknown_confirm)}. Valid names: {cls.ALL_TOOLS}"
            )
        overlap = set(allowed_tools) & set(confirm_tools)
        if overlap:
            raise ValueError(
                f"Tool name(s) appear in both allowed_tools and confirm_tools: {sorted(overlap)}. "
                "They must be mutually exclusive — allowed_tools auto-pass, confirm_tools require approval."
            )
        return list(allowed_tools), list(confirm_tools)

    def _is_excluded(self, path: Path) -> bool:
        """Return True if any component of ``path`` (relative to ``base_dir``) matches an exclude pattern."""
        if not self.exclude_patterns:
            return False
        try:
            rel = path.relative_to(self.base_dir)
        except ValueError:
            return False
        return any(fnmatch(part, pattern) for part in rel.parts for pattern in self.exclude_patterns)

    # ------------------------------------------------------------------
    # Read operations (auto-pass by default)
    # ------------------------------------------------------------------

    def read_file(
        self,
        path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        encoding: str = "utf-8",
    ) -> str:
        """Read a file from the workspace.

        :param path: File path relative to the workspace base directory.
        :param start_line: Optional 1-indexed first line to return. If omitted with end_line,
            returns the entire file (subject to size limits).
        :param end_line: Optional 1-indexed last line to return (inclusive).
        :param encoding: Text encoding (default utf-8).
        :return: File contents (or selected line range), or an error message starting with "Error".
        """
        try:
            log_debug(f"read_file: {path}")
            safe, file_path = self._check_path(path, self.base_dir)
            if not safe:
                log_error(f"Path escapes workspace: {path}")
                return "Error: path escapes workspace base directory"
            if not file_path.is_file():
                return f"Error: file not found: {path}"
            contents = file_path.read_text(encoding=encoding)
            if start_line is None and end_line is None:
                if len(contents) > self.max_file_length:
                    return (
                        f"Error: file too long ({len(contents)} chars > {self.max_file_length}). "
                        "Use start_line/end_line to read a chunk."
                    )
                line_count = contents.count("\n") + 1
                if line_count > self.max_file_lines:
                    return (
                        f"Error: file too long ({line_count} lines > {self.max_file_lines}). "
                        "Use start_line/end_line to read a chunk."
                    )
                return contents
            lines = contents.split("\n")
            start = start_line if start_line is not None else 1
            end = end_line if end_line is not None else len(lines)
            start_idx = max(0, start - 1)
            end_idx = min(len(lines), end)
            return "\n".join(lines[start_idx:end_idx])
        except Exception as e:
            log_error(f"read_file failed: {e}")
            return f"Error reading file: {e}"

    def list_files(self, directory: str = ".", pattern: Optional[str] = None) -> str:
        """List files in a workspace directory, optionally filtered by a glob pattern.

        :param directory: Subdirectory relative to the workspace base (default ".").
        :param pattern: Optional glob pattern. Use ``"**/*.py"`` for recursive matches.
            If omitted, lists immediate children of ``directory``.
        :return: JSON string with keys ``directory``, ``pattern``, and ``files`` (list of
            relative paths). Default-excluded directories (``.venv``, ``.git``, ``node_modules``,
            etc.) are filtered out.
        """
        try:
            safe, d = self._check_path(directory, self.base_dir)
            if not safe:
                return "Error: directory escapes workspace base directory"
            if not d.is_dir():
                return f"Error: not a directory: {directory}"
            if pattern:
                matches = [p for p in d.glob(pattern) if not self._is_excluded(p)]
                files = sorted(str(p.relative_to(self.base_dir)) for p in matches)
            else:
                files = sorted(str(p.relative_to(self.base_dir)) for p in d.iterdir() if not self._is_excluded(p))
            return json.dumps({"directory": directory, "pattern": pattern, "files": files}, indent=2)
        except Exception as e:
            log_error(f"list_files failed: {e}")
            return f"Error listing files: {e}"

    def search_content(self, query: str, directory: str = ".", limit: int = 10) -> str:
        """Recursive case-insensitive content grep across text files in the workspace.

        Only text files (by extension) under 500KB are searched. Returns the first ``limit``
        matching files with a snippet around the first match in each.

        :param query: Substring to search for (case-insensitive).
        :param directory: Subdirectory to scope the search to (default ".").
        :param limit: Maximum number of matching files to return (default 10).
        :return: JSON string with keys ``query``, ``matches_found``, and ``files`` (a list of
            ``{"file", "size", "snippet"}`` objects).
        """
        try:
            if not query or not query.strip():
                return "Error: query cannot be empty"
            safe, search_dir = self._check_path(directory, self.base_dir)
            if not safe:
                return "Error: directory escapes workspace base directory"
            if not search_dir.is_dir():
                return f"Error: not a directory: {directory}"

            lower_query = query.lower()
            matches: List[dict] = []
            max_file_size = 500 * 1024
            walk_done = False

            for dirpath, dirnames, filenames in os.walk(search_dir):
                if walk_done:
                    break
                dirnames[:] = [name for name in dirnames if not self._is_excluded(Path(dirpath) / name)]
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
                        matches.append(
                            {
                                "file": rel_path,
                                "size": _format_size(file_path.stat().st_size),
                                "snippet": _extract_snippet(content, query),
                            }
                        )
            return json.dumps({"query": query, "matches_found": len(matches), "files": matches}, indent=2)
        except Exception as e:
            log_error(f"search_content failed: {e}")
            return f"Error searching content: {e}"

    # ------------------------------------------------------------------
    # Write operations (require confirmation by default)
    # ------------------------------------------------------------------

    def write_file(self, path: str, content: str, overwrite: bool = True, encoding: str = "utf-8") -> str:
        """Write a file to the workspace, creating parent directories if needed.

        :param path: File path relative to the workspace base directory.
        :param content: Text content to write.
        :param overwrite: If False, fail when the file already exists (default True).
        :param encoding: Text encoding (default utf-8).
        :return: Success message including the path and byte count, or an error message.
        """
        try:
            safe, file_path = self._check_path(path, self.base_dir)
            if not safe:
                log_error(f"Path escapes workspace: {path}")
                return "Error: path escapes workspace base directory"
            if file_path.exists() and not overwrite:
                return f"Error: file exists and overwrite=False: {path}"
            if not file_path.parent.exists():
                file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding=encoding)
            return f"Wrote {len(content)} chars to {path}"
        except Exception as e:
            log_error(f"write_file failed: {e}")
            return f"Error writing file: {e}"

    def edit_file(self, path: str, old_str: str, new_str: str, encoding: str = "utf-8") -> str:
        """Edit a file by replacing exactly one occurrence of ``old_str`` with ``new_str``.

        Fails if ``old_str`` doesn't appear, or appears more than once. To replace all
        occurrences, call this method multiple times with progressively unique snippets,
        or read the file and use ``write_file`` with the rewritten contents.

        :param path: File path relative to the workspace base directory.
        :param old_str: Exact substring to replace. Must match exactly once in the file.
        :param new_str: Replacement substring.
        :param encoding: Text encoding (default utf-8).
        :return: Success message, or an error if old_str matches zero or multiple times.
        """
        try:
            safe, file_path = self._check_path(path, self.base_dir)
            if not safe:
                return "Error: path escapes workspace base directory"
            if not file_path.is_file():
                return f"Error: file not found: {path}"
            contents = file_path.read_text(encoding=encoding)
            count = contents.count(old_str)
            if count == 0:
                return f"Error: old_str not found in {path}"
            if count > 1:
                return f"Error: old_str matches {count} times in {path}; provide a more unique snippet"
            new_contents = contents.replace(old_str, new_str, 1)
            file_path.write_text(new_contents, encoding=encoding)
            return f"Edited {path}: replaced 1 occurrence"
        except Exception as e:
            log_error(f"edit_file failed: {e}")
            return f"Error editing file: {e}"

    def delete_file(self, path: str) -> str:
        """Delete a file from the workspace. Refuses to delete directories.

        :param path: File path relative to the workspace base directory.
        :return: Success message, or an error if the path doesn't exist or is a directory.
        """
        try:
            safe, file_path = self._check_path(path, self.base_dir)
            if not safe:
                return "Error: path escapes workspace base directory"
            if not file_path.exists():
                return f"Error: file not found: {path}"
            if file_path.is_dir():
                return f"Error: path is a directory, not a file: {path}"
            file_path.unlink()
            return f"Deleted {path}"
        except Exception as e:
            log_error(f"delete_file failed: {e}")
            return f"Error deleting file: {e}"

    def run_command(self, args: List[str], tail: int = 100) -> str:
        """Run a shell command in the workspace base directory and return its output.

        Args is a list of strings (e.g. ``["ls", "-la"]``) — the command is NOT
        invoked through a shell, so quoting/expansion are not interpreted. To use
        shell features, pass ``["bash", "-c", "your-command-here"]``.

        :param args: Command and arguments as a list of strings.
        :param tail: Maximum number of trailing lines of stdout (or stderr on error) to return.
        :return: Tailed stdout on success, or an error message including stderr on failure.
        """
        try:
            log_info(f"run_command: {args}")
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                cwd=str(self.base_dir),
            )
            if result.returncode != 0:
                err = "\n".join(result.stderr.splitlines()[-tail:])
                return f"Error (exit {result.returncode}): {err}"
            return "\n".join(result.stdout.splitlines()[-tail:])
        except Exception as e:
            log_warning(f"run_command failed: {e}")
            return f"Error running command: {e}"

    # ------------------------------------------------------------------
    # Async siblings
    # ------------------------------------------------------------------

    async def aread_file(
        self,
        path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        encoding: str = "utf-8",
    ) -> str:
        """Async variant of ``read_file``."""
        return await asyncio.to_thread(self.read_file, path, start_line, end_line, encoding)

    async def alist_files(self, directory: str = ".", pattern: Optional[str] = None) -> str:
        """Async variant of ``list_files``."""
        return await asyncio.to_thread(self.list_files, directory, pattern)

    async def asearch_content(self, query: str, directory: str = ".", limit: int = 10) -> str:
        """Async variant of ``search_content``."""
        return await asyncio.to_thread(self.search_content, query, directory, limit)

    async def awrite_file(self, path: str, content: str, overwrite: bool = True, encoding: str = "utf-8") -> str:
        """Async variant of ``write_file``."""
        return await asyncio.to_thread(self.write_file, path, content, overwrite, encoding)

    async def aedit_file(self, path: str, old_str: str, new_str: str, encoding: str = "utf-8") -> str:
        """Async variant of ``edit_file``."""
        return await asyncio.to_thread(self.edit_file, path, old_str, new_str, encoding)

    async def adelete_file(self, path: str) -> str:
        """Async variant of ``delete_file``."""
        return await asyncio.to_thread(self.delete_file, path)

    async def arun_command(self, args: List[str], tail: int = 100) -> str:
        """Async variant of ``run_command`` using ``asyncio.create_subprocess_exec``."""
        try:
            log_info(f"arun_command: {args}")
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.base_dir),
            )
            stdout_b, stderr_b = await proc.communicate()
            stdout = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
            stderr = stderr_b.decode("utf-8", errors="replace") if stderr_b else ""
            if proc.returncode != 0:
                err = "\n".join(stderr.splitlines()[-tail:])
                return f"Error (exit {proc.returncode}): {err}"
            return "\n".join(stdout.splitlines()[-tail:])
        except Exception as e:
            log_warning(f"arun_command failed: {e}")
            return f"Error running command: {e}"
