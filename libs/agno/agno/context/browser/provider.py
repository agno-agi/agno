"""
Browser Context Provider
========================

Browser automation via a configurable backend. Wraps backend tools in a
sub-agent that handles natural-language browsing requests.

Default backend is ``PlaywrightMCPBackend``, which runs Playwright's
MCP server and exposes all browser tools (navigate, click, type, etc.).
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


WRITE_TOOLS = [
    "browser_type",
    "browser_select_option",
    "browser_press_key",
    "browser_file_upload",
]


class BrowserContextProvider(ContextProvider):
    """Browser automation via a configurable backend.

    Args:
        backend: The browser backend (e.g. PlaywrightMCPBackend). If None,
            creates a PlaywrightMCPBackend with default settings.
        write: If False (default), write tools are excluded (type, select_option,
            press_key, file_upload). If True, all tools are available.
        headless: Whether to run the browser in headless mode (only used if
            backend is None).
    """

    def __init__(
        self,
        backend: ContextBackend | None = None,
        *,
        id: str = "browser",
        name: str = "Browser",
        instructions: str | None = None,
        mode: ContextMode = ContextMode.default,
        model: Model | None = None,
        write: bool = False,
        headless: bool = True,
    ) -> None:
        super().__init__(id=id, name=name, mode=mode, model=model)
        self.backend = backend if backend is not None else self._create_default_backend(write, headless)
        self.instructions_text = instructions if instructions is not None else DEFAULT_BROWSER_INSTRUCTIONS
        self._agent: Agent | None = None

    def _create_default_backend(self, write: bool, headless: bool) -> ContextBackend:
        from agno.context.browser.playwright_mcp import PlaywrightMCPBackend

        exclude = None if write else WRITE_TOOLS
        return PlaywrightMCPBackend(headless=headless, exclude_tools=exclude)

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
        raise NotImplementedError(
            "BrowserContextProvider does not support sync query(); use aquery() (MCP sessions are async-only)."
        )

    async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        agent = self._ensure_agent()
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(await agent.arun(question, **kwargs))

    # ------------------------------------------------------------------
    # Mode resolution
    # ------------------------------------------------------------------

    # Wrap in a query_browser sub-agent by default so the calling agent
    # gets a synthesized answer back instead of orchestrating raw browser
    # tools. mode=tools surfaces the backend's tools flat.
    def _default_tools(self) -> list:
        return [self._query_tool()]

    def _all_tools(self) -> list:
        return self.backend.get_tools()

    # ------------------------------------------------------------------
    # Sub-agent
    # ------------------------------------------------------------------

    async def _aget_query_agent(self, run_context):
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
You browse the web to find information.

## Workflow

1. **Navigate first.** Use the navigate tool to go to a URL.

2. **Take a snapshot.** Use the snapshot tool to get the page's accessibility
   tree. This shows interactive elements with their targets.

3. **Use screenshots sparingly.** Only use the screenshot tool when you
   need visual layout, images, or content not in the accessibility tree.

4. **Extract information.** Read the snapshot to find what you need. Quote
   relevant text verbatim. Include URLs for pages you visit.

5. **Follow links via URL.** Extract the href from the snapshot and navigate
   to it directly. If direct navigation isn't possible and interaction tools
   are available, use click/type as a fallback.

## Safety

- You are operating a real browser. Actions affect real websites.
- Never submit forms with sensitive data unless explicitly instructed.
- Never authenticate or enter credentials.
- If a page asks for login, report it and stop.
"""
