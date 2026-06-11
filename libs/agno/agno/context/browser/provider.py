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


class BrowserContextProvider(ContextProvider):
    def __init__(
        self,
        backend: ContextBackend,
        *,
        id: str = "browser",
        name: str = "Browser",
        instructions: str | None = None,
        mode: ContextMode = ContextMode.default,
        model: Model | None = None,
        read: bool = True,
        write: bool = False,
    ) -> None:
        super().__init__(id=id, name=name, mode=mode, model=model, read=read, write=write)
        self.backend = backend
        self.instructions_text = instructions if instructions is not None else DEFAULT_BROWSER_INSTRUCTIONS
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

    def update(self, instruction: str, *, run_context: RunContext | None = None) -> Answer:
        if not self.write:
            raise NotImplementedError(f"{self.name} is read-only. Set write=True to enable interactions.")
        agent = self._ensure_agent()
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(agent.run(instruction, **kwargs))

    async def aupdate(self, instruction: str, *, run_context: RunContext | None = None) -> Answer:
        if not self.write:
            raise NotImplementedError(f"{self.name} is read-only. Set write=True to enable interactions.")
        agent = self._ensure_agent()
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(await agent.arun(instruction, **kwargs))

    def instructions(self) -> str:
        if self.mode == ContextMode.tools:
            return (
                f"`{self.name}`: use browser tools to navigate, take screenshots, and extract content from web pages."
            )
        if self.write:
            return (
                f"`{self.name}`: call `{self.query_tool_name}(question)` to browse the web and find information. "
                f"Use `{self.update_tool_name}(instruction)` to interact with pages (click, type, submit forms)."
            )
        return (
            f"`{self.name}`: call `{self.query_tool_name}(question)` to browse the web, "
            "navigate pages, and extract information."
        )

    # ------------------------------------------------------------------
    # Mode resolution
    # ------------------------------------------------------------------

    def _default_tools(self) -> list:
        return self._read_write_tools()

    def _all_tools(self) -> list:
        return self.backend.get_tools()

    # ------------------------------------------------------------------
    # Sub-agent — built lazily
    # ------------------------------------------------------------------

    async def _aget_query_agent(self, run_context):
        return self._ensure_agent()

    async def _aget_update_agent(self, run_context):
        return self._ensure_agent()

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


DEFAULT_BROWSER_INSTRUCTIONS = """\
You browse the web to find information and complete tasks.

## Workflow

1. **Navigate first.** Use `browser_navigate` to go to a URL. If you need
   to find something, start at a search engine or the site's homepage.

2. **Take a snapshot.** Use `browser_snapshot` to get the page's accessibility
   tree. This shows you all interactive elements with their refs. Reading
   the snapshot is more token-efficient than screenshots for most tasks.

3. **Use screenshots sparingly.** Only use `browser_screenshot` when you need
   to see visual layout, images, or content not captured in the accessibility
   tree (charts, diagrams, videos).

4. **Extract information.** Read the snapshot or screenshot to find what
   you need. Quote relevant text verbatim. Include URLs for pages you visit.

5. **Navigate between pages.** Click links (if write tools enabled) or
   navigate directly to new URLs to explore.

## Element References

The accessibility tree includes `ref` attributes for interactive elements.
Use these refs with interaction tools:
- `browser_click(element="ref", ref="e42")` — click element with ref e42
- `browser_type(element="ref", ref="e42", text="...")` — type into element

## Safety

- You are operating a real browser. Actions affect real websites.
- Never submit forms with sensitive data unless explicitly instructed.
- Never authenticate or enter credentials.
- Avoid rapid repeated requests to the same site.
- If a page asks for login, report it and stop.
"""
