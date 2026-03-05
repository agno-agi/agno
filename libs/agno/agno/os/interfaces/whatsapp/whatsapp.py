from typing import List, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.whatsapp.router import attach_routes
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow


class Whatsapp(BaseInterface):
    type = "whatsapp"

    router: APIRouter

    def __init__(
        self,
        agent: Optional[Union[Agent, RemoteAgent]] = None,
        team: Optional[Union[Team, RemoteTeam]] = None,
        workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
        prefix: str = "/whatsapp",
        tags: Optional[List[str]] = None,
        show_reasoning: bool = False,
        send_user_number_to_context: bool = False,
        # Falls back to env vars when None
        access_token: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        verify_token: Optional[str] = None,
    ):
        self.agent = agent
        self.team = team
        self.workflow = workflow
        self.prefix = prefix
        # Tags group endpoints in OpenAPI docs
        self.tags = tags or ["Whatsapp"]
        self.show_reasoning = show_reasoning
        self.send_user_number_to_context = send_user_number_to_context
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.verify_token = verify_token

        if not (self.agent or self.team or self.workflow):
            raise ValueError("Whatsapp requires an agent, team, or workflow")

    def get_router(self) -> APIRouter:
        self.router = APIRouter(prefix=self.prefix, tags=self.tags)  # type: ignore

        self.router = attach_routes(
            router=self.router,
            agent=self.agent,
            team=self.team,
            workflow=self.workflow,
            show_reasoning=self.show_reasoning,
            send_user_number_to_context=self.send_user_number_to_context,
            access_token=self.access_token,
            phone_number_id=self.phone_number_id,
            verify_token=self.verify_token,
        )

        return self.router
