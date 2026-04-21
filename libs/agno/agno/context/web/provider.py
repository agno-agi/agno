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
        mode: ContextMode = ContextMode.default,
        model: Model | None = None,
    ) -> None:
        super().__init__(id=id, name=name, mode=mode, model=model)
        self.backend = backend
        self._agent: Agent | None = None

    def status(self) -> Status:
        return self.backend.status()

    async def astatus(self) -> Status:
        return await self.backend.astatus()

    def query(self, question: str) -> Answer:
        agent = self._ensure_agent()
        return answer_from_run(agent.run(question))

    async def aquery(self, question: str) -> Answer:
        agent = self._ensure_agent()
        return answer_from_run(await agent.arun(question))

    def instructions(self) -> str:
        if self.mode == ContextMode.agent:
            return (
                f"`{self.name}`: call `{self.query_tool_name}(question)` for web research. "
                "Returns a synthesized answer with cited URLs."
            )
        return (
            f"`{self.name}`: search the web for URLs/snippets, then fetch full pages when you need depth. "
            "Cite every URL you use."
        )

    # ------------------------------------------------------------------
    # Mode resolution
    # ------------------------------------------------------------------

    def _default_tools(self) -> list:
        return self._all_tools()

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
            role="Research the web and return cited answers",
            model=self.model,
            instructions=_AGENT_INSTRUCTIONS,
            tools=self.backend.get_tools(),
            markdown=True,
        )


_AGENT_INSTRUCTIONS = """\
You answer questions by searching the web and reading relevant pages.

Workflow:

1. **Search first.** Use the search tool with a focused natural-language
   query. Read the top URLs + excerpts.
2. **Fetch when depth is needed.** If the question asks about a specific
   URL, or the excerpts don't answer it, fetch the page(s) and read.
3. **Synthesize from at least two sources** when possible. Cross-check.
4. **Cite every URL you used.** Inline links are fine; include them so
   the caller can verify.
5. **Say so plainly** if the web doesn't have a confident answer.

You are read-only. Never submit forms, never follow redirects to auth
flows, never output credentials.
"""
