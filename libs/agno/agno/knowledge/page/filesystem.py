"""Read-only commands and lazy, revision-coherent access to one Knowledge namespace."""

from __future__ import annotations

import hashlib
import math
from collections import OrderedDict
from collections.abc import Iterator, Mapping
from threading import Lock
from typing import TYPE_CHECKING, Optional

from agno.knowledge.page.types import GrepResult, Page, PageError, PageNotFound
from agno.utils.bounded import BoundedWorkers, WorkBudget

if TYPE_CHECKING:
    from agno.knowledge.knowledge import Knowledge
    from agno.tools.toolkit import Toolkit

_COMMAND_WORKERS = BoundedWorkers(8, "page-filesystem")


class PageFileSystem:
    """Read-only command adapter with opt-in tools and no prompt insertion.

    Commands use public Knowledge page APIs. Each command gets a fresh metadata
    snapshot, and cached bodies are validated against current publication before
    reuse. Cache storage belongs to this instance, never another store/namespace.
    Output is capped at max_output_chars plus a short continuation notice.
    Async cancellation retains worker capacity until the actual work finishes.
    """

    def __init__(
        self,
        *,
        knowledge: Knowledge,
        max_output_chars: int = 30_000,
        max_pattern_chars: int = 256,
        regex_match_timeout: float = 0.05,
        regex_command_seconds: float = 2.0,
        command_seconds: float = 10.0,
        max_cached_bytes: int = 32 * 1024 * 1024,
        max_cached_entries: int = 8192,
        max_read_chars: int = 32 * 1024 * 1024,
        max_catalog_entries: int = 100_000,
    ):
        try:
            import regex  # noqa: F401
        except ImportError as exc:
            raise ImportError("PageFileSystem requires regex. Install it with `pip install 'agno[pages]'`.") from exc
        for name, value in locals().copy().items():
            if name.startswith("max_"):
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise ValueError(f"{name} must be a positive integer")
            elif name in ("regex_match_timeout", "regex_command_seconds", "command_seconds"):
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (float, int))
                    or not math.isfinite(value)
                    or value <= 0
                ):
                    raise ValueError(f"{name} must be finite and positive")
        self.knowledge = knowledge
        self.max_output_chars = max_output_chars
        self.max_pattern_chars = max_pattern_chars
        self.regex_match_timeout = regex_match_timeout
        self.regex_command_seconds = regex_command_seconds
        self.command_seconds = command_seconds
        self.max_cached_bytes = max_cached_bytes
        self.max_cached_entries = max_cached_entries
        self.max_read_chars = max_read_chars
        self.max_catalog_entries = max_catalog_entries
        self._bodies: OrderedDict[tuple[str, str, int], tuple[str, int]] = OrderedDict()
        self._body_bytes = 0
        self._body_lock = Lock()

    def _run(self, command: str, *, budget: WorkBudget) -> str:
        from agno.knowledge.page._commands import run_command

        return run_command(command, PageCorpus(self, budget=budget))

    def run_command(self, command: str) -> str:
        """Run ls/tree/find/cat/head/tail/wc/rg/grep within bounded worker capacity.

        Grammar errors return readable text. Publication/storage errors raise
        PageError so applications can retain their own unavailable wording.
        """
        try:
            return _COMMAND_WORKERS.run_sync(self._run, command, seconds=self.command_seconds)
        except TimeoutError as exc:
            raise PageError() from exc

    async def arun_command(self, command: str) -> str:
        """Run the same command without blocking the event loop."""
        try:
            return await _COMMAND_WORKERS.run(self._run, command, seconds=self.command_seconds)
        except TimeoutError as exc:
            raise PageError() from exc

    def tools(self, *, tool_name: str = "query_pages", description: Optional[str] = None) -> Toolkit:
        """Build one read-only command tool for ``Agent(tools=[files.tools()])``.

        Sync and async runs select their corresponding command implementation.
        The tool returns readable page errors; direct command methods still raise
        PageError. Applications retain setup, retrieval timing and instructions.
        """
        from agno.knowledge.page._commands import USAGE
        from agno.knowledge.page.types import tool_error
        from agno.tools.toolkit import Toolkit

        if not tool_name or not tool_name.strip():
            raise ValueError("tool_name must not be empty")

        def query_pages(command: str) -> str:
            try:
                return self.run_command(command)
            except PageError as exc:
                return tool_error(exc)

        async def aquery_pages(command: str) -> str:
            try:
                return await self.arun_command(command)
            except PageError as exc:
                return tool_error(exc)

        query_pages.__name__ = tool_name
        toolkit = Toolkit(name="page_filesystem", tools=[query_pages], async_tools=[(aquery_pages, tool_name)])
        tool_description = (
            description
            if description is not None
            else (
                "Browse, read or search published documentation pages as Markdown files. "
                "Commands are emulated against indexed pages; they cannot execute a shell or write files. "
                "Incomplete searches do not establish absence. "
                f"Output is bounded to {self.max_output_chars} characters plus a continuation notice.\n\n"
                + USAGE
                + '\nExamples: cat /agents/overview; ls /agents; rg -C 2 "tool_call_limit" /agents.'
            )
        )
        for function in (toolkit.functions[tool_name], toolkit.async_functions[tool_name]):
            function.description = tool_description
        return toolkit

    def get_corpus(self, *, lazy: bool = False, prefix: str = "/") -> PageCorpus:
        """Get a bounded command-local page mapping, optionally scoped to a prefix.

        Mapping access is synchronous. Async callers should use arun_command
        instead of iterating or loading this mapping on the event loop.
        """
        corpus = PageCorpus(self, prefix=prefix)
        if not lazy:
            corpus._pages = corpus._list(corpus.prefix)
        return corpus

    async def aget_corpus(self, *, prefix: str = "/") -> PageCorpus:
        """Fetch a metadata snapshot off the event loop; later mapping access is sync."""

        def listing(*, budget: WorkBudget) -> PageCorpus:
            corpus = PageCorpus(self, budget=budget, prefix=prefix)
            corpus._pages = corpus._list(corpus.prefix)
            return corpus

        try:
            return await _COMMAND_WORKERS.run(listing, seconds=self.command_seconds)
        except TimeoutError as exc:
            raise PageError() from exc


