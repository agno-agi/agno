"""
Wiki Context Provider
=====================

Read + write access to a directory of markdown files. Two tools:

- ``query_<id>`` — natural-language reads, backed by a sub-agent with
  the ``Workspace`` toolkit's read tools (list/search/read).
- ``update_<id>`` — natural-language writes, backed by a sub-agent
  with the ``Workspace`` toolkit's write tools (write/edit). After
  the sub-agent returns, the backend's ``commit_after_write`` hook
  runs (no-op for ``FileSystemBackend``, commit + rebase + push for
  ``GitBackend``).

Pluggable backend so the agent surface stays identical whether the
wiki is just a local folder or a clone of a GitHub repo. See
``agno.context.wiki.backend`` for the two ship-by-default backends.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from agno.agent import Agent
from agno.context._utils import answer_from_run
from agno.context.backend import ContextBackend
from agno.context.mode import ContextMode
from agno.context.provider import Answer, ContextProvider, Status
from agno.context.wiki.backend import CommitSummary, WikiBackend
from agno.run import RunContext
from agno.tools.workspace import Workspace
from agno.utils.log import log_info

if TYPE_CHECKING:
    from agno.models.base import Model


class WikiContextProvider(ContextProvider):
    """Read + write access to a directory of markdown files via two tools."""

    def __init__(
        self,
        *,
        backend: WikiBackend,
        id: str = "wiki",
        name: str | None = None,
        read_instructions: str | None = None,
        write_instructions: str | None = None,
        mode: ContextMode = ContextMode.default,
        model: Model | None = None,
        read: bool = True,
        write: bool = True,
        web: ContextBackend | None = None,
    ) -> None:
        super().__init__(id=id, name=name, mode=mode, model=model, read=read, write=write)
        self.backend: WikiBackend = backend
        # Optional web backend for ingestion. When set, the write
        # sub-agent gets the backend's tools (typically web_search +
        # web_fetch) on top of the workspace tools — so requests like
        # "add this paper to the wiki" can fetch the URL, digest it,
        # and write a page in one update call. Reads stay scoped to
        # the wiki on purpose: a "what does the wiki say" query
        # should answer from the wiki, not silently consult the web.
        self.web: ContextBackend | None = web
        self.read_instructions_text = (
            read_instructions if read_instructions is not None else DEFAULT_WIKI_READ_INSTRUCTIONS
        )
        self.write_instructions_text = (
            write_instructions if write_instructions is not None else DEFAULT_WIKI_WRITE_INSTRUCTIONS
        )
        self._read_agent: Agent | None = None
        self._write_agent: Agent | None = None
        # Serialises sync + write so a scheduled `provider.sync()` can't
        # race a write that's mid-commit. Reads are intentionally
        # lock-free — slight staleness is the right tradeoff for latency.
        self._git_lock: asyncio.Lock = asyncio.Lock()
        self._setup_done: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def asetup(self) -> None:
        if self._setup_done:
            return
        await self.backend.setup()
        if self.web is not None:
            await self.web.asetup()
        self._setup_done = True

    async def aclose(self) -> None:
        # Mirror WebContextProvider's pattern: drop the cached
        # sub-agent so a re-setup builds fresh tools, then forward
        # close to the web backend (its tools may hold a session).
        self._write_agent = None
        if self.web is not None:
            await self.web.aclose()

    async def sync(self) -> None:
        """Bring the local wiki up-to-date with the source of truth.

        For schedulers / external triggers — use this rather than poking
        ``backend.sync()`` directly so we hold the same lock writes use.
        Idempotent. No-op for ``FileSystemBackend``.
        """
        await self.asetup()
        async with self._git_lock:
            await self.backend.sync()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> Status:
        return self.backend.status()

    async def astatus(self) -> Status:
        return await self.backend.astatus()

    # ------------------------------------------------------------------
    # Query / update
    # ------------------------------------------------------------------

    def query(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        return asyncio.run(self.aquery(question, run_context=run_context))

    async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        await self.asetup()
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(await self._ensure_read_agent().arun(question, **kwargs))

    def update(self, instruction: str, *, run_context: RunContext | None = None) -> Answer:
        return asyncio.run(self.aupdate(instruction, run_context=run_context))

    async def aupdate(self, instruction: str, *, run_context: RunContext | None = None) -> Answer:
        await self.asetup()
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        async with self._git_lock:
            # Pull before writing so the sub-agent sees the latest
            # state (matters for git, no-op for FS). If sync fails,
            # we surface the error rather than committing on top of
            # stale content.
            await self.backend.sync()
            output = await self._ensure_write_agent().arun(instruction, **kwargs)
            answer = answer_from_run(output)

            commit: CommitSummary | None = await self.backend.commit_after_write(model=self.model)

        if commit is not None:
            log_info(
                f"WikiContextProvider[{self.id}] committed {commit.sha[:8]} "
                f"({commit.files_changed} file(s)): {commit.message}"
            )
            note = f"\n\nCommitted {commit.sha[:8]} ({commit.files_changed} file(s)): {commit.message}"
            answer = Answer(results=answer.results, text=(answer.text or "") + note)
        return answer

    def instructions(self) -> str:
        if self.mode == ContextMode.tools:
            return (
                f"`{self.name}`: read-only `read_file` / `list_files` / `search_content` over the wiki "
                f"at {self.backend.path}. Writes require mode=default (two-tool surface)."
            )
        if self.mode == ContextMode.agent:
            return f"`{self.name}`: call `{self.query_tool_name}(question)` to read the wiki."
        # default mode — describe the actual surface based on flags + web
        parts: list[str] = [f"`{self.name}`:"]
        if self.read:
            parts.append(f"call `{self.query_tool_name}(question)` to read the wiki.")
        if self.write:
            update_hint = f"Use `{self.update_tool_name}(instruction)` to add or edit pages"
            if self.web is not None:
                update_hint += " — pass a URL or 'find sources on X' and it will fetch the web before writing"
            update_hint += "."
            parts.append(update_hint)
        return " ".join(parts)

    # ------------------------------------------------------------------
    # Mode resolution
    # ------------------------------------------------------------------

    def _default_tools(self) -> list:
        return self._read_write_tools()

    def _all_tools(self) -> list:
        # mode=tools is read-only on purpose. The default surface
        # already gives two distinct tools (query_<id> / update_<id>);
        # collapsing both into a flat Workspace tool list would expose
        # raw write tools without the commit hook ever firing.
        return [self._build_read_tools()]

    # ------------------------------------------------------------------
    # Sub-agents
    # ------------------------------------------------------------------

    def _ensure_read_agent(self) -> Agent:
        if self._read_agent is None:
            self._read_agent = Agent(
                id=f"{self.id}-read",
                name=f"{self.name} Read",
                model=self.model,
                instructions=self.read_instructions_text.replace("{path}", str(self.backend.path)),
                tools=[self._build_read_tools()],
                markdown=True,
            )
        return self._read_agent

    def _ensure_write_agent(self) -> Agent:
        if self._write_agent is None:
            tools: list = [self._build_write_tools()]
            if self.web is not None:
                # Append the web backend's tools so the same sub-agent
                # can fetch a URL or run a web search before writing.
                tools.extend(self.web.get_tools())
            instructions = self._compose_write_instructions()
            self._write_agent = Agent(
                id=f"{self.id}-write",
                name=f"{self.name} Write",
                model=self.model,
                instructions=instructions,
                tools=tools,
                markdown=True,
            )
        return self._write_agent

    def _compose_write_instructions(self) -> str:
        """Build the write sub-agent's instructions, optionally
        appending a web-ingestion stanza when ``web`` is wired."""
        text = self.write_instructions_text.replace("{path}", str(self.backend.path))
        if self.web is None:
            return text
        return text + "\n\n" + WIKI_WEB_INGEST_INSTRUCTIONS

    def _build_read_tools(self) -> Workspace:
        return Workspace(
            root=self.backend.path,
            allowed=Workspace.READ_TOOLS,
        )

    def _build_write_tools(self) -> Workspace:
        return Workspace(
            root=self.backend.path,
            # Allow reads + writes auto-pass — the sub-agent is acting
            # on a wiki the caller has already entrusted to it. The
            # provider's commit hook handles audit and the git history
            # is the source of truth for what changed.
            allowed=["read", "list", "search", "write", "edit"],
        )


DEFAULT_WIKI_READ_INSTRUCTIONS = """\
You answer questions by reading wiki pages under {path}.

