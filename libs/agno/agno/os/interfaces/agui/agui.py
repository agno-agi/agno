"""Main class for the AG-UI app, used to expose an Agno Agent or Team in an AG-UI compatible format."""

from typing import List, Optional

from fastapi.routing import APIRouter

from agno.agent import Agent
from agno.os.interfaces.agui.router import attach_routes
from agno.os.interfaces.base import BaseInterface
from agno.team import Team


class AGUI(BaseInterface):
    type = "agui"

    router: APIRouter

    def __init__(
        self,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
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
            user_id_claim: Claim to extract user ID from AGUI forwardedProps (defaults to "user_id")
            dependencies_claims: List of claims to extract from AGUI forwardedProps
        """
        self.agent = agent
        self.team = team
        self.prefix = prefix
        self.tags = tags or ["AGUI"]
        self.user_id_claim = user_id_claim or "user_id"
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
        )  # type: ignore

        return self.router
