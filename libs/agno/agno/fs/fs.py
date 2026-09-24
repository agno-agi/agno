"""FileSystem: a durable, private filesystem for agents.

To the agent it looks exactly like a normal filesystem toolkit; underneath it is
a pluggable ``BaseFS`` backend, database by default. Use it for the agent's own
durable notes: decisions with their reasoning, running documents, working state
it will need again.

Attach the tools, and compose its instructions into your own:

    from agno.agent import Agent
    from agno.db.sqlite import SqliteDb
    from agno.fs import FileSystem

    fs = FileSystem(SqliteDb(db_file="agent.db"))
    agent = Agent(
        tools=[fs.tools()],
        instructions=["my instructions", fs.instructions()],
    )
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
    validate_normalized_namespace,
)
from agno.fs.base import BaseFS, partition_kwargs
from agno.fs.errors import InvalidPathError, QuotaExceededError
from agno.fs.types import ContainsResult, FileData, FileMeta, NamespaceUsage, SearchMatch

if TYPE_CHECKING:
    from agno.db.base import BaseDb
    from agno.fs.toolkit import FileSystemTools

DEFAULT_NAMESPACE = "default"
"""Namespace used when the caller does not name one.

A stable, documented default so simple apps need no namespace at all. Set one
explicitly whenever isolation or sharing matters: two FileSystems on the same
backend with no namespace share this one store, which is the intended behavior
but is rarely what a multi-tenant app wants (see the templated namespaces above).
"""

_DEFAULT_INSTRUCTIONS = """You have your own private, durable filesystem for notes that persist across \
sessions and runs. Use it to write, maintain and re-read prose that matters later: decisions with their \
reasoning, running documents on a topic, notes to your future self.

Conventions:
  - Paths are relative, like notes/decisions.md. Group related files in directories.
  - One topic, one file. Add dated entries as things develop; a note is a living document you maintain, not \
a log you only append to.
  - To correct or update part of a file, read it, then call replace_lines with the line numbers you saw. \
Never append a contradiction of what a note already says: fix the wording in place, in the same turn you \
learn it was wrong.
  - To find something, use search_content first: it reports the file and first-match line, which you can \
pass to read_file as start_line. Then answer from what the note says, not from memory.
  - To retire a note that is no longer current, move_file it into an archive/ directory. Do not blank it and \
do not overwrite it: its history may still be needed.
  - Store distilled content, not raw fetched payloads.
  - Never store secrets, passwords, or API keys.
  - Files have size limits. If a write is refused, split the topic into smaller files or archive what is \
finished. Never overwrite a note to make room if you might still need it."""

_READ_ONLY_INSTRUCTIONS = """You have read access to a durable filesystem. The files persist across sessions \
and runs.

Use it to look up what has been recorded: decisions, running documents, notes. You cannot change these \
files - you have no tool to write, append, move, or delete.

