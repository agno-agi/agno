"""
Web Context Provider
====================

Makes the web queryable by an agent. A `ContextBackend` handles
search + fetch; the provider glues it onto the agent. Swap backends
without touching the agent interface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agno.agent import Agent
from agno.context._utils import answer_from_run
from agno.context.backend import ContextBackend
from agno.context.mode import ContextMode
from agno.context.provider import Answer, ContextProvider, Status
from agno.run import RunContext

if TYPE_CHECKING:
    from agno.models.base import Model


class WebContextProvider(ContextProvider):
    """Web research via a configurable backend."""

    def __init__(
        self,
        backend: ContextBackend,
        *,
        id: str = "web",
        name: str = "Web",
        instructions: str | None = None,
        mode: ContextMode = ContextMode.default,
        model: Model | None = None,
    ) -> None:
        super().__init__(id=id, name=name, mode=mode, model=model)
        self.backend = backend
        self.instructions_text = instructions if instructions is not None else DEFAULT_WEB_INSTRUCTIONS
        self._agent: Agent | None = None

    def status(self) -> Status:
        return self.backend.status()

    async def astatus(self) -> Status:
        return await self.backend.astatus()

    async def asetup(self) -> None:
        await self.backend.asetup()

    async def aclose(self) -> None:
        self._agent = None
        await self.backend.aclose()

    def query(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        agent = self._ensure_agent()
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(agent.run(question, **kwargs))

    async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        agent = self._ensure_agent()
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(await agent.arun(question, **kwargs))

    def instructions(self) -> str:
        if self.mode == ContextMode.tools:
            return (
                f"`{self.name}`: search the web for URLs/snippets, then fetch full pages when you need depth. "
                "Cite every URL you use."
            )
        return (
            f"`{self.name}`: call `{self.query_tool_name}(question)` for web research. "
            "Returns a synthesized answer with cited URLs."
        )

    # ------------------------------------------------------------------
    # Mode resolution
    # ------------------------------------------------------------------

    # Wrap in a `query_web` sub-agent by default so the calling agent
    # gets a synthesized, cited answer back instead of orchestrating raw
    # search + fetch itself. mode=tools still surfaces the backend's
    # tools flat for callers that want to drive search directly.
    def _default_tools(self) -> list:
        return [self._query_tool()]

    def _all_tools(self) -> list:
        return self.backend.get_tools()

    # ------------------------------------------------------------------
    # Sub-agent — built lazily for agent mode and programmatic query()
    # ------------------------------------------------------------------

    def _ensure_agent(self) -> Agent:
        if self._agent is None:
            self._agent = self._build_agent()
        return self._agent

    def _build_agent(self) -> Agent:
        return Agent(
            id=self.id,
            name=self.name,
            model=self.model,
            instructions=self.instructions_text,
            tools=self.backend.get_tools(),
            markdown=True,
        )


DEFAULT_WEB_INSTRUCTIONS = """\
You answer questions by searching the web and reading relevant pages.

Workflow:

1. **Search first.** Use the search tool with a focused natural-language
   query. Read the top URLs + excerpts.
2. **Fetch when depth is needed.** If the question asks about a specific
   URL, or the excerpts don't answer it, fetch the page(s) and read.
3. **Synthesize from at least two sources** when possible. Cross-check.
4. **Cite every URL you used.** Inline links are fine; include them so
   the caller can verify.
5. **Say so plainly** if the web doesn't have a confident answer. Don't
   hedge with "likely" or "probably" when you're guessing — distinguish
   "sources agree" from "my guess". No answer is fine; a hedged guess
   dressed as an answer is not.

You are read-only. Never submit forms, never follow redirects to auth
flows, never output credentials.
"""
