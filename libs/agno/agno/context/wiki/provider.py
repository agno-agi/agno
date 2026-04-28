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
    ) -> None:
        super().__init__(id=id, name=name, mode=mode, model=model)
        self.backend: WikiBackend = backend
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
        self._setup_done = True

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
        return (
            f"`{self.name}`: call `{self.query_tool_name}(question)` to read the wiki. "
            f"Use `{self.update_tool_name}(instruction)` to add or edit pages."
        )

    # ------------------------------------------------------------------
    # Mode resolution
    # ------------------------------------------------------------------

    def _default_tools(self) -> list:
        return [self._query_tool(), self._update_tool()]

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
            self._write_agent = Agent(
                id=f"{self.id}-write",
                name=f"{self.name} Write",
                model=self.model,
                instructions=self.write_instructions_text.replace("{path}", str(self.backend.path)),
                tools=[self._build_write_tools()],
                markdown=True,
            )
        return self._write_agent

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
