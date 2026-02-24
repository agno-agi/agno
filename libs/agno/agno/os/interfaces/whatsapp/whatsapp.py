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
        show_reasoning: bool = True,
        send_user_number_to_context: bool = False,
    ):
        self.agent = agent
        self.team = team
        self.workflow = workflow
        self.prefix = prefix
        self.tags = tags or ["Whatsapp"]
        self.show_reasoning = show_reasoning
        self.send_user_number_to_context = send_user_number_to_context

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
        )

        return self.router