Workflow:
1. **Map the wiki first.** `list_files(recursive=True)` to see what's available.
   Don't guess at filenames.
2. **Search by content.** `search_content(query)` surfaces pages whose text
   matches; faster than reading every file.
3. **Read what you cite.** `read_file(path)` for the pages you actually quote.
   Don't paraphrase — quote the exact text you read.
4. **Cite paths relative to the wiki root.** Every claim points to a file path.
   If a question doesn't match any page, say so plainly — don't fabricate.

You are read-only. Writes happen through the update tool.
"""


DEFAULT_WIKI_WRITE_INSTRUCTIONS = """\
You add to and edit wiki pages under {path}.

Workflow:
1. **Look before writing.** `list_files(recursive=True)` and `search_content`
   first — don't create a duplicate page when one already exists.
2. **Edit existing pages with `edit_file`** — small targeted replacements
   keep the diff readable. Read the file first so the `old_str` you pass
   is exact.
3. **Create new pages with `write_file`.** Use kebab-case filenames under
   sensible directories (e.g. `runbooks/deploys.md`). Markdown only;
   include a single `# Title` heading at the top.
4. **Report what you wrote** — list the file paths you touched and a one-
   sentence summary of the change. The commit message and git history
   capture the rest.

Keep changes minimal and focused. The provider commits and pushes after
you return; do not invoke git yourself.
"""


WIKI_WEB_INGEST_INSTRUCTIONS = """\
## Ingesting from the web

You also have web search and fetch tools (e.g. `web_search`, `web_fetch`,
or backend-equivalents). When the user gives you a URL, asks you to
"add this paper / article", or asks you to find sources on a topic:

1. **Fetch first.** Use the web tool to retrieve the source material
   before writing anything. Don't summarise from memory.
2. **Digest, don't dump.** Convert what you fetched into clean markdown
   suitable for the wiki — a `# Title`, a brief context paragraph,
   key sections, and a `## Source` footer linking back to the URL.
   Drop nav cruft, ad text, and boilerplate.
3. **Pick the right path.** Use a sensible folder (`papers/`, `articles/`,
   `runbooks/`) and a kebab-case filename derived from the title.
4. **Cite the source URL.** Every ingested page must end with a
   `## Source` section pointing at the original URL with the date.

Search before fetching when the user gives a topic instead of a URL.
Pick the most relevant result rather than ingesting every hit.
"""
