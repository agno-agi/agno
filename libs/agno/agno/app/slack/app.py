import logging

from fastapi.routing import APIRouter

from agno.app.base import BaseAPIApp
from agno.app.slack.async_router import get_async_router
from agno.app.slack.sync_router import get_sync_router

logger = logging.getLogger(__name__)


class SlackAPI(BaseAPIApp):
    type = "slack"

    def get_router(self) -> APIRouter:
        return get_sync_router(agent=self.agent, team=self.team)

    def get_async_router(self) -> APIRouter:
        return get_async_router(agent=self.agent, team=self.team)
