"""FileSystem: a durable, private filesystem for agents.

To the agent it looks exactly like a normal filesystem toolkit; underneath it is
a pluggable ``BaseFS`` backend, database by default. Use it for the agent's
own working state: records of items already processed, decisions, progress
checkpoints.

Attach with one line, and the toolkit carries its own instructions:

    from agno.agent import Agent
    from agno.db.sqlite import SqliteDb
    from agno.fs import FileSystem

    fs = FileSystem(SqliteDb(db_file="agent.db"))
    agent = Agent(tools=[fs.tools()], instructions="my instructions")
"""

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

DEFAULT_NAMESPACE = "default"
"""Namespace used when the caller does not name one.

A stable, documented default so simple apps need no namespace at all. Set one
explicitly whenever isolation or sharing matters: two FileSystems on the same
backend with no namespace share this one store, which is the intended behavior
but is rarely what a multi-tenant app wants (see the templated namespaces above).
"""

_DEFAULT_INSTRUCTIONS = """You have your own private, durable filesystem you can use to
persist files across sessions and runs. Use it for your working state: records of items you have processed,
decisions, progress checkpoints, notes to your future self.

For storing facts and memories about the user, prefer the user memory if provided and fallback to the filesystem if not.

Conventions:
- Paths are relative, like notes/decisions.md or seen/2026-07-24.md. Group
  related files in directories.
- To keep a record set (items already processed): store one record per line in
  the seen/ directory, one file per date (seen/2026-07-24.md). Call
  check_lines(lines, directory="seen") BEFORE acting, then record the new ones
  with append_file(..., unique=True). check_lines matches exact whole lines, and
  unique=True keeps the log free of duplicates if a run overlaps another one.
- To correct or update part of a file, read it, then call replace_lines with the
  line numbers you saw. Rewriting a whole file with write_file to change a few
  lines wastes effort and risks losing the rest.
- To find something in a large file, use search_content first: it reports the
  line number of each match, which you can pass to read_file as start_line.
- Store extracted facts and identifiers, not raw fetched payloads.
- Never store secrets, passwords, or API keys.
- Files have size limits. If a write is refused, start a new file in your
  partition scheme (e.g. a new dated file), or delete only files you are certain
  are obsolete, like a date partition older than you still need. Never overwrite
  or delete a file of records to make room if you might still need those records:
  dropping them means you will repeat work you already did. If nothing is safely
  disposable, stop and report that storage is full rather than evicting history."""

_READ_ONLY_INSTRUCTIONS = """You have read access to a durable filesystem.
The files persist across sessions and runs.

Use it to look up what you have recorded: items you have processed, decisions
you made, notes you left. You cannot change these files - you have no tool to
write, append, move, or delete.

Conventions:
- Paths are relative, like notes/decisions.md or seen/2026-07-24.md.
- Use check_lines to see what is already recorded before acting."""


def _as_backend(source: Any) -> BaseFS:
    """Resolve the first constructor argument to a storage backend.

    A ``BaseFS`` is used as given. Anything else is a storage handle we recognise
    and wrap, so the common case needs no backend import at all::

        FileSystem(SqliteDb(db_file="agent.db"))   # -> DbFileSystem over that db

    This is the single dispatch point. Each branch detects cheaply (no import) and
    only then imports its backend, which is what keeps ``import agno.fs`` free of
    SQLAlchemy and every other optional dependency. Backends that land later
    (object storage, remote/agent-native stores) add a branch here the same way.
    """
    if isinstance(source, BaseFS):
        return source
    # An agno SQL db (SqliteDb / PostgresDb): keep the agent's files in the same
    # database as its sessions and memory. Detected by its engine, so recognising
    # it costs no import - and holding one means agno.db is already loaded.
    if hasattr(source, "db_engine"):
        from agno.fs.db import DbFileSystem

        return DbFileSystem(db=source)
    raise TypeError(
        f"FileSystem needs a backend or a storage handle it recognises, got {type(source).__name__}. "
        "Pass a SqliteDb/PostgresDb to store files in that database, or a backend "
        "such as DbFileSystem(...) or LocalFileSystem(root=...)."
    )


