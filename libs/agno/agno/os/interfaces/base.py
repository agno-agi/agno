from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Union

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

    # If True, interface handles its own auth (e.g. Slack/Telegram webhook signatures) and is excluded from AuthMiddleware
    authenticates_own_requests: bool = False

    router: APIRouter

    @abstractmethod
    def get_router(self, use_async: bool = True, **kwargs) -> APIRouter:
        pass

    def get_scope_mappings(self) -> Dict[str, List[str]]:
        """RBAC scope requirements for this interface's routes, keyed by "METHOD /path".

        An interface that executes agents/teams/workflows MUST override this so its routes
        are authorization-gated. Returning ``{}`` (the default) leaves every route unmapped,
        which the RBAC layer treats as *allow* -- so a non-self-authenticating interface that
        runs entities but returns no mappings is reachable by any authenticated token
        regardless of scopes. AgentOS merges these at startup (see ``_add_auth_middleware``),
        so entries reflect the interface's *actual* mount prefix.
        """
        return {}
