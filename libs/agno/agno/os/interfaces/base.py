from abc import ABC, abstractmethod
from typing import Any, List, Optional, Union

from fastapi import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow


class BaseInterface(ABC):
    type: str
    version: str = "1.0"
    agent: Optional[Union[Agent, RemoteAgent]] = None
    team: Optional[Union[Team, RemoteTeam]] = None
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None

    prefix: str
    tags: List[str]

    router: APIRouter

    @abstractmethod
    def get_router(self, use_async: bool = True, **kwargs) -> APIRouter:
        pass

    def get_lifespan(self) -> Optional[Any]:
        """Return a FastAPI-compatible lifespan context manager for background services, or None.

        The return value must be a callable ``(app) -> AsyncContextManager`` matching the
        FastAPI lifespan signature used by ``_combine_app_lifespans`` in ``app.py``.
        """
        return None