class FileSystem:
    """A durable, private filesystem scoped to one namespace.

    ``backend`` is a storage backend, or any storage handle FileSystem recognises
    (an agno ``SqliteDb``/``PostgresDb``, wrapped for you); ``namespace`` names this agent's file
    store within it, defaulting to ``"default"`` when you do not need more than
    one. Same ``backend`` + same ``namespace`` = same files; different
    ``namespace`` = full isolation. Sharing is explicit, by name. Isolation is per
    NORMALIZED name: namespaces are lowercased and URL-safe, so ``BANK`` and ``bank``
    address one store. If your identity system treats ``Alice`` and ``alice`` as two
    users, normalize the id before it reaches a templated namespace.

    ``namespace`` may embed the template placeholders ``{user_id}``,
    ``{agent_id}`` and ``{team_id}`` (e.g. ``"radar/{user_id}"``), resolved per
    tool call from framework-injected context only, never from model-supplied
    arguments. A placeholder whose value is missing at call time fails closed.
    Programmatic use of a templated instance goes through ``resolve()``.

    Cheap to construct and holds no connections; the backend owns the
    engine/pool and is shared across instances.
    """

    def __init__(
        self,
        backend: Any,
        namespace: str = DEFAULT_NAMESPACE,
        *,
        max_file_bytes: int = 1_000_000,
        max_namespace_bytes: int = 20_000_000,
    ) -> None:
        self.backend: BaseFS = _as_backend(backend)
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
                f"this agent's files require {self._placeholders[0]} for this run and none was provided."
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
        A missing value raises ``InvalidPathError``, so anonymous runs never
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
        # _stat, not list(): DbFileSystem overrides it as an indexed point select,
        # where listing the parent scans every row in the namespace to find one file.
        existing = self.backend._stat(namespace, normalized)
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

    def append(self, path: str, content: str, *, unique: bool = False) -> FileMeta:
        """Append line-oriented content, creating the file if missing.

        Content that is empty (or only line terminators) is a no-op: no write,
        no version bump, and the file is not created if missing.

        ``unique=True`` drops lines the file already holds, so a record log cannot
        gain a duplicate. It folds check-and-append into one call, which closes the
        window between two separate tool calls, but it is not atomic against a
        concurrent writer on any backend: two workers can still both read the file
        before either appends.
        """
        namespace = self._require_resolved()
        normalized = normalize_path(path)
        chunk = build_chunk(content)
        if chunk and unique:
            chunk = self._drop_present_lines(namespace, normalized, chunk)
        if not chunk:
            existing = self.backend._stat(namespace, normalized)
            if existing is not None:
                return existing
            return FileMeta(path=normalized, size_bytes=0, version=None, updated_at=None)
        chunk_bytes = len(chunk.encode("utf-8"))
        current_usage = self.backend.usage(namespace)
        # The separator is unknown client-side, so estimate it at 1 byte: over, never under.
        if current_usage.total_bytes + chunk_bytes + 1 > self.max_namespace_bytes:
            raise QuotaExceededError(
                f"storage is full ({current_usage.total_bytes} of {self.max_namespace_bytes} bytes)",
                scope="namespace",
                current=current_usage.total_bytes,
                limit=self.max_namespace_bytes,
            )
        return self.backend.append(namespace, normalized, chunk, max_file_bytes=self.max_file_bytes)

    def _drop_present_lines(self, namespace: str, normalized: str, chunk: str) -> str:
        """Return ``chunk`` without lines the file already holds, and without
        lines repeated inside the chunk itself. Order is preserved."""
        existing = self.backend.read(namespace, normalized) or ""
        seen = set(existing.split("\n"))
        kept: List[str] = []
        for line in chunk.split("\n"):
            if not line or line in seen:
                continue
            seen.add(line)
            kept.append(line)
        return build_chunk("\n".join(kept)) if kept else ""

    def replace_lines(self, path: str, start_line: int, end_line: int, content: str = "") -> FileMeta:
        """Replace lines ``start_line`` through ``end_line`` (1-indexed, inclusive) with ``content``.

        Empty ``content`` deletes the range. The file's trailing newline is
        preserved. Raises ``FileNotFoundError`` if the file is missing and
        ``ValueError`` for a range that does not start inside the file.
        """
        namespace = self._require_resolved()
        normalized = normalize_path(path)
        existing = self.backend.read(namespace, normalized)
        if existing is None:
            raise FileNotFoundError(f"file not found: {normalized}")
        if start_line < 1:
            raise ValueError("start_line must be 1 or greater")
        if end_line < start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        lines = existing.split("\n")
        trailing_newline = bool(lines) and lines[-1] == ""
        if trailing_newline:
            lines = lines[:-1]
        if start_line > len(lines):
            raise ValueError(f"start_line {start_line} is past the end of {normalized} ({len(lines)} lines)")
        replacement = content.split("\n") if content else []
        if replacement and replacement[-1] == "":
            replacement = replacement[:-1]
        new_lines = lines[: start_line - 1] + replacement + lines[min(end_line, len(lines)) :]
        new_content = "\n".join(new_lines)
        if new_content and trailing_newline:
            new_content += "\n"
        return self.write(normalized, new_content)

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

    async def aappend(self, path: str, content: str, *, unique: bool = False) -> FileMeta:
        """Async variant of ``append``."""
        return await asyncio.to_thread(self.append, path, content, unique=unique)

    async def areplace_lines(self, path: str, start_line: int, end_line: int, content: str = "") -> FileMeta:
        """Async variant of ``replace_lines``."""
        return await asyncio.to_thread(self.replace_lines, path, start_line, end_line, content)

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
        """Build the toolkit for this file store. ``Agent(tools=[fs.tools()])`` is the whole attach.

        The toolkit carries its own instructions, so do not also pass the same
        instance through the developer-instruction path (the block would render
        twice). ``read_only=True`` registers only ``read_file``, ``list_files``,
        ``search_content`` and ``check_lines``, and selects the read-only
        instructions variant. That is the surface for a consumer agent that
        consults another agent's namespace by shared name. ``**kwargs`` forwards to ``Toolkit``
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