Conventions:
  - Paths are relative, like notes/decisions.md.
  - Use search_content to find where something is recorded, then read_file to read it."""


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
    NORMALIZED name: literal namespace text is lowercased and URL-safe, so ``BANK``
    and ``bank`` address one store. Values bound to template placeholders preserve
    identity casing, so users ``Alice`` and ``alice`` remain isolated.

    ``namespace`` may embed the template placeholders ``{user_id}``,
    ``{agent_id}`` and ``{team_id}`` (e.g. ``"radar/{user_id}"``), resolved per
    tool call from framework-injected context only, never from model-supplied
    arguments. A placeholder whose value is missing at call time fails closed.
    Programmatic use of a templated instance goes through ``resolve()``.

    Files are further keyed by a user partition, and a run acts in the partition
    of its user: two users of one namespace never see each other's files, the
    same way memories are kept per user. A run with no user uses the shared
    partition. ``user_scoped=True`` refuses to run without a user, and
    ``user_scoped=False`` keeps the whole namespace shared whoever runs it.
    A user passed to ``resolve()`` selects that partition regardless.

    Use ``db=SqliteDb(...)`` or ``db=PostgresDb(...)`` to borrow a synchronous
    database, or ``backend=`` for an explicit backend. Supply exactly one source.

    Cheap to construct and holds no connections; the backend owns the
    engine/pool and is shared across instances.
    """

    def __init__(
        self,
        backend: Any = None,
        namespace: str = DEFAULT_NAMESPACE,
        *,
        db: Optional["BaseDb"] = None,
        max_file_bytes: int = 1_000_000,
        max_namespace_bytes: int = 20_000_000,
        user_scoped: Optional[bool] = None,
    ) -> None:
        if (backend is None) == (db is None):
            raise ValueError("Provide exactly one of backend or db")
        if db is not None:
            from agno.fs.db import DbFileSystem

            backend = DbFileSystem(db=db)
        self.backend: BaseFS = _as_backend(backend)
        self._raw_namespace = namespace
        self._namespace_is_normalized = False
        self.namespace = normalize_namespace(namespace)
        self.max_file_bytes = max_file_bytes
        self.max_namespace_bytes = max_namespace_bytes
        self._placeholders: Tuple[str, ...] = parse_namespace_template(self.namespace)
        self.user_scoped = user_scoped
        # The user partition this instance acts in, bound by resolve(). None is the shared partition.
        self._user_id: Optional[str] = None
        # A namespace naming {user_id} isolates by name, so its files stay in the
        # shared partition: the user is in the key already, and data written
        # before partitions exist under exactly that key.
        self._namespace_carries_user = "user_id" in self._placeholders

    @classmethod
    def _from_normalized(
        cls,
        *,
        backend: Any,
        namespace: str,
        max_file_bytes: int,
        max_namespace_bytes: int,
        user_scoped: Optional[bool] = None,
        user_id: Optional[str] = None,
    ) -> "FileSystem":
        """Build a derived instance whose namespace is already canonical."""
        instance = cls.__new__(cls)
        instance.backend = _as_backend(backend)
        instance._raw_namespace = namespace
        instance._namespace_is_normalized = True
        instance.namespace = validate_normalized_namespace(namespace)
        instance.max_file_bytes = max_file_bytes
        instance.max_namespace_bytes = max_namespace_bytes
        instance._placeholders = parse_namespace_template(namespace)
        instance.user_scoped = user_scoped
        instance._user_id = user_id
        instance._namespace_carries_user = "user_id" in instance._placeholders
        return instance

    @property
    def user_id(self) -> Optional[str]:
        """The user partition bound by ``resolve()``; ``None`` is the shared partition."""
        return self._user_id

    def _partition(self) -> str:
        """The backend partition every operation of this instance acts in.

        A user-scoped instance with no bound user fails closed: an anonymous run
        must never fall into the shared partition, nor into another user's.
        """
        if self._namespace_carries_user:
            return ""
        if self._user_id is not None:
            return self._user_id
        if self.user_scoped:
            raise InvalidPathError(
                "this filesystem is partitioned by user and no user is bound; resolve it with a user_id first"
            )
        return ""

    def _pk(self, method: Any) -> dict:
        """Keyword arguments selecting this instance's partition for one backend call."""
        return partition_kwargs(method, self._partition())

    def to_dict(self) -> dict:
        """Serialize built-in backend settings without serializing live connections."""
        from agno.fs.db import DbFileSystem
        from agno.fs.local import LocalFileSystem

        if isinstance(self.backend, DbFileSystem):
            db_id = getattr(getattr(self.backend, "db", None), "id", None)
            if not isinstance(db_id, str) or not db_id:
                raise TypeError(
                    "Cannot serialize a database-backed filesystem without an Agno database id; "
                    "construct DbFileSystem with db=SqliteDb/PostgresDb and register that database."
                )
            backend = {
                "type": "db",
                "db_id": db_id,
                "table_name": self.backend.table_name,
                "db_schema": self.backend.db_schema,
            }
        elif isinstance(self.backend, LocalFileSystem):
            backend = {"type": "local", "root": str(self.backend.root)}
        else:
            raise TypeError(
                f"Cannot serialize filesystem backend {type(self.backend).__name__}; "
                "configure this filesystem from application code."
            )
        config = {
            "backend": backend,
            # The constructor input is required here. Serializing the canonical
            # percent-encoded value and normalizing it again changes %20 to %2520.
            "namespace": self._raw_namespace,
            "max_file_bytes": self.max_file_bytes,
            "max_namespace_bytes": self.max_namespace_bytes,
        }
        if self._namespace_is_normalized:
            config["namespace_is_normalized"] = True
        if self.user_scoped is not None:
            config["user_scoped"] = self.user_scoped
        return config

    @classmethod
    def from_dict(cls, data: dict, *, db: Any = None) -> "FileSystem":
        """Rebuild a filesystem config, reusing the owning Agent database when needed."""
        backend_config = data.get("backend") or {}
        backend_type = backend_config.get("type")
        if backend_type == "db":
            if db is None:
                raise ValueError("A database is required to restore a database-backed filesystem")
            db_id = backend_config.get("db_id")
            if db_id is not None and getattr(db, "id", None) != db_id:
                raise ValueError(f"filesystem requires database {db_id!r}, got {getattr(db, 'id', None)!r}")
            from agno.fs.db import DbFileSystem

            backend: BaseFS = DbFileSystem(
                db=db,
                table_name=backend_config.get("table_name", "agno_fs"),
                db_schema=backend_config.get("db_schema", "fs"),
            )
        elif backend_type == "local":
            from agno.fs.local import LocalFileSystem

            root = backend_config.get("root")
            if not isinstance(root, str) or not root:
                raise ValueError("A root path is required to restore a local filesystem")
            backend = LocalFileSystem(root=root)
        else:
            raise ValueError(f"Unsupported filesystem backend type: {backend_type!r}")
        namespace = data.get("namespace", DEFAULT_NAMESPACE)
        max_file_bytes = data.get("max_file_bytes", 1_000_000)
        max_namespace_bytes = data.get("max_namespace_bytes", 20_000_000)
        user_scoped = data.get("user_scoped")
        if data.get("namespace_is_normalized") is True:
            return cls._from_normalized(
                backend=backend,
                namespace=namespace,
                max_file_bytes=max_file_bytes,
                max_namespace_bytes=max_namespace_bytes,
                user_scoped=user_scoped,
            )
        return cls(
            backend=backend,
            namespace=namespace,
            max_file_bytes=max_file_bytes,
            max_namespace_bytes=max_namespace_bytes,
            user_scoped=user_scoped,
        )

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
        with unresolved placeholders raises ``InvalidPathError``. A ``user_id``
        also selects that user's partition on the bound instance, whether or
        not the namespace names the user; so a literal namespace resolved with
        a user returns a bound copy, and an untemplated instance resolved with
        no user is returned unchanged.
        """
        bound_user = self._user_id if user_id is None else str(user_id)
        if not self._placeholders and bound_user == self._user_id:
            return self
        values = {"user_id": user_id, "agent_id": agent_id, "team_id": team_id}
        name = self.namespace
        for placeholder in set(self._placeholders):
            value = values.get(placeholder)
            if value is None:
                continue
            name = name.replace("{" + placeholder + "}", normalize_template_value(placeholder, value))
        resolved = FileSystem._from_normalized(
            backend=self.backend,
            namespace=name,
            max_file_bytes=self.max_file_bytes,
            max_namespace_bytes=self.max_namespace_bytes,
            user_scoped=self.user_scoped,
            user_id=bound_user,
        )
        resolved._namespace_carries_user = self._namespace_carries_user
        return resolved

    def _resolve_from_context(
        self,
        run_context: Any = None,
        agent: Any = None,
        team: Any = None,
        *,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> "FileSystem":
        """Resolve template placeholders from framework-injected context. Fails closed.

        ``{user_id}`` reads ``run_context.user_id``; ``{agent_id}`` reads the
        injected agent's ``id``; ``{team_id}`` reads the injected team's ``id``.
        A missing value raises ``InvalidPathError``, so anonymous runs never
        silently collapse into a shared namespace.

        The run's user selects their partition, unless ``user_scoped=False``
        keeps the namespace shared. ``user_scoped=True`` refuses a run with no
        user; otherwise such a run uses the shared partition.
        """
        context_user = user_id if user_id is not None else getattr(run_context, "user_id", None)
        if context_user is not None and not str(context_user).strip():
            context_user = None
        if self.user_scoped and context_user is None:
            raise InvalidPathError("this filesystem is partitioned by user and the run has no user_id")
        bind_user = self.user_scoped is not False or "user_id" in self._placeholders
        resolved = self.resolve(
            user_id=context_user if bind_user else None,
            agent_id=agent_id if agent_id is not None else getattr(agent, "id", None),
            team_id=team_id if team_id is not None else getattr(team, "id", None),
        )
        resolved._require_resolved()
        return resolved

    # ------------------------------------------------------------------
    # Programmatic API (sync)
    # ------------------------------------------------------------------

    def read(self, path: str) -> Optional[str]:
        """Return the file's content, or ``None`` if it does not exist."""
        namespace = self._require_resolved()
        return self.backend.read(namespace, normalize_path(path), **self._pk(self.backend.read))

    def read_with_meta(self, path: str) -> Optional[FileData]:
        """Return content and metadata from one consistent backend read."""
        namespace = self._require_resolved()
        return self.backend.read_with_meta(namespace, normalize_path(path), **self._pk(self.backend.read_with_meta))

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
        existing = self.backend._stat(namespace, normalized, **self._pk(self.backend._stat))
        if existing is not None and not overwrite:
            raise FileExistsError(f"file exists: {normalized}")
        delta = size_bytes - (existing.size_bytes if existing is not None else 0)
        if delta > 0:
            current_usage = self.backend.usage(namespace, **self._pk(self.backend.usage))
            if current_usage.total_bytes + delta > self.max_namespace_bytes:
                raise QuotaExceededError(
                    f"storage is full ({current_usage.total_bytes} of {self.max_namespace_bytes} bytes)",
                    scope="namespace",
                    current=current_usage.total_bytes,
                    limit=self.max_namespace_bytes,
                )
        return self.backend.write(
            namespace,
            normalized,
            content,
            expected_version=expected_version,
            **self._pk(self.backend.write),
        )

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
            existing = self.backend._stat(namespace, normalized, **self._pk(self.backend._stat))
            if existing is not None:
                return existing
            return FileMeta(path=normalized, size_bytes=0, version=None, updated_at=None)
        chunk_bytes = len(chunk.encode("utf-8"))
        current_usage = self.backend.usage(namespace, **self._pk(self.backend.usage))
        # The separator is unknown client-side, so estimate it at 1 byte: over, never under.
        if current_usage.total_bytes + chunk_bytes + 1 > self.max_namespace_bytes:
            raise QuotaExceededError(
                f"storage is full ({current_usage.total_bytes} of {self.max_namespace_bytes} bytes)",
                scope="namespace",
                current=current_usage.total_bytes,
                limit=self.max_namespace_bytes,
            )
        return self.backend.append(
            namespace,
            normalized,
            chunk,
            max_file_bytes=self.max_file_bytes,
            **self._pk(self.backend.append),
        )

    def _drop_present_lines(self, namespace: str, normalized: str, chunk: str) -> str:
        """Return ``chunk`` without lines the file already holds, and without
        lines repeated inside the chunk itself. Order is preserved."""
        existing = self.backend.read(namespace, normalized, **self._pk(self.backend.read)) or ""
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
        existing = self.backend.read(namespace, normalized, **self._pk(self.backend.read))
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
        return self.backend.move(
            namespace, normalize_path(src), normalize_path(dst), overwrite=overwrite, **self._pk(self.backend.move)
        )

    def delete(self, path: str) -> bool:
        """Delete a file. Returns ``True`` if it existed."""
        namespace = self._require_resolved()
        return self.backend.delete(namespace, normalize_path(path), **self._pk(self.backend.delete))

    def list(self, directory: str = "") -> List[FileMeta]:
        """List files under ``directory`` (``""`` or ``"."`` = namespace root), sorted by path segments."""
        namespace = self._require_resolved()
        metas = self.backend.list(namespace, normalize_directory(directory), **self._pk(self.backend.list))
        return sorted(metas, key=lambda m: path_sort_key(m.path))

    def search(self, query: str, directory: str = "", limit: int = 10) -> List[SearchMatch]:
        """Case-insensitive substring search. Returns at most ``limit`` matches."""
        namespace = self._require_resolved()
        if not query or not query.strip():
            return []
        return self.backend.search(
            namespace, query, normalize_directory(directory), limit, **self._pk(self.backend.search)
        )

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
        found_set = self.backend.contains(
            namespace, normalized_lines, normalized_directory, **self._pk(self.backend.contains)
        )
        return ContainsResult(
            found=[line for line in normalized_lines if line in found_set],
            missing=[line for line in normalized_lines if line not in found_set],
        )

    def usage(self) -> NamespaceUsage:
        """Aggregate file count and total bytes for this namespace."""
        namespace = self._require_resolved()
        return self.backend.usage(namespace, **self._pk(self.backend.usage))

    # ------------------------------------------------------------------
    # Programmatic API (async twins)
    # ------------------------------------------------------------------

    async def aread(self, path: str) -> Optional[str]:
        """Async variant of ``read``."""
        return await asyncio.to_thread(self.read, path)

    async def aread_with_meta(self, path: str) -> Optional[FileData]:
        """Async variant of ``read_with_meta``."""
        namespace = self._require_resolved()
        return await self.backend.aread_with_meta(
            namespace, normalize_path(path), **self._pk(self.backend.aread_with_meta)
        )

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

    def tools(self, *, read_only: bool = False, allow_delete: bool = False, **kwargs) -> "FileSystemTools":
        """Build the toolkit for this file store.

        ``Agent(tools=[fs.tools()], instructions=[..., fs.instructions()])`` is the
        whole attach: the tools arrive with no instructions of their own, and the
        system prompt stays the developer's to order and edit. Pass
        ``add_instructions=True`` to have the toolkit carry them instead.

        The default surface is the notes seven: ``read_file``, ``write_file``,
        ``append_file``, ``replace_lines``, ``list_files``, ``search_content``,
        ``move_file``. ``allow_delete=True`` adds ``delete_file`` - destructive
        is opt-in; archiving with ``move_file`` is the blessed retirement flow.
        ``check_lines`` (the batched record-set membership test feed agents use)
        is requested by name via ``include_tools``, which selects from the whole
        surface when passed.

        ``read_only=True`` registers only ``read_file``, ``list_files`` and
        ``search_content``; pair it with ``instructions(read_only=True)``. That
        is the surface for a consumer agent that consults another agent's
        namespace by shared name. ``**kwargs`` forwards to ``Toolkit`` (e.g.
        ``include_tools``, ``requires_confirmation_tools``).
        """
        from agno.fs.toolkit import FileSystemTools

        return FileSystemTools(fs=self, read_only=read_only, allow_delete=allow_delete, **kwargs)

    @staticmethod
    def instructions(read_only: bool = False) -> str:
        """Usage guidance for these tools, to compose into the agent's instructions.

        Namespace-independent, so it is equally callable on an instance
        (``fs.instructions()``) and on the class, which is what a per-user tool
        factory needs when no instance exists at module scope.
        """
        if read_only:
            return _READ_ONLY_INSTRUCTIONS
        return _DEFAULT_INSTRUCTIONS
