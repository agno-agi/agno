"""CopilotKit FastAPI application helper.

Usage:
```
from agno.app.copilotkit.app import CopilotKitApp
from agno.agent.builtins import EchoAgent

agent = EchoAgent()
app = CopilotKitApp(agent=agent).get_app()
```
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, FastAPI

from agno.agent.agent import Agent
from agno.app.copilotkit.router import get_router as get_copilotkit_router
from agno.app.fastapi.app import FastAPIApp
from agno.app.settings import APIAppSettings
from agno.team.team import Team


class CopilotKitApp(FastAPIApp):
    """FastAPIApp derivative pre-configured with CopilotKit router."""

    def __init__(
        self,
        *,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
        settings: Optional[APIAppSettings] = None,
        api_app: Optional[FastAPI] = None,
        router: Optional[APIRouter] = None,
    ) -> None:
        super().__init__(
            agent=agent,
            team=team,
            settings=settings,
            api_app=api_app,
            router=router,
        )

        # Internal CopilotKit router (without prefix). Keep separate from outer prefix router.
        self._copilot_router: Optional[APIRouter] = None

    # override to inject our router
    def get_router(self) -> APIRouter:
        if self._copilot_router is None:
            self._copilot_router = get_copilotkit_router(agent=self.agent, team=self.team)
        return self._copilot_router

    # Ensure async-mode server builds also use CopilotKit router
    def get_async_router(self) -> APIRouter:  # type: ignore[override]
        # Reuse the synchronous router; endpoint functions themselves may be async.
        return self.get_router()
