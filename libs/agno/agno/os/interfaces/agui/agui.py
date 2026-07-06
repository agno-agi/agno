"""Main class for the AG-UI app, used to expose an Agno Agent or Team in an AG-UI compatible format."""

from typing import List, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.os.interfaces.agui.router import DEFAULT_USER_ID_CLAIM, attach_routes
from agno.os.interfaces.base import BaseInterface
from agno.team import Team
from agno.team.remote import RemoteTeam


class AGUI(BaseInterface):
    type = "agui"

    router: APIRouter

    def __init__(
        self,
        agent: Optional[Union[Agent, RemoteAgent]] = None,
        team: Optional[Union[Team, RemoteTeam]] = None,
        prefix: str = "",
        tags: Optional[List[str]] = None,
        user_id_claim: Optional[str] = None,
        dependencies_claims: Optional[List[str]] = None,
    ):
        """
        Initialize the AGUI interface.

        Args:
            agent: The agent to expose via AG-UI
            team: The team to expose via AG-UI
            prefix: Custom prefix for the router (e.g., "/agui/v1", "/chat/public")
            tags: Custom tags for the router (e.g., ["AGUI", "Chat"], defaults to ["AGUI"])
            user_id_claim: Key in forwardedProps to extract as user_id (defaults to "user_id").
                Use this when your frontend's decoded JWT places the user identifier under a
                different name (e.g. "sub").
            dependencies_claims: Keys in forwardedProps to extract and pass to the underlying
                agent/team as a `dependencies` dict. When non-empty, the run is also called
                with `add_dependencies_to_context=True` so the values become available in
                prompt templates (e.g. as `{email}` if "email" is in this list). Missing keys
                are silently skipped.
        """
        self.agent = agent
        self.team = team
        self.prefix = prefix
        self.tags = tags or ["AGUI"]
        self.user_id_claim = user_id_claim or DEFAULT_USER_ID_CLAIM
        self.dependencies_claims = dependencies_claims or []

        if not (self.agent or self.team):
            raise ValueError("AGUI requires an agent or a team")

    def get_router(self) -> APIRouter:
        self.router = APIRouter(prefix=self.prefix, tags=self.tags)  # type: ignore

        self.router = attach_routes(
            router=self.router,
            agent=self.agent,
            team=self.team,
            user_id_claim=self.user_id_claim,
            dependencies_claims=self.dependencies_claims,
        )

        return self.router
