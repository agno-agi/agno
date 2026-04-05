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
        """Return an optional asynccontextmanager lifespan for this interface.

        Interfaces that need startup/shutdown behaviour (e.g. Slack Socket Mode)
        can override this method.  AgentOS will include the returned lifespan in
        its combined app lifespan so the interface starts and stops alongside the
        FastAPI application.
        """
        return None
