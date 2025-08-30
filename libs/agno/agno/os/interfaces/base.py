from abc import ABC, abstractmethod
from typing import Optional

from fastapi import APIRouter

from agno.agent import Agent
from agno.team import Team


class BaseInterface(ABC):
    type: str
    version: str = "1.0"
    router_prefix: str = ""
    agent: Optional[Agent] = None
    team: Optional[Team] = None

    router: APIRouter

    @abstractmethod
    def get_router(self, use_async: bool = True, **kwargs) -> APIRouter:
        pass