class PageCorpus(Mapping[str, str]):
    """One command's metadata snapshot; page bodies load only when requested."""

    def __init__(
        self,
        filesystem: PageFileSystem,
        pages: Optional[dict[str, Page]] = None,
        *,
        budget: Optional[WorkBudget] = None,
        prefix: str = "/",
    ):
        self.prefix = self.canonical_prefix(prefix)
        self.filesystem = filesystem
        self._pages = pages
        self._selected: dict[str, Page] = {}
        self._prefixes: dict[str, list[str]] = {}
        self.loaded: dict[str, str] = {}
        self._read_chars = 0
        self._budget = budget or WorkBudget(filesystem.command_seconds)

    @staticmethod
    def canonical_prefix(path: str) -> str:
        from agno.knowledge.page._source import page_prefix

        if path != "/" and path.endswith("/"):
            return page_prefix(path[:-1]) + "/"
        return page_prefix(path)

    def _scoped_prefix(self, prefix: str) -> Optional[str]:
        prefix = self.canonical_prefix(prefix)
        if prefix.startswith(self.prefix):
            return prefix
        if self.prefix.startswith(prefix):
            return self.prefix
        return None

    def _check(self) -> None:
        try:
            self._budget.remaining()
        except TimeoutError as exc:
            raise PageError() from exc

    def _list(self, prefix: str) -> dict[str, Page]:
        scoped = self._scoped_prefix(prefix)
        if scoped is None:
            return {}
        prefix = scoped
        for _ in range(2):
            pages: dict[str, Page] = {}
            cursor = None
            while True:
                self._check()
                result = self.filesystem.knowledge.list_pages(prefix=prefix, cursor=cursor, limit=200)
                if result.restart_required:
                    break
                pages.update((page.path, page) for page in result.pages if page.path.startswith(prefix))
                if len(pages) > self.filesystem.max_catalog_entries:
                    raise PageError()
                cursor = result.next_cursor
                if cursor is None:
                    return pages
        raise PageError()

    @property
    def pages(self) -> dict[str, Page]:
        if self._pages is None:
            self._pages = self._list(self.prefix)
            self.loaded.clear()
            self._selected.clear()
        return self._pages

    def __bool__(self) -> bool:
        self._check()
        if self._pages is not None:
            return bool(self._pages)
        kwargs = {} if self.prefix == "/" else {"prefix": self.prefix}
        return bool(self.filesystem.knowledge.list_pages(limit=1, **kwargs).pages)

    def paths_under(self, prefix: str) -> list[str]:
        scoped = self._scoped_prefix(prefix)
        if scoped is None:
            return []
        prefix = scoped
        if self._pages is not None or prefix == "/":
            return [path for path in self.pages if path.startswith(prefix)]
        if prefix not in self._prefixes:
            scoped_pages = self._list(prefix)
            self._selected.update(scoped_pages)
            for path in scoped_pages:
                self.loaded.pop(path, None)
            self._prefixes[prefix] = list(scoped_pages)
        return self._prefixes[prefix]

    def __iter__(self) -> Iterator[str]:
        return iter(self.pages)

    def has_directory(self, prefix: str) -> bool:
        self._check()
        scoped = self._scoped_prefix(prefix)
        if scoped is None:
            return False
        prefix = scoped
        if self._pages is not None:
            return any(path.startswith(prefix) for path in self._pages)
        if prefix in self._prefixes:
            return bool(self._prefixes[prefix])
        result = self.filesystem.knowledge.list_pages(prefix=prefix, limit=1)
        return any(page.path.startswith(prefix) for page in result.pages)

    def __len__(self) -> int:
        return len(self.pages)

    def _metadata_contains(self, path: str) -> bool:
        from agno.knowledge.page._source import page_path

        self._check()
        if not path.endswith(".md"):
            return False
        # Public page APIs return canonical paths even when the caller uses URL encoding.
        path = page_path(path)
        if not path.startswith(self.prefix):
            return False
        if self._pages is not None:
            return path in self._pages
        if path in self._selected:
            return True
        result = self.filesystem.knowledge.list_pages(prefix=path, limit=1)
        return any(page.path == path for page in result.pages)

    def __contains__(self, path: object) -> bool:
        if not isinstance(path, str) or not path.endswith(".md"):
            return False
        path = self.canonical_prefix(path)
        if not path.startswith(self.prefix):
            return False
        if self._pages is not None:
            return path in self._pages
        if path in self._selected:
            return True
        try:
            self[path]
            return True
        except KeyError:
            return False

    def __getitem__(self, path: str) -> str:
        from agno.knowledge.page._source import page_path

        self._check()
        path = page_path(path)
        if not path.startswith(self.prefix):
            raise KeyError(path)
        page = self._pages[path] if self._pages is not None else self._selected.get(path)
        if path in self.loaded:
            return self.loaded[path]
        fs = self.filesystem
        key = (page.content_id, page.revision, page.filesystem_version) if page is not None else None
        with fs._body_lock:
            cached = fs._bodies.get(key) if key is not None else None
            if cached is not None and key is not None:
                fs._bodies.move_to_end(key)
        revision = page.revision if page is not None else None
        try:
            if cached is not None:
                # Even a retained mapping must not resurrect an unpublished revision.
                fs.knowledge.read_page(path, revision=revision, max_chars=1)
                body = cached[0]
            else:
                parts, offset = [], 0
                while True:
                    self._check()
                    result = fs.knowledge.read_page(path, revision=revision, offset=offset, max_chars=24000)
                    self._read_chars += len(result.text)
                    if self._read_chars > fs.max_read_chars:
                        raise PageError()
                    parts.append(result.text)
                    if result.next_offset is None:
                        break
                    if result.next_offset <= offset:
                        raise PageError()
                    offset = result.next_offset
                    if revision is None:
                        revision = result.revision
                body = "".join(parts)
        except PageNotFound:
            if page is not None or revision is not None:
                raise  # A selected publication disappeared; retain the typed storage error.
            raise KeyError(path) from None
        if cached is not None:
            self._read_chars += len(body)
            if self._read_chars > fs.max_read_chars:
                raise PageError()
        self.loaded[path] = body
        size = len(body.encode("utf-8"))
        with fs._body_lock:
            if key is not None and key not in fs._bodies and size <= fs.max_cached_bytes:
                fs._bodies[key] = (body, size)
                fs._body_bytes += size
                while fs._body_bytes > fs.max_cached_bytes or len(fs._bodies) > fs.max_cached_entries:
                    fs._body_bytes -= fs._bodies.popitem(last=False)[1][1]
        return body

    def grep(self, query: str, *, prefix: str, ignore_case: bool) -> GrepResult:
        self._check()
        scoped = self._scoped_prefix(prefix)
        if scoped is None:
            return GrepResult()
        return self.filesystem.knowledge.grep_pages(query, prefix=scoped, ignore_case=ignore_case, limit=100)

    @property
    def stamp(self) -> str:
        return hashlib.sha256(
            "\n".join(f"{p.path}:{p.revision}:{p.filesystem_version}" for p in self.pages.values()).encode()
        ).hexdigest()
