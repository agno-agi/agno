"""AgentFSTools — the tool surface over AgentFS, built by ``AgentFS.tools()``.

To the agent this is just a filesystem: six tools share their names, shapes and
output formats with ``agno.tools.workspace.Workspace`` (``read_file``,
``write_file``, ``list_files``, ``search_content``, ``move_file``,
``delete_file``), plus two additions the durability use cases need:
``append_file`` (line-oriented) and ``check_lines`` (batch exact-line
membership — the dedupe primitive).

These names deliberately collide with the rest of the file-toolkit family
(Workspace, FileTools, PythonTools, CodingTools, ...). Agno's tool resolver
keeps the first registration per name and drops later duplicates with a logged
warning, so attach at most one file-like toolkit per agent; when an agent
genuinely needs both AgentFS and a local workspace, wrap one in a sub-agent.
"""

from __future__ import annotations

import asyncio
import json
from fnmatch import fnmatch
from typing import Dict, List, Optional, Union

# Real module-level imports, never TYPE_CHECKING-only: with postponed annotations a
# deferred import does not fail loudly — get_type_hints raises during schema
# building, the warning is downgraded, and the tool ships an empty JSON schema.
from agno.agent.agent import Agent
from agno.fs._paths import build_chunk, normalize_directory, path_sort_key
from agno.fs.errors import InvalidPathError, QuotaExceededError
from agno.fs.fs import AgentFS
from agno.run import RunContext
from agno.team.team import Team
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, log_error

_MAX_DIR_ENTRIES = 500


def _format_size(size: float) -> str:
    """Format a file size in bytes to a human-readable string."""
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{int(size)}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


def _format_with_line_numbers(text: str, start_line: int = 1) -> str:
    """Prefix each line with its 1-indexed number, ``cat -n`` style.

    The numbers reflect the actual line in the source file: when reading a chunk
    starting at line 50, the first returned line is numbered 50.
    """
    lines = text.split("\n")
    # Drop the trailing empty element produced by a terminal newline.
    if lines and lines[-1] == "":
        lines = lines[:-1]
    return "\n".join(f"{i + start_line:6d}\t{line}" for i, line in enumerate(lines))


