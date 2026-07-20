"""PlaywrightBackend — local browser automation via Playwright SDK.

Provides direct Playwright browser control with video recording, PDF
generation, console capture, and network request logging.

Requires:
    pip install playwright
    playwright install chromium
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agno.context.backend import ContextBackend
from agno.context.provider import Status

if TYPE_CHECKING:
    from agno.tools import Toolkit


class PlaywrightBackend(ContextBackend):
    """Backend for `BrowserContextProvider` using local Playwright browser."""

    def __init__(
        self,
        *,
        headless: bool = True,
    ) -> None:
        self.headless = headless
        self._tools: Toolkit | None = None

    def status(self) -> Status:
        mode = "headless" if self.headless else "headed"
        return Status(ok=True, detail=f"playwright (local, {mode})")

    async def astatus(self) -> Status:
        return self.status()

    def get_tools(self) -> list[Toolkit]:
        if self._tools is None:
            self._tools = self._build_tools()
        return [self._tools]

    def _build_tools(self) -> Toolkit:
        from agno.tools.playwright import PlaywrightTools

        return PlaywrightTools(
            headless=self.headless,
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
