"""BrowserbaseBackend — cloud browser automation via Browserbase.

Browserbase provides managed cloud browsers with built-in features like
ad blocking, CAPTCHA solving, and session recording. Use this backend
when you need cloud-hosted browsers instead of local Playwright.

Requires:
    pip install browserbase playwright
    BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID environment variables
"""

from __future__ import annotations

from os import getenv
from typing import TYPE_CHECKING

from agno.context.backend import ContextBackend
from agno.context.provider import Status

if TYPE_CHECKING:
    from agno.tools import Toolkit


class BrowserbaseBackend(ContextBackend):
    """Backend for `BrowserContextProvider` using Browserbase cloud browsers."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        project_id: str | None = None,
    ) -> None:
        self.api_key = api_key or getenv("BROWSERBASE_API_KEY")
        self.project_id = project_id or getenv("BROWSERBASE_PROJECT_ID")
        self._tools: Toolkit | None = None

    def status(self) -> Status:
        missing = []
        if not self.api_key:
            missing.append("BROWSERBASE_API_KEY")
        if not self.project_id:
            missing.append("BROWSERBASE_PROJECT_ID")
        if missing:
            return Status(ok=False, detail=f"browserbase: missing {', '.join(missing)}")
        return Status(ok=True, detail="browserbase (cloud)")

    async def astatus(self) -> Status:
        return self.status()

    def get_tools(self) -> list[Toolkit]:
        if self._tools is None:
            self._tools = self._build_tools()
        return [self._tools]

    def _build_tools(self) -> Toolkit:
        from agno.tools.browserbase import BrowserbaseTools

        return BrowserbaseTools(
            api_key=self.api_key,
            project_id=self.project_id,
            all=True,
        )

    async def asetup(self) -> None:
        if self._tools is None:
            self._tools = self._build_tools()

    async def aclose(self) -> None:
        if self._tools is not None:
            try:
                await self._tools.aclose_session()  # type: ignore[attr-defined]
            except Exception:
                pass
        self._tools = None
