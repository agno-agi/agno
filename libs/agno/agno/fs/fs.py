"""FileSystem — a durable, private filesystem for agents.

To the agent it looks exactly like a normal filesystem toolkit; underneath it is
a pluggable ``BaseFS`` backend, database by default. Use it for the agent's
own working state: records of items already processed, decisions, progress
checkpoints — the fourth kind of state (not memory, not session, not knowledge).

Attach with one line — the toolkit carries its own instructions:

    from agno.agent import Agent
    from agno.fs import FileSystem
    from agno.fs.db import DbFileSystem

    fs = FileSystem(backend=DbFileSystem(db_url=...), namespace="radar")
    agent = Agent(tools=[fs.tools()], instructions="my instructions")

FileSystem is also a complete durable-filesystem API without any Agent:
``fs.read(...)``, ``fs.append(...)``, ``fs.contains(...)`` from plain Python.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, List, Optional, Sequence, Tuple

from agno.fs._paths import (
    build_chunk,
    normalize_check_lines,
    normalize_directory,
    normalize_namespace,
    normalize_path,
    normalize_template_value,
    parse_namespace_template,
    path_sort_key,
)
from agno.fs.base import BaseFS
from agno.fs.errors import InvalidPathError, QuotaExceededError
from agno.fs.types import ContainsResult, FileMeta, NamespaceUsage, SearchMatch

if TYPE_CHECKING:
    from agno.tools.toolkit import Toolkit

_DEFAULT_INSTRUCTIONS = """You have your own private, durable filesystem. Files persist across sessions and
runs: anything you write is available in every future run.

Use it for your own working state: records of items you have already processed,
decisions, progress checkpoints, notes to your future self. Do not use it for
facts about the user (that belongs in memory) or scratch work for the current
reply.

These files are the only state you carry from one run to the next. Before
starting work that may have been started before - a recurring job, a long task
you could have checkpointed, a set of items you may already have processed -
call list_files to see what you have, then read what is relevant.

Conventions:
- Paths are relative, like notes/decisions.md or seen/2026-07-24.md. Group
  related files in directories.
- To keep a record set (items already processed): store one record per line in
  the seen/ directory, one file per date (seen/2026-07-24.md). Call
  check_lines(lines, directory="seen") BEFORE acting, then record the new ones
  with append_file. check_lines matches exact whole lines.
- Store extracted facts and identifiers, not raw fetched payloads.
- Never store secrets, passwords, or API keys.
- Files have size limits. If a write is refused, start a new file in your
  partition scheme or delete files you no longer need."""

_READ_ONLY_INSTRUCTIONS = """You have read access to a durable filesystem written by another agent. The files
persist across sessions and runs.

Use it to look up what that agent has recorded: items it has processed, decisions
it made, notes it left. You cannot change these files - you have no tool to
write, append, move, or delete.

Before answering something these files might already cover, call list_files to
see what is there, then read what is relevant.