class AgentFSTools(Toolkit):
    """Toolkit over one ``AgentFS`` file store. Build it with ``AgentFS.tools()``.

    Registers the full eight-tool surface, or the four read tools when
    ``read_only=True`` (the surface for a consumer agent that consults another
    agent's namespace by shared name). Ships the matching AgentFS instructions
    unless ``instructions`` is overridden. Tool errors are returned as
    ``"Error: ..."`` strings, never raised. Writes are last-writer-wins by
    design; there is no confirmation surface — this is the agent's own private,
    quota-capped store (pass ``requires_confirmation_tools`` to opt in).
    """

    FULL_TOOLS: List[str] = [
        "read_file",
        "write_file",
        "append_file",
        "list_files",
        "search_content",
        "check_lines",
        "move_file",
        "delete_file",
    ]
    READ_ONLY_TOOLS: List[str] = ["read_file", "list_files", "search_content", "check_lines"]

    def __init__(
        self,
        fs: AgentFS,
        read_only: bool = False,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        **kwargs,
    ):
        self.fs = fs
        self.read_only = read_only
        if instructions is None:
            instructions = AgentFS.instructions(read_only=read_only)

        registered = self.READ_ONLY_TOOLS if read_only else self.FULL_TOOLS
        sync_tools = [getattr(self, name) for name in registered]
        async_tools = [(getattr(self, "a" + name), name) for name in registered]

        super().__init__(
            name="agent_fs",
            tools=sync_tools,
            async_tools=async_tools,
            instructions=instructions,
            add_instructions=add_instructions,
            **kwargs,
        )

        # Surface-drift guard: every tool name must resolve to both a sync method
        # and an async sibling on the class, for the full surface and the
        # read-only subset alike.
        for tool_name in self.FULL_TOOLS:
            assert callable(getattr(self, tool_name, None)), f"AgentFSTools missing sync method '{tool_name}'"
            assert callable(getattr(self, "a" + tool_name, None)), f"AgentFSTools missing async method 'a{tool_name}'"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolved(
        self,
        run_context: Optional[RunContext],
        agent: Optional[Agent],
        team: Optional[Team],
    ) -> AgentFS:
        """Resolve a templated namespace from injected context. Fails closed."""
        return self.fs._resolve_from_context(run_context=run_context, agent=agent, team=team)

    @staticmethod
    def _quota_error(e: QuotaExceededError, path: str) -> str:
        if e.scope == "file":
            return (
                f"Error: {path} would be {e.current} bytes (limit {e.limit} per file). "
                "Start a new file (for record logs, partition by date, e.g. seen/2026-07-24.md) "
                "or delete files you no longer need."
            )
        return (
            f"Error: storage is full ({e.current} of {e.limit} bytes). "
            "Delete files you no longer need (see list_files), then retry."
        )

    # ------------------------------------------------------------------
    # Read tools
    # ------------------------------------------------------------------

    def read_file(
        self,
        path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        *,
        run_context: Optional[RunContext] = None,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
    ) -> str:
        """Read a file from your files, returning ``cat -n`` style line-numbered output.

        Each line is prefixed with its 1-indexed line number. Line numbers reflect the
        actual line in the file — reading lines 50-60 numbers the first line 50. The
        numbers are display only: never include them in content you pass to write_file
        or append_file.

        :param path: File path, e.g. "notes/decisions.md".
        :param start_line: Optional 1-indexed first line to return.
        :param end_line: Optional 1-indexed last line to return (inclusive).
        :return: Line-numbered contents, or an error message starting with "Error".
        """
        try:
            log_debug(f"read_file: {path}")
            fs = self._resolved(run_context, agent, team)
            contents = fs.read(path)
            if contents is None:
                return f"Error: file not found: {path}"
            if start_line is None and end_line is None:
                if len(contents) > fs.max_file_bytes:
                    return (
                        f"Error: file too long ({len(contents)} chars > {fs.max_file_bytes}). "
                        "Use start_line/end_line to read a chunk, "
                        "or use search_content to find specific text first."
                    )
                return _format_with_line_numbers(contents, start_line=1)
            lines = contents.split("\n")
            start = start_line if start_line is not None else 1
            end = end_line if end_line is not None else len(lines)
            start_idx = max(0, start - 1)
            end_idx = min(len(lines), end)
            chunk = "\n".join(lines[start_idx:end_idx])
            return _format_with_line_numbers(chunk, start_line=start)
        except InvalidPathError as e:
            return f"Error: {e}"
        except Exception as e:
            log_error(f"read_file failed: {e}")
            return f"Error: {e}"

    def list_files(
        self,
        directory: str = ".",
        pattern: Optional[str] = None,
        recursive: bool = False,
        max_depth: int = 3,
        *,
        run_context: Optional[RunContext] = None,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
    ) -> str:
        """List your files.

        Entries are ``{"path", "type", "size"}`` — ``type`` is "file" or "dir", ``size``
        human-readable for files, null for dirs. The result also reports total usage
        against your storage limit.

        :param directory: Directory to list (default "." = top level), e.g. "seen".
        :param pattern: Optional glob to filter names, e.g. "*.md".
        :param recursive: If True, walk the directory tree up to ``max_depth`` levels deep.
        :param max_depth: Depth limit when ``recursive=True`` (default 3).
        :return: JSON with keys ``directory``, ``pattern``, ``recursive``, ``files``, ``usage``.
        """
        try:
            fs = self._resolved(run_context, agent, team)
            metas = fs.list(directory)
            normalized_directory = normalize_directory(directory)
            prefix_len = 0 if not normalized_directory else len(normalized_directory.split("/"))
            # Entries appear down to max_depth levels of nesting below `directory`;
            # the boundary directory is itself enumerated, so paths carry up to
            # max_depth + 1 segments below it.
            depth_cap = max_depth + 1 if recursive else 1

            file_entries: List[Dict[str, Union[str, None]]] = []
            dir_paths: set = set()
            for meta in metas:
                segments = meta.path.split("/")
                rel = segments[prefix_len:]
                if len(rel) <= depth_cap:
                    # An empty pattern means no filter — Workspace truthiness, not `is None`
                    # (models do pass pattern="").
                    if not pattern or fnmatch(segments[-1], pattern):
                        file_entries.append({"path": meta.path, "type": "file", "size": _format_size(meta.size_bytes)})
                for k in range(1, min(len(rel) - 1, depth_cap) + 1):
                    dir_path = "/".join(segments[: prefix_len + k])
                    if not pattern or fnmatch(dir_path.split("/")[-1], pattern):
                        dir_paths.add(dir_path)

            sorted_dirs = sorted(dir_paths, key=path_sort_key)
            truncated_dirs = 0
            if len(sorted_dirs) > _MAX_DIR_ENTRIES:
                truncated_dirs = len(sorted_dirs) - _MAX_DIR_ENTRIES
                sorted_dirs = sorted_dirs[:_MAX_DIR_ENTRIES]
            dir_entries: List[Dict[str, Union[str, None]]] = [
                {"path": dir_path, "type": "dir", "size": None} for dir_path in sorted_dirs
            ]

            entries = sorted(file_entries + dir_entries, key=lambda e: path_sort_key(str(e["path"])))
            if truncated_dirs:
                entries.append({"path": f"...and {truncated_dirs} more", "type": "dir", "size": None})

            current_usage = fs.usage()
            return json.dumps(
                {
                    "directory": directory,
                    "pattern": pattern,
                    "recursive": recursive,
                    "files": entries,
                    "usage": {
                        "files": current_usage.file_count,
                        "bytes_used": current_usage.total_bytes,
                        "bytes_limit": fs.max_namespace_bytes,
                    },
                },
                indent=2,
            )
        except InvalidPathError as e:
            return f"Error: {e}"
        except Exception as e:
            log_error(f"list_files failed: {e}")
            return f"Error: {e}"

    def search_content(
        self,
        query: str,
        directory: str = ".",
        limit: int = 10,
        *,
        run_context: Optional[RunContext] = None,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
    ) -> str:
        """Search your files for text (case-insensitive substring match).

        Finds where text appears. To check whether exact records are already stored,
        use check_lines instead — substring matches can mislead there.

        :param query: Substring to search for.
        :param directory: Directory to scope the search (default "." = everything).
        :param limit: Maximum matching files to return (default 10).
        :return: JSON with keys ``query``, ``matches_found``, ``files`` (each
            ``{"file", "size", "snippet"}``).
        """
        try:
            if not query or not query.strip():
                return "Error: query cannot be empty"
            fs = self._resolved(run_context, agent, team)
            matches = fs.search(query, directory=directory, limit=limit)
            files = [
                {"file": match.path, "size": _format_size(match.size_bytes), "snippet": match.snippet}
                for match in matches
            ]
            return json.dumps({"query": query, "matches_found": len(files), "files": files}, indent=2)
        except InvalidPathError as e:
            return f"Error: {e}"
        except Exception as e:
            log_error(f"search_content failed: {e}")
            return f"Error: {e}"

    def check_lines(
        self,
        lines: List[str],
        directory: str = ".",
        *,
        run_context: Optional[RunContext] = None,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
    ) -> str:
        """Check which of these exact lines already exist in your files.

        Exact whole-line matching: a line counts as found only if some file contains
        it as a complete line. Use this before acting on items so you never repeat
        work, then record the new ones with append_file (one per line).

        :param lines: The records to check, e.g. a list of URLs or IDs. Max 200. Pass
            each record in exactly the form you will store it — matching is literal,
            so "example.com/a" and "https://example.com/a/" are different records.
        :param directory: Directory to scope the check (default "." = everything),
            e.g. "seen".
        :return: JSON: {"found": [...], "missing": [...]}.
        """
        try:
            fs = self._resolved(run_context, agent, team)
            result = fs.contains(lines, directory=directory)
            return json.dumps({"found": result.found, "missing": result.missing}, indent=2)
        except InvalidPathError as e:
            return f"Error: {e}"
        except Exception as e:
            log_error(f"check_lines failed: {e}")
            return f"Error: {e}"

    # ------------------------------------------------------------------
    # Write tools
    # ------------------------------------------------------------------

    def write_file(
        self,
        path: str,
        content: str,
        overwrite: bool = True,
        *,
        run_context: Optional[RunContext] = None,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
    ) -> str:
        """Create or overwrite a file. For adding records to a log-style file, use
        append_file instead — it cannot clobber existing lines.

        :param path: File path, e.g. "state/last-run.md". Parent folders are implicit.
        :param content: The complete new file content.
        :param overwrite: If False, fail when the file already exists (default True).
        :return: Success message with the byte count, or an error message.
        """
        try:
            fs = self._resolved(run_context, agent, team)
            meta = fs.write(path, content, overwrite=overwrite)
            return f"Wrote {meta.size_bytes} bytes to {path}"
        except FileExistsError:
            return f"Error: file exists and overwrite=False: {path}"
        except QuotaExceededError as e:
            return self._quota_error(e, path)
        except InvalidPathError as e:
            return f"Error: {e}"
        except Exception as e:
            log_error(f"write_file failed: {e}")
            return f"Error: {e}"

    def append_file(
        self,
        path: str,
        content: str,
        *,
        run_context: Optional[RunContext] = None,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
    ) -> str:
        """Append lines to a file, creating it if needed.

        Line-oriented: appended content always starts on a fresh line and ends with a
        newline. Keep one record per line (one URL, one ID) so check_lines can match
        records exactly.

        :param path: File path, e.g. "seen/2026-07-24.md". Parent folders are implicit.
        :param content: One or more lines to append.
        :return: Success message with the file's new size, or an error message.
        """
        try:
            fs = self._resolved(run_context, agent, team)
            meta = fs.append(path, content)
            chunk = build_chunk(content)
            appended_bytes = len(chunk.encode("utf-8")) if chunk else 0
            return f"Appended {appended_bytes} bytes to {path} (now {meta.size_bytes} bytes)"
        except QuotaExceededError as e:
            return self._quota_error(e, path)
        except InvalidPathError as e:
            return f"Error: {e}"
        except Exception as e:
            log_error(f"append_file failed: {e}")
            return f"Error: {e}"

    def move_file(
        self,
        src: str,
        dst: str,
        overwrite: bool = False,
        *,
        run_context: Optional[RunContext] = None,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
    ) -> str:
        """Move or rename a file.

        :param src: Source file path.
        :param dst: Destination path. Parent folders are implicit.
        :param overwrite: If True, replace dst if it exists (default False).
        :return: Success message, or an error message.
        """
        try:
            fs = self._resolved(run_context, agent, team)
            fs.move(src, dst, overwrite=overwrite)
            return f"Moved {src} -> {dst}"
        except FileNotFoundError:
            return f"Error: file not found: {src}"
        except FileExistsError:
            return f"Error: dst exists and overwrite=False: {dst}"
        except InvalidPathError as e:
            return f"Error: {e}"
        except Exception as e:
            log_error(f"move_file failed: {e}")
            return f"Error: {e}"

    def delete_file(
        self,
        path: str,
        *,
        run_context: Optional[RunContext] = None,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
    ) -> str:
        """Delete a file. This cannot be undone.

        :param path: File path to delete.
        :return: Success message, or an error if the file does not exist.
        """
        try:
            fs = self._resolved(run_context, agent, team)
            if not fs.delete(path):
                return f"Error: file not found: {path}"
            return f"Deleted {path}"
        except InvalidPathError as e:
            return f"Error: {e}"
        except Exception as e:
            log_error(f"delete_file failed: {e}")
            return f"Error: {e}"

    # ------------------------------------------------------------------
    # Async siblings
    # ------------------------------------------------------------------

    async def aread_file(
        self,
        path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        *,
        run_context: Optional[RunContext] = None,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
    ) -> str:
        """Async variant of ``read_file``."""
        return await asyncio.to_thread(
            self.read_file, path, start_line, end_line, run_context=run_context, agent=agent, team=team
        )

    async def alist_files(
        self,
        directory: str = ".",
        pattern: Optional[str] = None,
        recursive: bool = False,
        max_depth: int = 3,
        *,
        run_context: Optional[RunContext] = None,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
    ) -> str:
        """Async variant of ``list_files``."""
        return await asyncio.to_thread(
            self.list_files, directory, pattern, recursive, max_depth, run_context=run_context, agent=agent, team=team
        )

    async def asearch_content(
        self,
        query: str,
        directory: str = ".",
        limit: int = 10,
        *,
        run_context: Optional[RunContext] = None,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
    ) -> str:
        """Async variant of ``search_content``."""
        return await asyncio.to_thread(
            self.search_content, query, directory, limit, run_context=run_context, agent=agent, team=team
        )

    async def acheck_lines(
        self,
        lines: List[str],
        directory: str = ".",
        *,
        run_context: Optional[RunContext] = None,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
    ) -> str:
        """Async variant of ``check_lines``."""
        return await asyncio.to_thread(
            self.check_lines, lines, directory, run_context=run_context, agent=agent, team=team
        )

    async def awrite_file(
        self,
        path: str,
        content: str,
        overwrite: bool = True,
        *,
        run_context: Optional[RunContext] = None,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
    ) -> str:
        """Async variant of ``write_file``."""
        return await asyncio.to_thread(
            self.write_file, path, content, overwrite, run_context=run_context, agent=agent, team=team
        )

    async def aappend_file(
        self,
        path: str,
        content: str,
        *,
        run_context: Optional[RunContext] = None,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
    ) -> str:
        """Async variant of ``append_file``."""
        return await asyncio.to_thread(self.append_file, path, content, run_context=run_context, agent=agent, team=team)

    async def amove_file(
        self,
        src: str,
        dst: str,
        overwrite: bool = False,
        *,
        run_context: Optional[RunContext] = None,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
    ) -> str:
        """Async variant of ``move_file``."""
        return await asyncio.to_thread(
            self.move_file, src, dst, overwrite, run_context=run_context, agent=agent, team=team
        )

    async def adelete_file(
        self,
        path: str,
        *,
        run_context: Optional[RunContext] = None,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
    ) -> str:
        """Async variant of ``delete_file``."""
        return await asyncio.to_thread(self.delete_file, path, run_context=run_context, agent=agent, team=team)
