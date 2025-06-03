from fastapi.routing import APIRouter

from agno.app.agui.async_router import get_async_agui_router
from agno.app.base import BaseAPIApp


class AGUIApp(BaseAPIApp):
    type = "agui"

    def get_async_router(self) -> APIRouter:
        return get_async_agui_router(agent=self.agent, team=self.team)

    def get_router(self) -> APIRouter:
        return get_async_agui_router(agent=self.agent, team=self.team)