Conventions:
- Paths are relative, like notes/decisions.md or seen/2026-07-24.md.
- search_content finds where text appears. check_lines answers whether exact
  whole lines are already recorded - reach for it, not search_content, when you
  need an exact answer about specific records."""


class FileSystem:
    """A durable, private filesystem scoped to one namespace.

    ``fs`` is the storage backend; ``namespace`` names this agent's file store
    within it. Same ``fs`` + same ``namespace`` = same files; different
    ``namespace`` = full isolation. Sharing is explicit, by name.

    ``namespace`` may embed the template placeholders ``{user_id}``,
    ``{agent_id}`` and ``{team_id}`` (e.g. ``"radar/{user_id}"``), resolved per
    tool call from framework-injected context only — never from model-supplied
    arguments. A placeholder whose value is missing at call time fails closed.
    Programmatic use of a templated instance goes through ``resolve()``.

    Cheap to construct and holds no connections; the backend owns the
    engine/pool and is shared across instances.
    """

    def __init__(
        self,
        backend: BaseFS,
        namespace: str,
        *,
        max_file_bytes: int = 1_000_000,
        max_namespace_bytes: int = 20_000_000,
    ) -> None:
        self.backend = backend
        self.namespace = normalize_namespace(namespace)
        self.max_file_bytes = max_file_bytes
        self.max_namespace_bytes = max_namespace_bytes
        self._placeholders: Tuple[str, ...] = parse_namespace_template(self.namespace)

    # ------------------------------------------------------------------
    # Templated namespaces
    # ------------------------------------------------------------------

    @property
    def is_templated(self) -> bool:
        """Whether the namespace still contains unresolved template placeholders."""
        return bool(self._placeholders)

    def _require_resolved(self) -> str:
        if self._placeholders:
            raise InvalidPathError(
                f"this agent's files require a {self._placeholders[0]} for this run and none was provided."
            )
        return self.namespace

    def resolve(
        self,
        *,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> "FileSystem":
        """Bind a templated namespace to concrete values and return the bound instance.

        Values are validated as single path segments. Placeholders without a
        value stay unresolved, and calling any file operation on an instance
        with unresolved placeholders raises ``InvalidPathError``. Untemplated
        instances are returned unchanged.
        """
        if not self._placeholders:
            return self
        values = {"user_id": user_id, "agent_id": agent_id, "team_id": team_id}
        name = self.namespace
        for placeholder in set(self._placeholders):
            value = values.get(placeholder)
            if value is None:
                continue
            name = name.replace("{" + placeholder + "}", normalize_template_value(placeholder, value))
        return FileSystem(
            backend=self.backend,
            namespace=name,
            max_file_bytes=self.max_file_bytes,
            max_namespace_bytes=self.max_namespace_bytes,
        )

    def _resolve_from_context(self, run_context: Any = None, agent: Any = None, team: Any = None) -> "FileSystem":
        """Resolve template placeholders from framework-injected context. Fails closed.

        ``{user_id}`` reads ``run_context.user_id``; ``{agent_id}`` reads the
        injected agent's ``id``; ``{team_id}`` reads the injected team's ``id``.
        A missing value raises ``InvalidPathError`` — anonymous runs never
        silently collapse into a shared namespace.
        """
        if not self._placeholders:
            return self
        resolved = self.resolve(
            user_id=getattr(run_context, "user_id", None) if run_context is not None else None,
            agent_id=getattr(agent, "id", None) if agent is not None else None,
            team_id=getattr(team, "id", None) if team is not None else None,
        )
        resolved._require_resolved()
        return resolved

    # ------------------------------------------------------------------
    # Programmatic API (sync)
    # ------------------------------------------------------------------

    def read(self, path: str) -> Optional[str]:
        """Return the file's content, or ``None`` if it does not exist."""
        namespace = self._require_resolved()
        return self.backend.read(namespace, normalize_path(path))

    def write(
        self,
        path: str,
        content: str,
        *,
        overwrite: bool = True,
        expected_version: Optional[int] = None,
    ) -> FileMeta:
        """Create or replace a file. Last-writer-wins unless ``expected_version`` is passed.

        ``overwrite=False`` raises the builtin ``FileExistsError`` if the file
        exists (checked above the backend; racy under concurrency, in the same
        class as the last-writer-wins semantics).
        """
        namespace = self._require_resolved()
        normalized = normalize_path(path)
        size_bytes = len(content.encode("utf-8"))
        if size_bytes > self.max_file_bytes:
            raise QuotaExceededError(
                f"{normalized} would be {size_bytes} bytes (limit {self.max_file_bytes} per file)",
                scope="file",
                current=size_bytes,
                limit=self.max_file_bytes,
            )
        parent = "/".join(normalized.split("/")[:-1])
        existing = next((m for m in self.backend.list(namespace, parent) if m.path == normalized), None)
        if existing is not None and not overwrite:
            raise FileExistsError(f"file exists: {normalized}")
        delta = size_bytes - (existing.size_bytes if existing is not None else 0)
        if delta > 0:
            current_usage = self.backend.usage(namespace)
            if current_usage.total_bytes + delta > self.max_namespace_bytes:
                raise QuotaExceededError(
                    f"storage is full ({current_usage.total_bytes} of {self.max_namespace_bytes} bytes)",
                    scope="namespace",
                    current=current_usage.total_bytes,
                    limit=self.max_namespace_bytes,
                )
        return self.backend.write(namespace, normalized, content, expected_version=expected_version)

    def append(self, path: str, content: str) -> FileMeta:
        """Append line-oriented content, creating the file if missing.

        Content that is empty (or only line terminators) is a no-op: no write,
        no version bump, and the file is not created if missing.
        """
        namespace = self._require_resolved()
        normalized = normalize_path(path)
        chunk = build_chunk(content)
        if not chunk:
            existing = self.backend._stat(namespace, normalized)
            if existing is not None:
                return existing
            return FileMeta(path=normalized, size_bytes=0, version=None, updated_at=None)
        chunk_bytes = len(chunk.encode("utf-8"))
        current_usage = self.backend.usage(namespace)
        # The separator is unknown client-side, so estimate it at 1 byte — over, never under.
        if current_usage.total_bytes + chunk_bytes + 1 > self.max_namespace_bytes:
            raise QuotaExceededError(
                f"storage is full ({current_usage.total_bytes} of {self.max_namespace_bytes} bytes)",
                scope="namespace",
                current=current_usage.total_bytes,
                limit=self.max_namespace_bytes,
            )
        return self.backend.append(namespace, normalized, chunk, max_file_bytes=self.max_file_bytes)

    def move(self, src: str, dst: str, *, overwrite: bool = False) -> FileMeta:
        """Move or rename a file. Raises ``FileNotFoundError`` if ``src`` is missing,
        ``FileExistsError`` if ``dst`` exists and ``overwrite`` is False."""
        namespace = self._require_resolved()
        return self.backend.move(namespace, normalize_path(src), normalize_path(dst), overwrite=overwrite)

    def delete(self, path: str) -> bool:
        """Delete a file. Returns ``True`` if it existed."""
        namespace = self._require_resolved()
        return self.backend.delete(namespace, normalize_path(path))

    def list(self, directory: str = "") -> List[FileMeta]:
        """List files under ``directory`` (``""`` or ``"."`` = namespace root), sorted by path segments."""
        namespace = self._require_resolved()
        metas = self.backend.list(namespace, normalize_directory(directory))
        return sorted(metas, key=lambda m: path_sort_key(m.path))

    def search(self, query: str, directory: str = "", limit: int = 10) -> List[SearchMatch]:
        """Case-insensitive substring search. Returns at most ``limit`` matches."""
        namespace = self._require_resolved()
        if not query or not query.strip():
            return []
        return self.backend.search(namespace, query, normalize_directory(directory), limit)

    def contains(self, lines: Sequence[str], directory: str = "") -> ContainsResult:
        """Batch exact-line membership check, input order preserved.

        Lines are normalized with the same transform ``append`` applies, so a
        record stored through ``append`` is always found in the form it was
        stored. An input that is empty after normalization short-circuits with
        no backend call.
        """
        namespace = self._require_resolved()
        normalized_directory = normalize_directory(directory)
        normalized_lines = normalize_check_lines(lines)
        if not normalized_lines:
            return ContainsResult(found=[], missing=[])
        found_set = self.backend.contains(namespace, normalized_lines, normalized_directory)
        return ContainsResult(
            found=[line for line in normalized_lines if line in found_set],
            missing=[line for line in normalized_lines if line not in found_set],
        )

    def usage(self) -> NamespaceUsage:
        """Aggregate file count and total bytes for this namespace."""
        namespace = self._require_resolved()
        return self.backend.usage(namespace)

    # ------------------------------------------------------------------
    # Programmatic API (async twins)
    # ------------------------------------------------------------------

    async def aread(self, path: str) -> Optional[str]:
        """Async variant of ``read``."""
        return await asyncio.to_thread(self.read, path)

    async def awrite(
        self,
        path: str,
        content: str,
        *,
        overwrite: bool = True,
        expected_version: Optional[int] = None,
    ) -> FileMeta:
        """Async variant of ``write``."""
        return await asyncio.to_thread(
            self.write, path, content, overwrite=overwrite, expected_version=expected_version
        )

    async def aappend(self, path: str, content: str) -> FileMeta:
        """Async variant of ``append``."""
        return await asyncio.to_thread(self.append, path, content)

    async def amove(self, src: str, dst: str, *, overwrite: bool = False) -> FileMeta:
        """Async variant of ``move``."""
        return await asyncio.to_thread(self.move, src, dst, overwrite=overwrite)

    async def adelete(self, path: str) -> bool:
        """Async variant of ``delete``."""
        return await asyncio.to_thread(self.delete, path)

    async def alist(self, directory: str = "") -> List[FileMeta]:
        """Async variant of ``list``."""
        return await asyncio.to_thread(self.list, directory)

    async def asearch(self, query: str, directory: str = "", limit: int = 10) -> List[SearchMatch]:
        """Async variant of ``search``."""
        return await asyncio.to_thread(self.search, query, directory, limit)

    async def acontains(self, lines: Sequence[str], directory: str = "") -> ContainsResult:
        """Async variant of ``contains``."""
        return await asyncio.to_thread(self.contains, lines, directory)

    async def ausage(self) -> NamespaceUsage:
        """Async variant of ``usage``."""
        return await asyncio.to_thread(self.usage)

    # ------------------------------------------------------------------
    # Agent surface
    # ------------------------------------------------------------------

    def tools(self, *, read_only: bool = False, **kwargs) -> "Toolkit":
        """Build the toolkit for this file store — ``Agent(tools=[fs.tools()])`` is the whole attach.

        The toolkit carries its own instructions, so do not also pass the same
        instance through the developer-instruction path (the block would render
        twice). ``read_only=True`` registers only ``read_file``, ``list_files``,
        ``search_content`` and ``check_lines`` — the surface for a consumer agent
        that consults another agent's namespace by shared name — and selects the
        read-only instructions variant. ``**kwargs`` forwards to ``Toolkit``
        (e.g. ``include_tools``, ``requires_confirmation_tools``).
        """
        from agno.fs.toolkit import FileSystemTools

        return FileSystemTools(fs=self, read_only=read_only, **kwargs)

    @staticmethod
    def instructions(read_only: bool = False) -> str:
        """The instructions the toolkit ships (namespace-independent, usable with no instance)."""
        if read_only:
            return _READ_ONLY_INSTRUCTIONS
        return _DEFAULT_INSTRUCTIONS
